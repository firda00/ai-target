"""
Adversarial Stress Test Suite for StrategistBillingAgent (Milestone 2).
File: tests/unit/test_adversarial_strategist_billing.py

Empirical verification harness authored by Challenger Subagent (challenger_m2_1).
Zero external network access enforced via socket blocking fixture.

Coverage:
1. Micro & Boundary Budgets Precision Stress Test (0.01, 1.00, 9.99, 10.00, 10.01, 999.99, 1,000,000.00)
2. Exact Cent Matching Invariant:
   - service_commission + net_media_budget == gross_budget (0 cent drift)
   - total_allocated <= net_media_budget without negative drift
3. Partner Cashback Boundary Stress Test (Click.ru 3-5%, eLama 3-6%, casing, boundary spends)
4. Platform Floor Enforcement (Reels >= 10.0 USDT/day, AdsGram >= 10.0 USDT/day, Adsly >= 0.10 TON)
5. Insufficient Budget Scenarios & Flight Pacing (raising InsufficientBudgetError)
6. Error Handling & Malformed State/Input Stress Test
"""

import math
import random
import unittest
from typing import List

from pydantic import ValidationError

from tests.conftest import enable_socket_blocking

enable_socket_blocking()

from ai_target.agents.strategist import (
    ADSGRAM_MIN_DAILY_BUDGET_USDT,
    ADSLY_DEFAULT_CPM_TON,
    ADSLY_MIN_CPM_TON,
    CLICKRU_DEFAULT_CASHBACK_RATE,
    CLICKRU_MAX_CASHBACK_RATE,
    CLICKRU_MIN_CASHBACK_RATE,
    DEFAULT_FLIGHT_DURATION_DAYS,
    ELAMA_DEFAULT_CASHBACK_RATE,
    ELAMA_MAX_CASHBACK_RATE,
    ELAMA_MIN_CASHBACK_RATE,
    META_MIN_DAILY_BUDGET_USDT,
    SERVICE_COMMISSION_RATE,
    InsufficientBudgetError,
    StrategistBillingAgent,
)
from ai_target.state.models import (
    CampaignState,
    CampaignStatus,
    ChannelAllocation,
    ClientBrief,
    Financials,
    MediaPlan,
    PlatformEnum,
)


class TestAdversarialMicroAndBoundaryBudgets(unittest.TestCase):
    """Stress-tests commission calculations across micro and boundary budget inputs."""

    def setUp(self):
        enable_socket_blocking()
        self.agent = StrategistBillingAgent()

    def test_mandatory_boundary_budgets_exact_cent_matching(self):
        """Verifies exact cent matching for the required boundary values:
        0.01, 1.00, 9.99, 10.00, 10.01, 999.99, 1,000,000.00 USDT.
        """
        targets = [0.01, 1.00, 9.99, 10.00, 10.01, 999.99, 1_000_000.00]
        for b in targets:
            fin = self.agent.calculate_financials(b)
            self.assertEqual(fin.gross_budget, b)
            self.assertGreaterEqual(fin.service_commission, 0.0)
            self.assertGreaterEqual(fin.net_media_budget, 0.0)
            cent_sum = round(fin.service_commission + fin.net_media_budget, 2)
            self.assertEqual(
                cent_sum,
                round(b, 2),
                f"Cent drift for budget {b}: comm={fin.service_commission}, net={fin.net_media_budget}, sum={cent_sum}",
            )

    def test_micro_budgets_sub_cent_commission_rounding(self):
        """Budgets under $0.05 yield $0.00 commission and allocate full gross to net."""
        # 0.01 * 0.12 = 0.0012 -> 0.00
        fin_001 = self.agent.calculate_financials(0.01)
        self.assertEqual(fin_001.service_commission, 0.00)
        self.assertEqual(fin_001.net_media_budget, 0.01)

        # 0.04 * 0.12 = 0.0048 -> 0.00
        fin_004 = self.agent.calculate_financials(0.04)
        self.assertEqual(fin_004.service_commission, 0.00)
        self.assertEqual(fin_004.net_media_budget, 0.04)

        # 0.05 * 0.12 = 0.006 -> 0.01 commission, 0.04 net
        fin_005 = self.agent.calculate_financials(0.05)
        self.assertEqual(fin_005.service_commission, 0.01)
        self.assertEqual(fin_005.net_media_budget, 0.04)
        self.assertEqual(round(fin_005.service_commission + fin_005.net_media_budget, 2), 0.05)

    def test_dense_cent_sweep_low_range_zero_drift(self):
        """Dense cent sweep [0.01 .. 1.00] with 100 discrete values maintains 0 cent drift."""
        for cent in range(1, 101):
            gross = round(cent / 100.0, 2)
            fin = self.agent.calculate_financials(gross)
            cent_sum = round(fin.service_commission + fin.net_media_budget, 2)
            self.assertEqual(cent_sum, gross, f"Cent drift at low gross={gross}")

    def test_dense_cent_sweep_mid_range_zero_drift(self):
        """Dense cent sweep [9.00 .. 11.00] with 201 discrete values maintains 0 cent drift."""
        for cent in range(900, 1101):
            gross = round(cent / 100.0, 2)
            fin = self.agent.calculate_financials(gross)
            cent_sum = round(fin.service_commission + fin.net_media_budget, 2)
            self.assertEqual(cent_sum, gross, f"Cent drift at mid gross={gross}")

    def test_dense_cent_sweep_high_boundary_zero_drift(self):
        """Dense cent sweep [998.00 .. 1002.00] with 401 values maintains 0 cent drift."""
        for cent in range(99800, 100201):
            gross = round(cent / 100.0, 2)
            fin = self.agent.calculate_financials(gross)
            cent_sum = round(fin.service_commission + fin.net_media_budget, 2)
            self.assertEqual(cent_sum, gross, f"Cent drift at high gross={gross}")

    def test_stochastic_large_budget_sweep_zero_drift(self):
        """10,000 random budgets between 0.01 and 10,000,000.00 USDT all preserve exact sum."""
        random.seed(987654)
        for _ in range(10_000):
            gross = round(random.uniform(0.01, 10_000_000.00), 2)
            fin = self.agent.calculate_financials(gross)
            cent_sum = round(fin.service_commission + fin.net_media_budget, 2)
            self.assertEqual(
                cent_sum,
                gross,
                f"Stochastic cent drift at gross={gross}: comm={fin.service_commission}, net={fin.net_media_budget}",
            )


class TestAdversarialMediaPlanInvariants(unittest.TestCase):
    """Stress-tests the MediaPlan allocation invariant:
    total_allocated <= net_media_budget without negative drift.
    """

    def setUp(self):
        enable_socket_blocking()
        self.agent = StrategistBillingAgent()

    def test_bare_minimum_floor_14_days_exact_boundary(self):
        """Exact minimum budget 290.00 USDT net for 14 days allocates exactly 290.00."""
        state = CampaignState(
            campaign_id="cmp_adv_min_floor_14",
            status=CampaignStatus.PLANNING,
            financials=Financials(gross_budget=1000.0, net_media_budget=290.00),
        )
        plan = self.agent.allocate_budget(state, duration_days=14)
        self.assertEqual(plan.total_allocated, 290.00)
        self.assertLessEqual(plan.total_allocated, 290.00)

        # Confirm allocations: Meta=140, AdsGram=140, Adsly=10, Google=0 (not in list)
        meta = plan.get_allocation_for_platform(PlatformEnum.META_INSTAGRAM)
        adsgram = plan.get_allocation_for_platform(PlatformEnum.TELEGRAM_ADSGRAM)
        adsly = plan.get_allocation_for_platform(PlatformEnum.TELEGRAM_ADSLY)
        google = plan.get_allocation_for_platform(PlatformEnum.GOOGLE_ADS)

        self.assertIsNotNone(meta)
        self.assertIsNotNone(adsgram)
        self.assertIsNotNone(adsly)
        self.assertIsNone(google)

        self.assertEqual(meta.allocated_budget, 140.00)
        self.assertEqual(adsgram.allocated_budget, 140.00)
        self.assertEqual(adsly.allocated_budget, 10.00)
        self.assertEqual(meta.daily_budget, 10.00)
        self.assertEqual(adsgram.daily_budget, 10.00)

    def test_bare_minimum_floor_plus_one_cent(self):
        """Net budget 290.01 USDT for 14 days allocates without over-budget or negative drift."""
        state = CampaignState(
            campaign_id="cmp_adv_floor_plus_cent",
            status=CampaignStatus.PLANNING,
            financials=Financials(gross_budget=1000.0, net_media_budget=290.01),
        )
        plan = self.agent.allocate_budget(state, duration_days=14)
        self.assertLessEqual(plan.total_allocated, 290.01)
        drift = round(290.01 - plan.total_allocated, 2)
        self.assertGreaterEqual(drift, 0.0)
        self.assertEqual(plan.total_allocated, 290.01)

    def test_stochastic_budget_allocation_zero_overspend(self):
        """3,000 random allocations across varied flight durations (1 to 90 days)
        verify total_allocated <= net_media_budget and 0 negative drift.
        """
        random.seed(112233)
        flight_durations = [1, 3, 7, 10, 14, 21, 30, 45, 60, 90]

        for i in range(3000):
            dur = random.choice(flight_durations)
            min_required = round(10.0 * dur + 10.0 * dur + 10.0, 2)
            net_budget = round(random.uniform(min_required, min_required + 25_000.0), 2)

            state = CampaignState(
                campaign_id=f"cmp_stoch_plan_{i}",
                status=CampaignStatus.PLANNING,
                financials=Financials(
                    gross_budget=round(net_budget * 1.5, 2),
                    net_media_budget=net_budget,
                ),
            )
            plan = self.agent.allocate_budget(state, duration_days=dur)

            # Invariant 1: total_allocated <= net_media_budget
            self.assertLessEqual(
                plan.total_allocated,
                net_budget,
                f"Over-allocation at net={net_budget}, dur={dur}: allocated={plan.total_allocated}",
            )

            # Invariant 2: No negative drift (unallocated budget >= 0)
            unallocated = round(net_budget - plan.total_allocated, 2)
            self.assertGreaterEqual(unallocated, 0.0)

            # Invariant 3: Exact allocation matches sum of item allocated budgets
            item_sum = round(sum(a.allocated_budget for a in plan.allocations), 2)
            self.assertEqual(plan.total_allocated, item_sum)

            # Invariant 4: Individual allocations are all positive
            for a in plan.allocations:
                self.assertGreater(a.allocated_budget, 0.0)
                self.assertGreater(a.daily_budget, 0.0)

    def test_extreme_enterprise_budget_allocation_precision(self):
        """Enterprise budget $10,000,000.00 allocates across all 4 channels with exact cent matching."""
        gross = 10_000_000.00
        fin = self.agent.calculate_financials(gross)
        state = CampaignState(
            campaign_id="cmp_enterprise_10m",
            status=CampaignStatus.PLANNING,
            financials=fin,
        )
        plan = self.agent.allocate_budget(state, duration_days=30)
        self.assertEqual(plan.total_allocated, fin.net_media_budget)
        self.assertEqual(len(plan.allocations), 4)


class TestAdversarialPartnerCashback(unittest.TestCase):
    """Stress-tests partner cashback calculations and boundaries:
    - Click.ru: range 3–5%, default 5%
    - eLama: range 3–6%, default 4%
    """

    def setUp(self):
        enable_socket_blocking()
        self.agent = StrategistBillingAgent()

    def test_clickru_boundary_spends(self):
        """Click.ru cashback computations across boundary spend levels."""
        spends = [0.00, 0.01, 1.00, 10.00, 88.00, 100.00, 123.45, 880.00, 999.99, 1_000_000.00]
        for s in spends:
            cb_amount, cb_rate = self.agent.estimate_cashback(s, partner="click_ru")
            self.assertEqual(cb_rate, 0.05)
            expected_amt = round(s * 0.05, 2)
            self.assertEqual(cb_amount, expected_amt)

    def test_elama_boundary_spends(self):
        """eLama cashback computations across boundary spend levels."""
        spends = [0.00, 0.01, 1.00, 10.00, 88.00, 100.00, 123.45, 880.00, 999.99, 1_000_000.00]
        for s in spends:
            cb_amount, cb_rate = self.agent.estimate_cashback(s, partner="elama")
            self.assertEqual(cb_rate, 0.04)
            expected_amt = round(s * 0.04, 2)
            self.assertEqual(cb_amount, expected_amt)

    def test_partner_name_adversarial_casing_and_punctuation(self):
        """Partner normalization handles varied case formats and punctuation."""
        variants_clickru = ["click_ru", "CLICK_RU", "Click_RU", "click.ru", "Click.ru", "CLICK.RU"]
        for p in variants_clickru:
            amount, rate = self.agent.estimate_cashback(1000.0, partner=p)
            self.assertEqual(rate, 0.05, f"Failed for partner string {p}")
            self.assertEqual(amount, 50.00)

        variants_elama = ["elama", "ELAMA", "eLama", "Elama"]
        for p in variants_elama:
            amount, rate = self.agent.estimate_cashback(1000.0, partner=p)
            self.assertEqual(rate, 0.04, f"Failed for partner string {p}")
            self.assertEqual(amount, 40.00)

        # Punctuated or unknown strings ("E-LAMA", "e_lama", "direct", "unknown") fall back to default click_ru rate
        punctuated_or_unknown = ["E-LAMA", "e_lama", "direct", "unknown_broker"]
        for p in punctuated_or_unknown:
            amount, rate = self.agent.estimate_cashback(1000.0, partner=p)
            self.assertEqual(rate, 0.05, f"Expected fallback to default 0.05 for {p}")
            self.assertEqual(amount, 50.00)

    def test_partner_cashback_rate_bounds_enforced_by_pydantic(self):
        """Financials model enforces cashback rates strictly within bounded ranges:
        - clickru_cashback_rate: [0.03, 0.06]
        - elama_cashback_rate: [0.03, 0.06]
        """
        # Valid bounds
        f1 = Financials(gross_budget=1000.0, clickru_cashback_rate=0.03)
        self.assertEqual(f1.clickru_cashback_rate, 0.03)

        f2 = Financials(gross_budget=1000.0, clickru_cashback_rate=0.05)
        self.assertEqual(f2.clickru_cashback_rate, 0.05)

        f3 = Financials(gross_budget=1000.0, elama_cashback_rate=0.03)
        self.assertEqual(f3.elama_cashback_rate, 0.03)

        f4 = Financials(gross_budget=1000.0, elama_cashback_rate=0.06)
        self.assertEqual(f4.elama_cashback_rate, 0.06)

        # Sub-minimum (< 0.03) raises ValidationError
        with self.assertRaises(ValidationError):
            Financials(gross_budget=1000.0, clickru_cashback_rate=0.02)

        with self.assertRaises(ValidationError):
            Financials(gross_budget=1000.0, elama_cashback_rate=0.02)

        # Above maximum (> 0.06) raises ValidationError
        with self.assertRaises(ValidationError):
            Financials(gross_budget=1000.0, clickru_cashback_rate=0.07)

        with self.assertRaises(ValidationError):
            Financials(gross_budget=1000.0, elama_cashback_rate=0.07)


class TestAdversarialPlatformFloorEnforcement(unittest.TestCase):
    """Stress-tests hard minimum platform floor enforcement:
    - Instagram Reels: daily_budget >= 10.00 USDT/day
    - AdsGram: daily_budget >= 10.00 USDT/day
    - Adsly.Pro: CPM >= 0.10 TON
    """

    def setUp(self):
        enable_socket_blocking()
        self.agent = StrategistBillingAgent()

    def test_reels_sub_floor_daily_budget_raises_value_error(self):
        """ChannelAllocation rejects daily_budget < 10.00 USDT for Instagram Reels."""
        with self.assertRaises(ValueError):
            ChannelAllocation(
                platform=PlatformEnum.META_INSTAGRAM,
                allocated_budget=100.0,
                daily_budget=9.99,
            )

    def test_adsgram_sub_floor_daily_budget_raises_value_error(self):
        """ChannelAllocation rejects daily_budget < 10.00 USDT for Telegram AdsGram."""
        with self.assertRaises(ValueError):
            ChannelAllocation(
                platform=PlatformEnum.TELEGRAM_ADSGRAM,
                allocated_budget=100.0,
                daily_budget=9.99,
            )

    def test_adsly_sub_floor_cpm_raises_value_error(self):
        """ChannelAllocation rejects cpm_estimate < 0.10 TON for Adsly.Pro."""
        with self.assertRaises(ValueError):
            ChannelAllocation(
                platform=PlatformEnum.TELEGRAM_ADSLY,
                allocated_budget=50.0,
                daily_budget=3.57,
                cpm_estimate=0.099,
            )

    def test_adsly_exact_floor_cpm_succeeds(self):
        """ChannelAllocation accepts exact floor CPM = 0.10 TON for Adsly.Pro."""
        alloc = ChannelAllocation(
            platform=PlatformEnum.TELEGRAM_ADSLY,
            allocated_budget=50.0,
            daily_budget=3.57,
            cpm_estimate=0.10,
        )
        self.assertEqual(alloc.cpm_estimate, 0.10)

    def test_allocate_budget_always_satisfies_reels_and_adsgram_floors(self):
        """allocate_budget output always adheres to daily >= 10.0 USDT and CPM >= 0.10 TON."""
        durations = [1, 7, 14, 30]
        for dur in durations:
            gross = 5000.0
            state = CampaignState(
                campaign_id=f"cmp_floor_verify_{dur}",
                status=CampaignStatus.PLANNING,
                financials=self.agent.calculate_financials(gross),
            )
            plan = self.agent.allocate_budget(state, duration_days=dur)

            meta = plan.get_allocation_for_platform(PlatformEnum.META_INSTAGRAM)
            adsgram = plan.get_allocation_for_platform(PlatformEnum.TELEGRAM_ADSGRAM)
            adsly = plan.get_allocation_for_platform(PlatformEnum.TELEGRAM_ADSLY)

            self.assertGreaterEqual(meta.daily_budget, 10.00)
            self.assertGreaterEqual(adsgram.daily_budget, 10.00)
            self.assertGreaterEqual(adsly.cpm_estimate, 0.10)
            self.assertGreaterEqual(meta.allocated_budget, 10.00 * dur)
            self.assertGreaterEqual(adsgram.allocated_budget, 10.00 * dur)


class TestAdversarialInsufficientBudgetScenarios(unittest.TestCase):
    """Stress-tests insufficient budget scenarios across varied flight pacing,
    verifying InsufficientBudgetError is consistently raised.
    """

    def setUp(self):
        enable_socket_blocking()
        self.agent = StrategistBillingAgent()

    def test_insufficient_budget_error_is_value_error_subclass(self):
        """Confirms InsufficientBudgetError inherits from ValueError."""
        self.assertTrue(issubclass(InsufficientBudgetError, ValueError))

    def test_14_day_flight_under_minimum_raises_error(self):
        """For 14-day flight (min floor = $290.00), budgets < 290.00 raise InsufficientBudgetError."""
        sub_budgets = [0.01, 10.00, 100.00, 200.00, 289.00, 289.99]
        for net in sub_budgets:
            state = CampaignState(
                campaign_id=f"cmp_under_14_{net}",
                status=CampaignStatus.PLANNING,
                financials=Financials(gross_budget=1000.0, net_media_budget=net),
            )
            with self.assertRaises(InsufficientBudgetError):
                self.agent.allocate_budget(state, duration_days=14)

    def test_30_day_flight_boundary_enforcement(self):
        """For 30-day flight (min floor: 300 Meta + 300 AdsGram + 10 Adsly = 610.00 USDT):
        - 609.99 raises InsufficientBudgetError
        - 610.00 succeeds
        """
        # 609.99 fails
        state_fail = CampaignState(
            campaign_id="cmp_under_30d",
            status=CampaignStatus.PLANNING,
            financials=Financials(gross_budget=1000.0, net_media_budget=609.99),
        )
        with self.assertRaises(InsufficientBudgetError):
            self.agent.allocate_budget(state_fail, duration_days=30)

        # 610.00 succeeds
        state_pass = CampaignState(
            campaign_id="cmp_exact_30d",
            status=CampaignStatus.PLANNING,
            financials=Financials(gross_budget=1000.0, net_media_budget=610.00),
        )
        plan = self.agent.allocate_budget(state_pass, duration_days=30)
        self.assertEqual(plan.total_allocated, 610.00)

    def test_1_day_flight_boundary_enforcement(self):
        """For 1-day flight (min floor: 10 Meta + 10 AdsGram + 10 Adsly = 30.00 USDT):
        - 29.99 raises InsufficientBudgetError
        - 30.00 succeeds
        """
        state_fail = CampaignState(
            campaign_id="cmp_under_1d",
            status=CampaignStatus.PLANNING,
            financials=Financials(gross_budget=100.0, net_media_budget=29.99),
        )
        with self.assertRaises(InsufficientBudgetError):
            self.agent.allocate_budget(state_fail, duration_days=1)

        state_pass = CampaignState(
            campaign_id="cmp_exact_1d",
            status=CampaignStatus.PLANNING,
            financials=Financials(gross_budget=100.0, net_media_budget=30.00),
        )
        plan = self.agent.allocate_budget(state_pass, duration_days=1)
        self.assertEqual(plan.total_allocated, 30.00)


class TestAdversarialErrorHandlingAndMalformedInputs(unittest.TestCase):
    """Stress-tests agent robustness against malformed, non-positive, or illegal state objects."""

    def setUp(self):
        enable_socket_blocking()
        self.agent = StrategistBillingAgent()

    def test_negative_gross_budget_raises_value_error(self):
        """Negative gross budget inputs raise ValueError."""
        for b in [-0.01, -1.0, -100.0, -1_000_000.0]:
            with self.assertRaises(ValueError):
                self.agent.calculate_financials(b)

    def test_zero_gross_budget_raises_value_error(self):
        """Zero gross budget inputs raise ValueError."""
        for b in [0, 0.0, 0.00]:
            with self.assertRaises(ValueError):
                self.agent.calculate_financials(b)

    def test_nan_gross_budget_raises_validation_error(self):
        """float('nan') gross budget is rejected by validation."""
        with self.assertRaises(Exception):
            self.agent.calculate_financials(float("nan"))

    def test_negative_cashback_spend_raises_value_error(self):
        """estimate_cashback with negative net spend raises ValueError."""
        with self.assertRaises(ValueError):
            self.agent.estimate_cashback(-1.0, partner="click_ru")

    def test_empty_campaign_state_raises_value_error(self):
        """CampaignState with no financials and no client brief raises ValueError."""
        state = CampaignState(campaign_id="cmp_empty_state", status=CampaignStatus.PLANNING)
        with self.assertRaises(ValueError):
            self.agent.allocate_budget(state)

    def test_state_budget_source_resolution_precedence(self):
        """Tests budget resolution precedence in allocate_budget:
        1. state.financials.net_media_budget
        2. state.financials.gross_budget
        3. state.client_brief.budget
        """
        # Case 1: Pre-computed net_media_budget takes precedence
        state1 = CampaignState(
            campaign_id="cmp_prec_1",
            status=CampaignStatus.PLANNING,
            financials=Financials(gross_budget=2000.0, net_media_budget=1500.0),
        )
        plan1 = self.agent.allocate_budget(state1, duration_days=14)
        self.assertEqual(plan1.total_allocated, 1500.0)

        # Case 2: Financials with gross_budget but net_media_budget=0 computes financials
        fin2 = Financials(gross_budget=1000.0)
        object.__setattr__(fin2, "net_media_budget", 0.0)
        state2 = CampaignState(
            campaign_id="cmp_prec_2",
            status=CampaignStatus.PLANNING,
            financials=fin2,
        )
        plan2 = self.agent.allocate_budget(state2, duration_days=14)
        self.assertEqual(plan2.total_allocated, 880.00)

        # Case 3: Brief-only state initializes financials and allocates
        state3 = CampaignState(
            campaign_id="cmp_prec_3",
            status=CampaignStatus.PLANNING,
            client_brief=ClientBrief(product="CRM", geo="US", goal="SALES", budget=1200.0),
        )
        plan3 = self.agent.allocate_budget(state3, duration_days=14)
        self.assertIsNotNone(state3.financials)
        self.assertEqual(plan3.total_allocated, 1056.00)  # 1200 * 0.88

    def test_non_campaign_state_objects_rejected(self):
        """Non-CampaignState objects passed to allocate_budget raise AttributeError or TypeError."""
        for invalid_obj in [None, {}, "string_state", 12345]:
            with self.assertRaises((AttributeError, TypeError, ValueError)):
                self.agent.allocate_budget(invalid_obj)

    def test_duration_days_non_positive_fallback(self):
        """duration_days <= 0 or None gracefully defaults to DEFAULT_FLIGHT_DURATION_DAYS (14)."""
        state = CampaignState(
            campaign_id="cmp_fallback_dur",
            status=CampaignStatus.PLANNING,
            financials=Financials(gross_budget=1500.0),
        )
        plan_none = self.agent.allocate_budget(state, duration_days=None)
        plan_zero = self.agent.allocate_budget(state, duration_days=0)
        plan_neg = self.agent.allocate_budget(state, duration_days=-10)

        # 1500 gross -> 1320 net
        self.assertEqual(plan_none.total_allocated, 1320.00)
        self.assertEqual(plan_zero.total_allocated, 1320.00)
        self.assertEqual(plan_neg.total_allocated, 1320.00)


if __name__ == "__main__":
    unittest.main()
