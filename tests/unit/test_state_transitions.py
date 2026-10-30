"""
Unit test suite for state lifecycle transitions and payment verification hard gate.

File: tests/unit/test_state_transitions.py
Target: ai_target.state.transitions
"""

import pytest

from ai_target.state.models import (
    CampaignState,
    CampaignStatus,
    ClientBrief,
    Financials,
)
from ai_target.state.transitions import (
    InvalidStateTransitionError,
    PaymentNotVerifiedError,
    can_transition,
    get_allowed_transitions,
    transition_state,
)


@pytest.fixture
def base_campaign_state():
    """Provides a fresh CampaignState in INTAKE status with unpaid financials."""
    return CampaignState(
        campaign_id="cmp_test_001",
        status=CampaignStatus.INTAKE,
        client_brief=ClientBrief(
            product_name="Test SaaS App",
            target_geo=["US", "KZ"],
            goal="LEADS",
            budget=1000.0,
        ),
        financials=Financials(
            gross_budget=1000.0,
            payment_verified=False,
        ),
    )


# ============================================================================
# Tier 1: Valid Transition Paths & State Progression
# ============================================================================

class TestValidTransitions:
    """Verifies that all 9 legal transitions succeed and update state."""

    def test_intake_to_planning(self, base_campaign_state):
        state = base_campaign_state
        assert state.status == CampaignStatus.INTAKE
        updated = transition_state(state, CampaignStatus.PLANNING)
        assert updated.status == CampaignStatus.PLANNING
        assert state.status == CampaignStatus.PLANNING

    def test_planning_to_awaiting_approval(self, base_campaign_state):
        state = base_campaign_state
        state.status = CampaignStatus.PLANNING
        updated = transition_state(state, CampaignStatus.AWAITING_APPROVAL)
        assert updated.status == CampaignStatus.AWAITING_APPROVAL

    def test_awaiting_approval_to_live_with_payment(self, base_campaign_state):
        state = base_campaign_state
        state.status = CampaignStatus.AWAITING_APPROVAL
        state.financials.payment_verified = True
        updated = transition_state(state, CampaignStatus.LIVE)
        assert updated.status == CampaignStatus.LIVE

    def test_live_to_optimizing(self, base_campaign_state):
        state = base_campaign_state
        state.financials.payment_verified = True
        state.status = CampaignStatus.LIVE
        updated = transition_state(state, CampaignStatus.OPTIMIZING)
        assert updated.status == CampaignStatus.OPTIMIZING

    def test_optimizing_to_live(self, base_campaign_state):
        state = base_campaign_state
        state.financials.payment_verified = True
        state.status = CampaignStatus.OPTIMIZING
        updated = transition_state(state, CampaignStatus.LIVE)
        assert updated.status == CampaignStatus.LIVE

    def test_live_to_paused(self, base_campaign_state):
        state = base_campaign_state
        state.financials.payment_verified = True
        state.status = CampaignStatus.LIVE
        updated = transition_state(state, CampaignStatus.PAUSED)
        assert updated.status == CampaignStatus.PAUSED

    def test_optimizing_to_paused(self, base_campaign_state):
        state = base_campaign_state
        state.financials.payment_verified = True
        state.status = CampaignStatus.OPTIMIZING
        updated = transition_state(state, CampaignStatus.PAUSED)
        assert updated.status == CampaignStatus.PAUSED

    def test_paused_to_live_with_payment(self, base_campaign_state):
        state = base_campaign_state
        state.status = CampaignStatus.PAUSED
        state.financials.payment_verified = True
        updated = transition_state(state, CampaignStatus.LIVE)
        assert updated.status == CampaignStatus.LIVE

    def test_paused_to_optimizing_with_payment(self, base_campaign_state):
        state = base_campaign_state
        state.status = CampaignStatus.PAUSED
        state.financials.payment_verified = True
        updated = transition_state(state, CampaignStatus.OPTIMIZING)
        assert updated.status == CampaignStatus.OPTIMIZING

    def test_full_lifecycle_chain(self, base_campaign_state):
        """Tests the end-to-end forward and recovery lifecycle."""
        state = base_campaign_state
        # INTAKE -> PLANNING
        state = transition_state(state, CampaignStatus.PLANNING)
        # PLANNING -> AWAITING_APPROVAL
        state = transition_state(state, CampaignStatus.AWAITING_APPROVAL)
        # Confirm payment
        state.financials.payment_verified = True
        # AWAITING_APPROVAL -> LIVE
        state = transition_state(state, CampaignStatus.LIVE)
        # LIVE -> OPTIMIZING
        state = transition_state(state, CampaignStatus.OPTIMIZING)
        # OPTIMIZING -> PAUSED (kill-switch triggered)
        state = transition_state(state, CampaignStatus.PAUSED)
        # PAUSED -> OPTIMIZING (re-armed)
        state = transition_state(state, CampaignStatus.OPTIMIZING)
        # OPTIMIZING -> LIVE
        state = transition_state(state, CampaignStatus.LIVE)
        assert state.status == CampaignStatus.LIVE


# ============================================================================
# Tier 2: Blocked Invalid Transitions (27 Disallowed Paths)
# ============================================================================

class TestInvalidTransitions:
    """Parametrized testing of all 27 invalid transition pairings."""

    @pytest.mark.parametrize(
        "from_status, to_status",
        [
            # INTAKE invalid targets (5)
            (CampaignStatus.INTAKE, CampaignStatus.INTAKE),
            (CampaignStatus.INTAKE, CampaignStatus.AWAITING_APPROVAL),
            (CampaignStatus.INTAKE, CampaignStatus.LIVE),
            (CampaignStatus.INTAKE, CampaignStatus.OPTIMIZING),
            (CampaignStatus.INTAKE, CampaignStatus.PAUSED),

            # PLANNING invalid targets (5)
            (CampaignStatus.PLANNING, CampaignStatus.PLANNING),
            (CampaignStatus.PLANNING, CampaignStatus.INTAKE),
            (CampaignStatus.PLANNING, CampaignStatus.LIVE),
            (CampaignStatus.PLANNING, CampaignStatus.OPTIMIZING),
            (CampaignStatus.PLANNING, CampaignStatus.PAUSED),

            # AWAITING_APPROVAL invalid targets (5)
            (CampaignStatus.AWAITING_APPROVAL, CampaignStatus.AWAITING_APPROVAL),
            (CampaignStatus.AWAITING_APPROVAL, CampaignStatus.INTAKE),
            (CampaignStatus.AWAITING_APPROVAL, CampaignStatus.PLANNING),
            (CampaignStatus.AWAITING_APPROVAL, CampaignStatus.OPTIMIZING),
            (CampaignStatus.AWAITING_APPROVAL, CampaignStatus.PAUSED),

            # LIVE invalid targets (4)
            (CampaignStatus.LIVE, CampaignStatus.LIVE),
            (CampaignStatus.LIVE, CampaignStatus.INTAKE),
            (CampaignStatus.LIVE, CampaignStatus.PLANNING),
            (CampaignStatus.LIVE, CampaignStatus.AWAITING_APPROVAL),

            # OPTIMIZING invalid targets (4)
            (CampaignStatus.OPTIMIZING, CampaignStatus.OPTIMIZING),
            (CampaignStatus.OPTIMIZING, CampaignStatus.INTAKE),
            (CampaignStatus.OPTIMIZING, CampaignStatus.PLANNING),
            (CampaignStatus.OPTIMIZING, CampaignStatus.AWAITING_APPROVAL),

            # PAUSED invalid targets (4)
            (CampaignStatus.PAUSED, CampaignStatus.PAUSED),
            (CampaignStatus.PAUSED, CampaignStatus.INTAKE),
            (CampaignStatus.PAUSED, CampaignStatus.PLANNING),
            (CampaignStatus.PAUSED, CampaignStatus.AWAITING_APPROVAL),
        ],
    )
    def test_disallowed_transitions_raise_error(self, base_campaign_state, from_status, to_status):
        state = base_campaign_state
        state.financials.payment_verified = True
        state.status = from_status

        with pytest.raises(InvalidStateTransitionError) as exc_info:
            transition_state(state, to_status)

        assert exc_info.value.current_status == from_status
        assert exc_info.value.target_status == to_status
        assert state.status == from_status  # State must remain unmodified


# ============================================================================
# Tier 3: Payment Verification Hard Gate
# ============================================================================

class TestPaymentVerificationGate:
    """Verifies strict security enforcement of payment clearance."""

    def test_launch_blocked_when_payment_unverified(self, base_campaign_state):
        state = base_campaign_state
        state.status = CampaignStatus.AWAITING_APPROVAL
        state.financials.payment_verified = False

        with pytest.raises(PaymentNotVerifiedError) as exc_info:
            transition_state(state, CampaignStatus.LIVE)

        assert exc_info.value.campaign_id == state.campaign_id
        assert exc_info.value.target_status == CampaignStatus.LIVE
        assert state.status == CampaignStatus.AWAITING_APPROVAL  # Invariant intact

    def test_launch_blocked_when_financials_none(self, base_campaign_state):
        state = base_campaign_state
        state.status = CampaignStatus.AWAITING_APPROVAL
        state.financials = None

        with pytest.raises(PaymentNotVerifiedError):
            transition_state(state, CampaignStatus.LIVE)

        assert state.status == CampaignStatus.AWAITING_APPROVAL

    def test_resume_from_paused_to_live_blocked_if_unpaid(self, base_campaign_state):
        state = base_campaign_state
        state.status = CampaignStatus.PAUSED
        state.financials.payment_verified = False

        with pytest.raises(PaymentNotVerifiedError):
            transition_state(state, CampaignStatus.LIVE)

        assert state.status == CampaignStatus.PAUSED

    def test_resume_from_paused_to_optimizing_blocked_if_unpaid(self, base_campaign_state):
        state = base_campaign_state
        state.status = CampaignStatus.PAUSED
        state.financials.payment_verified = False

        with pytest.raises(PaymentNotVerifiedError):
            transition_state(state, CampaignStatus.OPTIMIZING)

        assert state.status == CampaignStatus.PAUSED

    def test_can_transition_predicate_reflects_payment_status(self, base_campaign_state):
        state = base_campaign_state
        state.status = CampaignStatus.AWAITING_APPROVAL
        state.financials.payment_verified = False

        assert not can_transition(state.status, CampaignStatus.LIVE, state)

        state.financials.payment_verified = True
        assert can_transition(state.status, CampaignStatus.LIVE, state)

    def test_get_allowed_transitions(self):
        intake_allowed = get_allowed_transitions(CampaignStatus.INTAKE)
        assert intake_allowed == {CampaignStatus.PLANNING}

        live_allowed = get_allowed_transitions(CampaignStatus.LIVE)
        assert live_allowed == {CampaignStatus.OPTIMIZING, CampaignStatus.PAUSED}

        paused_allowed = get_allowed_transitions(CampaignStatus.PAUSED)
        assert paused_allowed == {CampaignStatus.LIVE, CampaignStatus.OPTIMIZING}

    def test_atomic_state_preserved_on_payment_failure(self, base_campaign_state):
        state = base_campaign_state
        state.status = CampaignStatus.AWAITING_APPROVAL
        state.financials.payment_verified = False
        initial_timestamp = state.updated_at

        with pytest.raises(PaymentNotVerifiedError):
            transition_state(state, CampaignStatus.LIVE)

        assert state.status == CampaignStatus.AWAITING_APPROVAL
        assert state.updated_at == initial_timestamp
