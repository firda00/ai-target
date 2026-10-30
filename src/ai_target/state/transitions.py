"""
State transition engine and payment verification hard gate for CampaignState.

Module: ai_target.state.transitions
Integrity Mode: development
Python Version: 3.12+
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Dict, Optional, Set, Union

from ai_target.state.models import (
    CampaignStateError,
    CampaignStatus,
    InvalidStateTransitionError,
    InvalidTransitionError,
    PaymentNotVerifiedError,
    PaymentVerificationError,
)

if TYPE_CHECKING:
    from ai_target.state.models import CampaignState


# ============================================================================
# 1. Legal Transition Graph & Active Status Sets
# ============================================================================

LEGAL_TRANSITIONS: Dict[CampaignStatus, Set[CampaignStatus]] = {
    CampaignStatus.INTAKE: {
        CampaignStatus.PLANNING,
    },
    CampaignStatus.PLANNING: {
        CampaignStatus.AWAITING_APPROVAL,
    },
    CampaignStatus.AWAITING_APPROVAL: {
        CampaignStatus.LIVE,
    },
    CampaignStatus.LIVE: {
        CampaignStatus.OPTIMIZING,
        CampaignStatus.PAUSED,
    },
    CampaignStatus.OPTIMIZING: {
        CampaignStatus.LIVE,
        CampaignStatus.PAUSED,
    },
    CampaignStatus.PAUSED: {
        CampaignStatus.LIVE,
        CampaignStatus.OPTIMIZING,
    },
}

ACTIVE_STATUSES: Set[CampaignStatus] = {
    CampaignStatus.LIVE,
    CampaignStatus.OPTIMIZING,
}


# ============================================================================
# 2. Transition Validation & Execution Functions
# ============================================================================

def get_allowed_transitions(current_status: Union[CampaignStatus, str]) -> Set[CampaignStatus]:
    """
    Returns the set of valid next CampaignStatus targets from current_status.
    Returns an empty set if current_status is invalid or unrecognized.
    """
    try:
        status = current_status if isinstance(current_status, CampaignStatus) else CampaignStatus(current_status)
    except (ValueError, TypeError):
        return set()
    return LEGAL_TRANSITIONS.get(status, set()).copy()


def can_transition(
    current_status: Union[CampaignStatus, str],
    target_status: Union[CampaignStatus, str],
    state: Optional[CampaignState] = None,
) -> bool:
    """
    Predicate returning True if the transition is legal and satisfies the payment gate.
    Returns False otherwise without raising exceptions.
    """
    try:
        validate_transition(current_status, target_status, state)
        return True
    except (InvalidStateTransitionError, PaymentVerificationError, ValueError, TypeError):
        return False


def validate_transition(
    current_status: Union[CampaignStatus, str],
    target_status: Union[CampaignStatus, str],
    state: Optional[CampaignState] = None,
) -> None:
    """
    Validates state transition permissibility and enforces the payment verification hard gate.

    Args:
        current_status: The starting status.
        target_status: The intended target status.
        state: Optional reference to CampaignState for context-aware payment verification.

    Raises:
        InvalidStateTransitionError: If current_status or target_status is invalid,
                                     or if target_status is not a legal successor of current_status.
        PaymentNotVerifiedError: If target_status is an active status (LIVE, OPTIMIZING)
                                 and state.financials.payment_verified is False.
    """
    # 1. Coerce and validate current_status
    try:
        curr = current_status if isinstance(current_status, CampaignStatus) else CampaignStatus(current_status)
    except (ValueError, TypeError) as err:
        raise InvalidStateTransitionError(
            current_status_or_msg=current_status,
            target_status=target_status,
            message=f"Invalid current status: '{current_status}' is not a valid CampaignStatus member.",
        ) from err

    # 2. Coerce and validate target_status
    try:
        targ = target_status if isinstance(target_status, CampaignStatus) else CampaignStatus(target_status)
    except (ValueError, TypeError) as err:
        raise InvalidStateTransitionError(
            current_status_or_msg=curr,
            target_status=target_status,
            message=f"Invalid target status: '{target_status}' is not a valid CampaignStatus member.",
        ) from err

    # 3. Structural graph transition check
    allowed_targets = LEGAL_TRANSITIONS.get(curr, set())
    if targ not in allowed_targets:
        raise InvalidStateTransitionError(
            current_status_or_msg=curr,
            target_status=targ,
        )

    # 4. Payment verification hard gate check
    if targ in ACTIVE_STATUSES:
        campaign_id = getattr(state, "campaign_id", "UNKNOWN") if state else "UNKNOWN"
        financials = getattr(state, "financials", None)
        payment_verified = getattr(financials, "payment_verified", False) if financials else False
        if not payment_verified:
            raise PaymentNotVerifiedError(
                message_or_campaign_id=campaign_id,
                target_status=targ,
            )


def transition_state(
    state: CampaignState,
    target_status: Union[CampaignStatus, str],
) -> CampaignState:
    """
    Validates and executes a state transition on a CampaignState instance.

    Args:
        state: The CampaignState instance to transition.
        target_status: The target CampaignStatus.

    Returns:
        The mutated CampaignState instance with updated status and updated_at timestamp.

    Raises:
        InvalidStateTransitionError: If current_status or target_status is invalid,
                                     or if the transition path is invalid.
        PaymentNotVerifiedError: If payment is unverified when moving to LIVE or OPTIMIZING.
    """
    # Validate transition permissions and payment gate first
    validate_transition(
        current_status=state.status,
        target_status=target_status,
        state=state,
    )

    targ = target_status if isinstance(target_status, CampaignStatus) else CampaignStatus(target_status)

    # State mutation: update status and timestamp atomically
    old_status = state.status
    state.status = targ
    state.updated_at = datetime.now(timezone.utc)
    if hasattr(state, "record_audit_event"):
        state.record_audit_event(
            agent="SupervisorOrchestrator",
            action="STATUS_TRANSITION",
            details={
                "from": getattr(old_status, "value", str(old_status)),
                "to": getattr(targ, "value", str(targ)),
            },
        )
    return state
