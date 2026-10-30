"""
Adversarial Stress Test Suite for Milestone 1.
Empirical validation of CampaignState models, transitions, and payment gate.

Targets:
- src/ai_target/state/models.py
- src/ai_target/state/transitions.py
"""

import copy
import json
import math
import threading
from datetime import datetime, timezone
from typing import Any, Dict

import pytest
from pydantic import ValidationError

from ai_target.state.models import (
    CampaignState,
    CampaignStateError,
    CampaignStatus,
    ClientBrief,
    Financials,
    InvalidStateTransitionError,
    PaymentNotVerifiedError,
    PaymentVerificationError,
)
from ai_target.state.transitions import (
    ACTIVE_STATUSES,
    LEGAL_TRANSITIONS,
    can_transition,
    get_allowed_transitions,
    transition_state,
    validate_transition,
)


# ============================================================================
# 1. Payment Verification Gatekeeper Adversarial Tests
# ============================================================================

class TestAdversarialPaymentGate:
    """Stress-tests attempting to breach or bypass the payment verification hard gate."""

    @pytest.mark.parametrize(
        "falsy_val",
        [
            False,
            0,
            0.0,
            "false",
            "False",
            "0",
            "no",
            "off",
            "f",
        ],
    )
    def test_payment_verified_falsy_coercions_strictly_blocked_from_live(self, falsy_val: Any):
        """Verify that any falsy representation of payment_verified cannot enter LIVE."""
        # 1. Via Financials model validation
        fin_data: Dict[str, Any] = {"gross_budget": 1000.0, "payment_verified": falsy_val}
        financials = Financials.model_validate(fin_data)
        assert financials.payment_verified is False

        state = CampaignState(
            status=CampaignStatus.AWAITING_APPROVAL,
            financials=financials,
        )

        # 2. Blocked via transition_to (direct PaymentVerificationError)
        with pytest.raises(PaymentVerificationError):
            state.transition_to(CampaignStatus.LIVE)

        # 3. Blocked via transition_state function (direct PaymentVerificationError)
        with pytest.raises(PaymentVerificationError):
            transition_state(state, CampaignStatus.LIVE)

        # 4. Blocked via direct attribute assignment (direct PaymentVerificationError)
        with pytest.raises(PaymentVerificationError):
            state.status = CampaignStatus.LIVE

        # 5. Blocked via direct instantiation (PaymentVerificationError or wrapped ValidationError)
        with pytest.raises((PaymentVerificationError, ValidationError)):
            CampaignState(status=CampaignStatus.LIVE, financials=financials)

    def test_financials_none_strictly_blocks_live_transition(self):
        """Verify that state with financials=None is strictly blocked from LIVE."""
        state = CampaignState(
            status=CampaignStatus.AWAITING_APPROVAL,
            financials=None,
        )

        # Blocked via transition_to
        with pytest.raises(PaymentVerificationError):
            state.transition_to(CampaignStatus.LIVE)

        # Blocked via transition_state
        with pytest.raises(PaymentVerificationError):
            transition_state(state, CampaignStatus.LIVE)

        # Blocked via direct attribute assignment
        with pytest.raises(PaymentVerificationError):
            state.status = CampaignStatus.LIVE

        # Blocked via direct instantiation
        with pytest.raises((PaymentVerificationError, ValidationError)):
            CampaignState(status=CampaignStatus.LIVE, financials=None)

    def test_financials_missing_in_json_strictly_blocks_live(self):
        """Verify that raw JSON payload with status=LIVE but missing financials fails validation."""
        raw_json_no_fin = json.dumps({"status": "LIVE"})
        with pytest.raises((PaymentVerificationError, ValidationError)):
            CampaignState.model_validate_json(raw_json_no_fin)

        raw_json_null_fin = json.dumps({"status": "LIVE", "financials": None})
        with pytest.raises((PaymentVerificationError, ValidationError)):
            CampaignState.model_validate_json(raw_json_null_fin)

        raw_json_unpaid_fin = json.dumps({
            "status": "LIVE",
            "financials": {"gross_budget": 500.0, "payment_verified": False},
        })
        with pytest.raises((PaymentVerificationError, ValidationError)):
            CampaignState.model_validate_json(raw_json_unpaid_fin)

    def test_financials_revocation_in_live_state(self):
        """
        Adversarial scenario: Campaign is in LIVE (validly paid).
        Attacker attempts to set state.financials = None or unpaid Financials.
        Assignment validation should reject this illegal state mutation.
        """
        state = CampaignState(
            status=CampaignStatus.AWAITING_APPROVAL,
            financials=Financials(gross_budget=1000.0, payment_verified=True),
        )
        state.transition_to(CampaignStatus.LIVE)
        assert state.status == CampaignStatus.LIVE

        # Attempt to revoke payment by setting financials to None
        with pytest.raises((PaymentVerificationError, ValidationError)):
            state.financials = None

        # Attempt to revoke payment by setting financials to unpaid
        with pytest.raises((PaymentVerificationError, ValidationError)):
            state.financials = Financials(gross_budget=1000.0, payment_verified=False)

    def test_optimizing_transition_enforces_payment_verification_via_fsm(self):
        """
        Adversarial scenario: Attacker attempts to jump to OPTIMIZING
        from PAUSED when payment has not been verified via transition_to.
        """
        unpaid_fin = Financials(gross_budget=1000.0, payment_verified=False)
        state = CampaignState(
            status=CampaignStatus.PAUSED,
            financials=unpaid_fin,
        )

        # Transitioning to OPTIMIZING when unpaid must raise PaymentNotVerifiedError
        with pytest.raises(PaymentVerificationError):
            state.transition_to(CampaignStatus.OPTIMIZING)

        with pytest.raises(PaymentVerificationError):
            transition_state(state, CampaignStatus.OPTIMIZING)

    def test_optimizing_status_bypass_vulnerability_probe(self):
        """
        Verify that OPTIMIZING is strictly guarded against unverified payment
        in direct instantiation, attribute mutation, and model validation.
        """
        unpaid_fin = Financials(gross_budget=1000.0, payment_verified=False)

        # Probe 1: Direct instantiation in OPTIMIZING without payment must raise PaymentVerificationError
        with pytest.raises(PaymentVerificationError):
            CampaignState(
                status=CampaignStatus.OPTIMIZING,
                financials=unpaid_fin,
            )

        # Probe 2: Direct attribute assignment to OPTIMIZING without payment must raise PaymentVerificationError
        paused_state = CampaignState(
            status=CampaignStatus.PAUSED,
            financials=unpaid_fin,
        )
        with pytest.raises(PaymentVerificationError):
            paused_state.status = CampaignStatus.OPTIMIZING


# ============================================================================
# 2. Invalid State Transitions Matrix and Adversarial Inputs
# ============================================================================

class TestAdversarialTransitions:
    """Stress-tests all illegal transitions, self-loops, and corrupted inputs."""

    ALL_STATUSES = list(CampaignStatus)

    @pytest.mark.parametrize("start_status", ALL_STATUSES)
    @pytest.mark.parametrize("target_status", ALL_STATUSES)
    def test_exhaustive_transition_matrix(self, start_status: CampaignStatus, target_status: CampaignStatus):
        """
        Exhaustively test all 36 combinations of start -> target.
        Ensure every legal transition is permitted and every illegal transition is rejected.
        """
        is_legal = target_status in LEGAL_TRANSITIONS.get(start_status, set())

        state = CampaignState(
            status=start_status,
            financials=Financials(gross_budget=1000.0, payment_verified=True),
        )

        if is_legal:
            # Legal transition must succeed
            new_state = transition_state(state, target_status)
            assert new_state.status == target_status
        else:
            # Illegal transition must raise InvalidStateTransitionError
            with pytest.raises(InvalidStateTransitionError):
                transition_state(state, target_status)

    @pytest.mark.parametrize("status", ALL_STATUSES)
    def test_self_transitions_strictly_forbidden(self, status: CampaignStatus):
        """Verify that no status can transition to itself (no no-op self-loops)."""
        state = CampaignState(
            status=status,
            financials=Financials(gross_budget=1000.0, payment_verified=True),
        )
        with pytest.raises(InvalidStateTransitionError):
            state.transition_to(status)

    @pytest.mark.parametrize(
        "bogus_target",
        [
            "INVALID_STATUS",
            "DELETED",
            "ARCHIVED",
            "123",
            "",
            "   ",
            "live",  # lowercase string
            "Planning",  # titlecase string
        ],
    )
    def test_bogus_string_target_transition_rejected(self, bogus_target: str):
        """Verify transition_to rejects unrecognized status strings."""
        state = CampaignState(
            status=CampaignStatus.INTAKE,
            financials=Financials(gross_budget=1000.0, payment_verified=True),
        )
        # Attempting to transition to an invalid status string must raise an error
        with pytest.raises((InvalidStateTransitionError, ValueError)):
            state.transition_to(bogus_target)

    def test_can_transition_unhandled_value_error_probe(self):
        """
        Verify that can_transition returns False on invalid status strings without raising exceptions.
        """
        assert can_transition(CampaignStatus.INTAKE, "NON_EXISTENT") is False
        assert can_transition(CampaignStatus.INTAKE, "") is False
        assert can_transition(CampaignStatus.INTAKE, "   ") is False
        assert can_transition(CampaignStatus.INTAKE, "live") is False
        assert can_transition(CampaignStatus.INTAKE, None) is False
        assert can_transition("NON_EXISTENT", CampaignStatus.PLANNING) is False
        assert can_transition(None, None) is False

    def test_atomic_rollback_on_failed_transition(self):
        """Verify that state attributes are completely untouched when a transition is rejected."""
        state = CampaignState(
            status=CampaignStatus.INTAKE,
            financials=Financials(gross_budget=1000.0, payment_verified=False),
        )
        initial_timestamp = state.updated_at
        initial_audit_len = len(state.audit_trail)

        # Illegal jump: INTAKE -> LIVE
        with pytest.raises((InvalidStateTransitionError, PaymentVerificationError)):
            state.transition_to(CampaignStatus.LIVE)

        assert state.status == CampaignStatus.INTAKE
        assert state.updated_at == initial_timestamp
        assert len(state.audit_trail) == initial_audit_len


# ============================================================================
# 3. Deserialization of Corrupted and Maliciously Crafted JSON
# ============================================================================

class TestAdversarialDeserialization:
    """Tests resilience against corrupted, malformed, or malicious JSON inputs."""

    def test_syntax_error_json(self):
        """Verify that malformed JSON strings raise ValidationError."""
        malformed_inputs = [
            '{"status": "INTAKE"',
            '{"status": "INTAKE",}',
            '{status: INTAKE}',
            'not a json',
            "",
            "\x00\x01\x02",
        ]
        for bad_json in malformed_inputs:
            with pytest.raises(ValidationError):
                CampaignState.model_validate_json(bad_json)

    def test_type_mismatches_in_client_brief(self):
        """Verify strict type validation on client brief fields."""
        # Non-numeric budget
        with pytest.raises(ValidationError):
            ClientBrief.model_validate({
                "product": "Crypto Bot",
                "geo": "US",
                "goal": "LEADS",
                "budget": "five hundred dollars",
            })

        # Negative budget
        with pytest.raises(ValidationError):
            ClientBrief.model_validate({
                "product": "Crypto Bot",
                "geo": "US",
                "goal": "LEADS",
                "budget": -100.0,
            })

        # Zero budget
        with pytest.raises(ValidationError):
            ClientBrief.model_validate({
                "product": "Crypto Bot",
                "geo": "US",
                "goal": "LEADS",
                "budget": 0.0,
            })

    def test_massive_payload_injection(self):
        """Verify model handles large payload strings without stack overflow or crash."""
        huge_text = "A" * 100_000
        brief = ClientBrief(
            product="Massive Scale Product",
            geo="GLOBAL",
            goal="TRAFFIC",
            budget=50_000.0,
            product_description=huge_text,
        )
        assert len(brief.product_description) == 100_000

        state = CampaignState(client_brief=brief)
        # Should serialize and deserialize cleanly
        json_dump = state.model_dump_json()
        restored = CampaignState.model_validate_json(json_dump)
        assert restored.client_brief.product_description == huge_text

    def test_financials_cashback_rate_bounds_enforced(self):
        """Verify agency cashback rate outside 3-6% range is strictly rejected."""
        # Lower than 0.03
        with pytest.raises(ValidationError):
            Financials(gross_budget=1000.0, agency_cashback_rate=0.01)

        # Higher than 0.06
        with pytest.raises(ValidationError):
            Financials(gross_budget=1000.0, agency_cashback_rate=0.15)


# ============================================================================
# 4. Rapid Sequential Transitions & Concurrency Stress
# ============================================================================

class TestSequentialTransitionsAndConcurrency:
    """Tests high-frequency sequential transitions and multi-threaded behavior."""

    def test_rapid_cyclical_transitions(self):
        """
        Performs 100 consecutive valid lifecycle state transitions.
        Validates state consistency, monotonically non-decreasing timestamps,
        and accurate audit trail logging.
        """
        state = CampaignState(
            status=CampaignStatus.INTAKE,
            financials=Financials(gross_budget=5000.0, payment_verified=True),
        )

        state.transition_to(CampaignStatus.PLANNING)
        state.transition_to(CampaignStatus.AWAITING_APPROVAL)
        state.transition_to(CampaignStatus.LIVE)

        last_time = state.updated_at

        # Cycle through LIVE -> OPTIMIZING -> PAUSED -> LIVE 50 times (150 transitions)
        for i in range(50):
            # LIVE -> OPTIMIZING
            state.transition_to(CampaignStatus.OPTIMIZING)
            assert state.status == CampaignStatus.OPTIMIZING
            assert state.updated_at >= last_time
            last_time = state.updated_at

            # OPTIMIZING -> PAUSED
            state.transition_to(CampaignStatus.PAUSED)
            assert state.status == CampaignStatus.PAUSED
            assert state.updated_at >= last_time
            last_time = state.updated_at

            # PAUSED -> LIVE
            state.transition_to(CampaignStatus.LIVE)
            assert state.status == CampaignStatus.LIVE
            assert state.updated_at >= last_time
            last_time = state.updated_at

        # Total transitions: 3 initial + 150 loop = 153 transitions
        assert len(state.audit_trail) == 153
        assert state.audit_trail[-1]["details"]["to"] == "LIVE"

    def test_multithreaded_independent_states(self):
        """Verify state machine stability across multiple concurrent threads."""
        errors = []

        def worker(thread_id: int):
            try:
                s = CampaignState(
                    status=CampaignStatus.INTAKE,
                    financials=Financials(gross_budget=1000.0 + thread_id, payment_verified=True),
                )
                s.transition_to(CampaignStatus.PLANNING)
                s.transition_to(CampaignStatus.AWAITING_APPROVAL)
                s.transition_to(CampaignStatus.LIVE)
                s.transition_to(CampaignStatus.OPTIMIZING)
                s.transition_to(CampaignStatus.PAUSED)
                assert s.status == CampaignStatus.PAUSED
            except Exception as e:
                errors.append((thread_id, e))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread errors encountered: {errors}"
