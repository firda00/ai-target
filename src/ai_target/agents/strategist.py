"""
ai_target.agents.strategist
Strategist & Billing Agent (Milestone 2 - Component 1).

Responsibilities:
1. Calculates service commission (12%) and net media spend (88%).
2. Computes agency cashback estimations (Click.ru 3-5%, eLama 3-6%).
3. Allocates net budget across advertising channels enforcing platform minimum thresholds:
   - Instagram Reels (Meta): >= 10.0 USDT/day
   - Telegram AdsGram: >= 10.0 USDT/day
   - Telegram Adsly.Pro: CPM >= 0.10 TON (default 0.20 TON)
   - Google Ads AI Max: Remainder of net media budget
4. Emits structured, Pydantic-validated MediaPlan conforming to CampaignState.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union

from ai_target.state.models import (
    CampaignState,
    ChannelAllocation,
    Financials,
    MediaPlan,
    PlatformEnum,
)


# ==============================================================================
# Domain Constants & Configuration
# ==============================================================================

SERVICE_COMMISSION_RATE: float = 0.12  # 12% agency service commission

CLICKRU_DEFAULT_CASHBACK_RATE: float = 0.05  # 5% default Click.ru cashback
CLICKRU_MIN_CASHBACK_RATE: float = 0.03
CLICKRU_MAX_CASHBACK_RATE: float = 0.05

ELAMA_DEFAULT_CASHBACK_RATE: float = 0.04  # 4% default eLama cashback
ELAMA_MIN_CASHBACK_RATE: float = 0.03
ELAMA_MAX_CASHBACK_RATE: float = 0.06

META_MIN_DAILY_BUDGET_USDT: float = 10.00  # Hard floor for Instagram Reels / Meta
ADSGRAM_MIN_DAILY_BUDGET_USDT: float = 10.00  # Hard floor for Telegram AdsGram
ADSLY_MIN_CPM_TON: float = 0.10  # Hard floor for Adsly.Pro starting bid
ADSLY_DEFAULT_CPM_TON: float = 0.20  # Recommended initial CPM in TON
DEFAULT_TON_USDT_RATE: float = 5.00  # Baseline conversion reference: 1 TON = 5.0 USDT

DEFAULT_FLIGHT_DURATION_DAYS: int = 14  # Default flight length in days


class InsufficientBudgetError(ValueError):
    """Raised when net media budget is insufficient to satisfy platform entry minimums."""
    pass


class StrategistBillingAgent:
    """
    Strategist & Billing Agent responsible for agency financial computations,
    cashback modeling, and platform minimum threshold-guarded media planning.
    """

    def __init__(
        self,
        service_commission_rate: float = SERVICE_COMMISSION_RATE,
        default_billing_partner: str = "click_ru",
    ) -> None:
        self.service_commission_rate = service_commission_rate
        self.default_billing_partner = default_billing_partner

    def calculate_financials(
        self,
        gross_budget: float,
        billing_partner: str = "click_ru",
        currency: str = "USDT",
    ) -> Financials:
        """
        Calculates agency service commission (12%) and net media budget (88%),
        and initializes partner cashback projections.

        Args:
            gross_budget: Total client funding in USDT/USD (must be > 0).
            billing_partner: Billing aggregator ("click_ru", "elama", or "direct").
            currency: Currency code (default "USDT").

        Returns:
            Financials: Pydantic model populated with commission and net media budget.

        Raises:
            ValueError: If gross_budget <= 0.
        """
        if gross_budget <= 0:
            raise ValueError(f"gross_budget must be strictly positive, got {gross_budget}")

        partner = billing_partner or self.default_billing_partner

        return Financials(
            gross_budget=float(gross_budget),
            currency=currency,
            service_commission_rate=self.service_commission_rate,
            billing_partner=partner,
        )

    def estimate_cashback(
        self,
        net_spend: float,
        partner: str = "click_ru",
    ) -> Tuple[float, float]:
        """
        Estimates partner agency cashback based on net advertising spend.

        Tier ranges:
        - Click.ru: 3% to 5% (default: 5% / 0.05)
        - eLama: 3% to 6% (default: 4% / 0.04)

        Args:
            net_spend: Net advertising expenditure after service commission.
            partner: Billing partner name ('click_ru' or 'elama').

        Returns:
            Tuple[float, float]: (cashback_amount, cashback_rate)
        """
        if net_spend < 0:
            raise ValueError(f"net_spend cannot be negative, got {net_spend}")

        partner_norm = (partner or self.default_billing_partner).lower()

        if "elama" in partner_norm:
            cashback_rate = ELAMA_DEFAULT_CASHBACK_RATE
        else:
            cashback_rate = CLICKRU_DEFAULT_CASHBACK_RATE

        cashback_amount = round(net_spend * cashback_rate, 2)
        return cashback_amount, cashback_rate

    def allocate_budget(
        self,
        state: CampaignState,
        duration_days: int = DEFAULT_FLIGHT_DURATION_DAYS,
    ) -> MediaPlan:
        """
        Allocates net media budget across advertising platforms subject to hard minimum floors:
        - Instagram Reels (Meta): >= 10.0 USDT/day
        - Telegram AdsGram: >= 10.0 USDT/day
        - Telegram Adsly.Pro: CPM >= 0.10 TON
        - Google Ads AI Max: Remainder of net media budget

        Args:
            state: Central CampaignState containing client_brief and/or financials.
            duration_days: Campaign flight pacing duration in days (default: 14).

        Returns:
            MediaPlan: Validated media plan with allocations.

        Raises:
            ValueError: If budget is missing or insufficient to meet platform floors.
        """
        # 1. Resolve net media budget from state
        net_budget = 0.0
        if state.financials and state.financials.net_media_budget > 0:
            net_budget = state.financials.net_media_budget
        elif state.financials and state.financials.gross_budget > 0:
            fin = self.calculate_financials(state.financials.gross_budget)
            state.financials = fin
            net_budget = fin.net_media_budget
        elif state.client_brief and state.client_brief.budget > 0:
            fin = self.calculate_financials(state.client_brief.budget)
            state.financials = fin
            net_budget = fin.net_media_budget
        else:
            raise ValueError("CampaignState must contain positive financials or client_brief budget.")

        # 2. Resolve duration
        flight_days = duration_days if duration_days and duration_days > 0 else DEFAULT_FLIGHT_DURATION_DAYS

        # 3. Calculate minimum threshold requirements
        min_meta_total = round(META_MIN_DAILY_BUDGET_USDT * flight_days, 2)
        min_adsgram_total = round(ADSGRAM_MIN_DAILY_BUDGET_USDT * flight_days, 2)
        min_adsly_total = 10.00  # Baseline floor for Adsly.Pro TON allocation
        min_required = round(min_meta_total + min_adsgram_total + min_adsly_total, 2)

        if net_budget < min_required:
            raise InsufficientBudgetError(
                f"Net media budget {net_budget} USDT is insufficient to satisfy platform minimum thresholds "
                f"for flight of {flight_days} days. Minimum required is {min_required} USDT "
                f"(Meta: {min_meta_total}, AdsGram: {min_adsgram_total}, Adsly: {min_adsly_total})."
            )

        # 4. Proportional Target Partitioning
        # Standard weights: Meta 35%, AdsGram 25%, Adsly 20%, Google Ads remainder (~20%)
        target_meta = round(net_budget * 0.35, 2)
        target_adsgram = round(net_budget * 0.25, 2)
        target_adsly = round(net_budget * 0.20, 2)

        # Clamping to platform minimums
        meta_budget = max(target_meta, min_meta_total)
        adsgram_budget = max(target_adsgram, min_adsgram_total)
        adsly_budget = max(target_adsly, min_adsly_total)

        # 5. Check if floor clamping exceeded net budget; if so, rebalance towards exact floors
        allocated_subtotal = round(meta_budget + adsgram_budget + adsly_budget, 2)
        if allocated_subtotal > net_budget:
            meta_budget = min_meta_total
            adsgram_budget = min_adsgram_total
            adsly_budget = round(net_budget - meta_budget - adsgram_budget, 2)
            if adsly_budget < min_adsly_total:
                adsly_budget = min_adsly_total
            allocated_subtotal = round(meta_budget + adsgram_budget + adsly_budget, 2)

        # 6. Google Ads AI Max takes the remainder
        google_budget = round(net_budget - allocated_subtotal, 2)
        if google_budget < 0:
            # Rebalance cent discrepancy
            excess = abs(google_budget)
            adsly_budget = round(adsly_budget - excess, 2)
            google_budget = 0.0

        # 7. Compute Daily Budgets
        meta_daily = max(META_MIN_DAILY_BUDGET_USDT, round(meta_budget / flight_days, 2))
        adsgram_daily = max(ADSGRAM_MIN_DAILY_BUDGET_USDT, round(adsgram_budget / flight_days, 2))
        adsly_daily = max(0.01, round(adsly_budget / flight_days, 2))
        google_daily = max(0.01, round(google_budget / flight_days, 2)) if google_budget > 0 else 0.0

        # 8. Construct Channel Allocations
        allocations: List[ChannelAllocation] = []

        # Platform 1: Meta Instagram Reels
        allocations.append(
            ChannelAllocation(
                platform=PlatformEnum.META_INSTAGRAM,
                allocated_budget=meta_budget,
                daily_budget=meta_daily,
                notes="Instagram Reels & Stories video campaign",
            )
        )

        # Platform 2: Telegram AdsGram
        allocations.append(
            ChannelAllocation(
                platform=PlatformEnum.TELEGRAM_ADSGRAM,
                allocated_budget=adsgram_budget,
                daily_budget=adsgram_daily,
                notes="Telegram Mini Apps rewarded video format",
            )
        )

        # Platform 3: Telegram Adsly.Pro
        allocations.append(
            ChannelAllocation(
                platform=PlatformEnum.TELEGRAM_ADSLY,
                allocated_budget=adsly_budget,
                daily_budget=adsly_daily,
                cpm_estimate=ADSLY_DEFAULT_CPM_TON,  # 0.20 TON (>= 0.10 TON floor)
                notes="Telegram channel seed postings via Adsly.Pro (bidding in TON)",
            )
        )

        # Platform 4: Google Ads AI Max (Remainder)
        if google_budget > 0:
            allocations.append(
                ChannelAllocation(
                    platform=PlatformEnum.GOOGLE_ADS,
                    allocated_budget=google_budget,
                    daily_budget=google_daily,
                    notes="Google Ads AI Max multi-channel remainder allocation",
                )
            )

        # 9. Build MediaPlan
        media_plan = MediaPlan(allocations=allocations)

        # Double check invariant: total_allocated <= net_budget
        if media_plan.total_allocated > net_budget:
            # Surgical cent trim from Google or Adsly
            diff = round(media_plan.total_allocated - net_budget, 2)
            if google_budget > diff:
                allocations[-1].allocated_budget = round(allocations[-1].allocated_budget - diff, 2)
            else:
                allocations[2].allocated_budget = round(allocations[2].allocated_budget - diff, 2)
            media_plan = MediaPlan(allocations=allocations)

        # Record audit trail entry
        state.record_audit_event(
            agent="StrategistBillingAgent",
            action="ALLOCATE_BUDGET",
            details={
                "net_media_budget": net_budget,
                "flight_duration_days": flight_days,
                "total_allocated": media_plan.total_allocated,
                "channels_count": len(allocations),
                "platform_thresholds_passed": media_plan.platform_threshold_checks_passed,
            },
        )

        return media_plan
