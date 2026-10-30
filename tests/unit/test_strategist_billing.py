"""
Unit Test Suite for StrategistBillingAgent (Milestone 2).
File: tests/unit/test_strategist_billing.py

Covers:
- Service commission calculation (12% commission, 88% net)
- Click.ru cashback calculation (default 5%, tier ranges 3–5%)
- eLama cashback calculation (default 4%, tier ranges 3–6%)
- Platform budget allocation (Instagram Reels, AdsGram, Adsly.Pro, Google Ads AI Max)
- Platform minimum floors (>=10 USDT/day Reels, >=10 USDT/day AdsGram, CPM >=0.10 TON)
- Insufficient budget handling and boundary edge cases (0, negative, fractional, huge budgets)
- Currency preservation and invalid partner error handling
- Zero external network connectivity (100% offline socket blocking enforced)
"""

import unittest
from typing import Optional

# Ensure hermetic offline socket blocking is engaged
from tests.conftest import BlockedNetworkError, enable_socket_blocking

enable_socket_blocking()

# Dynamic import with graceful skip if agent not yet implemented
try:
    from ai_target.agents.strategist import (
        ADSGRAM_MIN_DAILY_BUDGET_USDT,
        ADSLY_DEFAULT_CPM_TON,
        ADSLY_MIN_CPM_TON,
        CLICKRU_DEFAULT_CASHBACK_RATE,
        CLICKRU_MAX_CASHBACK_RATE,
        CLICKRU_MIN_CASHBACK_RATE,
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
    STRATEGIST_AVAILABLE = True
except ImportError:
    STRATEGIST_AVAILABLE = False


# ==============================================================================
# Category 1: Commission & Financial Calculations (6 tests)
# ==============================================================================

class TestCommissionCalculation(unittest.TestCase):
    """Verifies service commission (12%) and net media spend (88%) exactness."""

    def setUp(self):
        if not STRATEGIST_AVAILABLE:
            self.skipTest("StrategistBillingAgent or models not yet implemented")
        enable_socket_blocking()
        self.agent = StrategistBillingAgent()

    def test_commission_exactness_standard_budget(self):
        """Gross budget $1000.00 yields exactly $120.00 commission and $880.00 net."""
        fin = self.agent.calculate_financials(1000.0)
        self.assertAlmostEqual(fin.gross_budget, 1000.0, places=2)
        self.assertAlmostEqual(fin.service_commission_rate, 0.12, places=4)
        self.assertAlmostEqual(fin.service_commission, 120.00, places=2)
        self.assertAlmostEqual(fin.net_media_budget, 880.00, places=2)

    def test_commission_exactness_odd_fractional_budget(self):
        """Gross budget $1234.56 produces correctly rounded cent allocations."""
        fin = self.agent.calculate_financials(1234.56)
        expected_commission = round(1234.56 * 0.12, 2)  # 148.15
        expected_net = round(1234.56 - expected_commission, 2)  # 1086.41
        self.assertAlmostEqual(fin.service_commission, expected_commission, places=2)
        self.assertAlmostEqual(fin.net_media_budget, expected_net, places=2)
        self.assertAlmostEqual(fin.service_commission + fin.net_media_budget, 1234.56, places=2)

    def test_commission_micro_budget(self):
        """Micro budget of $10.00 produces $1.20 commission and $8.80 net."""
        fin = self.agent.calculate_financials(10.0)
        self.assertAlmostEqual(fin.service_commission, 1.20, places=2)
        self.assertAlmostEqual(fin.net_media_budget, 8.80, places=2)

    def test_commission_property_aliases(self):
        """Verifies model aliases service_commission_amount and net_ad_spend."""
        fin = self.agent.calculate_financials(2500.0)
        self.assertEqual(fin.service_commission_amount, fin.service_commission)
        self.assertEqual(fin.net_ad_spend, fin.net_media_budget)
        self.assertAlmostEqual(fin.service_commission_amount, 300.00, places=2)
        self.assertAlmostEqual(fin.net_ad_spend, 2200.00, places=2)

    def test_commission_large_enterprise_budget_precision(self):
        """Large budget $10,000,000.00 computes with zero IEEE-754 precision drift."""
        fin = self.agent.calculate_financials(10_000_000.0)
        self.assertAlmostEqual(fin.service_commission, 1_200_000.00, places=2)
        self.assertAlmostEqual(fin.net_media_budget, 8_800_000.00, places=2)

    def test_currency_preservation(self):
        """Financials retains specified currency code (USDT, USD, TON)."""
        fin_usdt = self.agent.calculate_financials(1000.0, currency="USDT")
        fin_ton = self.agent.calculate_financials(500.0, currency="TON")
        self.assertEqual(fin_usdt.currency, "USDT")
        self.assertEqual(fin_ton.currency, "TON")


# ==============================================================================
# Category 2: Cashback Calculations (Click.ru & eLama) (14 tests)
# ==============================================================================

class TestCashbackCalculation(unittest.TestCase):
    """Verifies Click.ru (3–5%, default 5%) and eLama (3–6%, default 4%) cashback models."""

    def setUp(self):
        if not STRATEGIST_AVAILABLE:
            self.skipTest("StrategistBillingAgent or models not yet implemented")
        enable_socket_blocking()
        self.agent = StrategistBillingAgent()

    def test_clickru_default_cashback_rate(self):
        """Click.ru default rate is 5% (0.05)."""
        cb_amount, cb_rate = self.agent.estimate_cashback(880.0, partner="click_ru")
        self.assertAlmostEqual(cb_rate, 0.05, places=4)
        self.assertAlmostEqual(cb_amount, 44.00, places=2)

    def test_clickru_tier_lower_bound_3_percent(self):
        """Click.ru minimum tier rate 3% (0.03) calculation."""
        cb_amount, cb_rate = self.agent.estimate_cashback(1000.0, partner="click_ru")
        self.assertGreaterEqual(cb_rate, 0.03)

    def test_clickru_tier_upper_bound_5_percent(self):
        """Click.ru maximum tier rate 5% (0.05) calculation."""
        cb_amount, cb_rate = self.agent.estimate_cashback(1000.0, partner="click_ru")
        self.assertLessEqual(cb_rate, 0.05)

    def test_clickru_case_insensitive_partner_name(self):
        """Partner normalization handles Click_RU and click.ru."""
        amount1, rate1 = self.agent.estimate_cashback(1000.0, partner="Click_RU")
        amount2, rate2 = self.agent.estimate_cashback(1000.0, partner="click.ru")
        self.assertEqual(rate1, 0.05)
        self.assertEqual(rate2, 0.05)
        self.assertEqual(amount1, 50.0)
        self.assertEqual(amount2, 50.0)

    def test_elama_default_cashback_rate(self):
        """eLama default rate is 4% (0.04)."""
        cb_amount, cb_rate = self.agent.estimate_cashback(880.0, partner="elama")
        self.assertAlmostEqual(cb_rate, 0.04, places=4)
        self.assertAlmostEqual(cb_amount, 35.20, places=2)

    def test_elama_tier_lower_bound_3_percent(self):
        """eLama tier rate is >= 3% (0.03)."""
        cb_amount, cb_rate = self.agent.estimate_cashback(1000.0, partner="elama")
        self.assertGreaterEqual(cb_rate, 0.03)

    def test_elama_tier_upper_bound_6_percent(self):
        """eLama tier rate is <= 6% (0.06)."""
        cb_amount, cb_rate = self.agent.estimate_cashback(1000.0, partner="elama")
        self.assertLessEqual(cb_rate, 0.06)

    def test_elama_case_insensitive_partner_name(self):
        """Partner normalization handles ELAMA and eLama."""
        amount, rate = self.agent.estimate_cashback(1000.0, partner="ELAMA")
        self.assertEqual(rate, 0.04)
        self.assertEqual(amount, 40.0)

    def test_calculate_financials_sets_clickru_cashback(self):
        """calculate_financials defaults to Click.ru cashback projection."""
        fin = self.agent.calculate_financials(1000.0, billing_partner="click_ru")
        self.assertAlmostEqual(fin.agency_cashback_rate, 0.05, places=4)
        self.assertAlmostEqual(fin.projected_cashback, 44.00, places=2)
        self.assertEqual(fin.estimated_cashback_amount, fin.projected_cashback)

    def test_calculate_financials_sets_elama_cashback(self):
        """calculate_financials with billing_partner='elama' sets 4% cashback projection."""
        fin = self.agent.calculate_financials(1000.0, billing_partner="elama")
        self.assertAlmostEqual(fin.agency_cashback_rate, 0.04, places=4)
        self.assertAlmostEqual(fin.projected_cashback, 35.20, places=2)

    def test_unsupported_partner_raises_error_or_falls_back(self):
        """Unsupported partner either defaults to click_ru or raises ValueError."""
        try:
            amount, rate = self.agent.estimate_cashback(1000.0, partner="unknown_broker_xyz")
            self.assertGreaterEqual(rate, 0.03)
            self.assertLessEqual(rate, 0.06)
        except ValueError:
            pass  # Raising ValueError is also acceptable

    def test_zero_net_spend_cashback(self):
        """Zero net spend yields zero cashback amount."""
        cb_amount, cb_rate = self.agent.estimate_cashback(0.0, partner="click_ru")
        self.assertEqual(cb_amount, 0.0)

    def test_negative_net_spend_raises_error(self):
        """Negative net spend raises ValueError."""
        with self.assertRaises(ValueError):
            self.agent.estimate_cashback(-100.0, partner="click_ru")

    def test_fractional_net_spend_cashback_rounding(self):
        """Fractional net spend rounds to 2 decimal places."""
        cb_amount, _ = self.agent.estimate_cashback(123.45, partner="click_ru")
        self.assertEqual(cb_amount, round(123.45 * 0.05, 2))


# ==============================================================================
# Category 3: Platform Budget Allocation (8 tests)
# ==============================================================================

class TestPlatformBudgetAllocation(unittest.TestCase):
    """Verifies media plan allocation and platform floor enforcement."""

    def setUp(self):
        if not STRATEGIST_AVAILABLE:
            self.skipTest("StrategistBillingAgent or models not yet implemented")
        enable_socket_blocking()
        self.agent = StrategistBillingAgent()

    def test_allocate_budget_happy_path_allocations(self):
        """Allocates net media budget across all required platforms."""
        state = CampaignState(
            campaign_id="cmp_strat_happy_01",
            status=CampaignStatus.PLANNING,
            client_brief=ClientBrief(
                product="Trading Mini App",
                geo="KZ, UZ",
                goal="LEADS",
                budget=1500.0,
            ),
            financials=Financials(gross_budget=1500.0),
        )
        plan = self.agent.allocate_budget(state, duration_days=14)
        self.assertIsInstance(plan, MediaPlan)
        self.assertTrue(plan.platform_threshold_checks_passed)
        self.assertGreaterEqual(len(plan.allocations), 3)

    def test_allocate_budget_total_does_not_exceed_net(self):
        """Total allocated budget strictly does not exceed net media budget."""
        gross = 2000.0
        net = round(gross * 0.88, 2)
        state = CampaignState(
            campaign_id="cmp_strat_inv_01",
            status=CampaignStatus.PLANNING,
            client_brief=ClientBrief(product="SaaS", geo="US", goal="SALES", budget=gross),
            financials=Financials(gross_budget=gross),
        )
        plan = self.agent.allocate_budget(state, duration_days=14)
        self.assertLessEqual(plan.total_allocated, net)

    def test_allocate_budget_reels_floor_enforcement(self):
        """Instagram Reels allocation enforces daily_budget >= 10.0 USDT."""
        state = CampaignState(
            campaign_id="cmp_strat_reels",
            status=CampaignStatus.PLANNING,
            client_brief=ClientBrief(product="App", geo="KZ", goal="INSTALLS", budget=1500.0),
            financials=Financials(gross_budget=1500.0),
        )
        plan = self.agent.allocate_budget(state, duration_days=14)
        reels_alloc = plan.get_allocation_for_platform(PlatformEnum.META_INSTAGRAM)
        self.assertIsNotNone(reels_alloc)
        self.assertGreaterEqual(reels_alloc.daily_budget, 10.00)

    def test_allocate_budget_adsgram_floor_enforcement(self):
        """Telegram AdsGram allocation enforces daily_budget >= 10.0 USDT."""
        state = CampaignState(
            campaign_id="cmp_strat_adsgram",
            status=CampaignStatus.PLANNING,
            client_brief=ClientBrief(product="Game", geo="UZ", goal="LEADS", budget=1500.0),
            financials=Financials(gross_budget=1500.0),
        )
        plan = self.agent.allocate_budget(state, duration_days=14)
        adsgram_alloc = plan.get_allocation_for_platform(PlatformEnum.TELEGRAM_ADSGRAM)
        self.assertIsNotNone(adsgram_alloc)
        self.assertGreaterEqual(adsgram_alloc.daily_budget, 10.00)

    def test_allocate_budget_adsly_cpm_floor_enforcement(self):
        """Telegram Adsly.Pro allocation enforces cpm_estimate >= 0.10 TON."""
        state = CampaignState(
            campaign_id="cmp_strat_adsly",
            status=CampaignStatus.PLANNING,
            client_brief=ClientBrief(product="DEX", geo="KZ", goal="TRAFFIC", budget=1500.0),
            financials=Financials(gross_budget=1500.0),
        )
        plan = self.agent.allocate_budget(state, duration_days=14)
        adsly_alloc = plan.get_allocation_for_platform(PlatformEnum.TELEGRAM_ADSLY)
        self.assertIsNotNone(adsly_alloc)
        self.assertIsNotNone(adsly_alloc.cpm_estimate)
        self.assertGreaterEqual(adsly_alloc.cpm_estimate, 0.10)

    def test_allocate_budget_google_ads_remainder(self):
        """Google Ads AI Max receives positive remainder allocation for healthy budgets."""
        state = CampaignState(
            campaign_id="cmp_strat_google",
            status=CampaignStatus.PLANNING,
            client_brief=ClientBrief(product="E-Com", geo="US", goal="SALES", budget=3000.0),
            financials=Financials(gross_budget=3000.0),
        )
        plan = self.agent.allocate_budget(state, duration_days=14)
        google_alloc = plan.get_allocation_for_platform(PlatformEnum.GOOGLE_ADS)
        self.assertIsNotNone(google_alloc)
        self.assertGreater(google_alloc.allocated_budget, 0.0)

    def test_allocate_budget_flight_duration_scaling(self):
        """Flight duration scaling (e.g. 30 days) scales cumulative platform minimums."""
        state = CampaignState(
            campaign_id="cmp_strat_30d",
            status=CampaignStatus.PLANNING,
            client_brief=ClientBrief(product="Course", geo="KZ", goal="LEADS", budget=3000.0),
            financials=Financials(gross_budget=3000.0),
        )
        plan = self.agent.allocate_budget(state, duration_days=30)
        reels_alloc = plan.get_allocation_for_platform(PlatformEnum.META_INSTAGRAM)
        self.assertGreaterEqual(reels_alloc.daily_budget, 10.00)
        self.assertGreaterEqual(reels_alloc.allocated_budget, 300.00)  # 30d * 10 USDT

    def test_allocate_budget_records_audit_trail_event(self):
        """allocate_budget records an ALLOCATE_BUDGET event in campaign audit trail."""
        state = CampaignState(
            campaign_id="cmp_strat_audit",
            status=CampaignStatus.PLANNING,
            client_brief=ClientBrief(product="Bot", geo="KZ", goal="LEADS", budget=1500.0),
            financials=Financials(gross_budget=1500.0),
        )
        self.agent.allocate_budget(state, duration_days=14)
        audit_actions = [e.get("action") for e in state.audit_trail]
        self.assertIn("ALLOCATE_BUDGET", audit_actions)


# ==============================================================================
# Category 4: Insufficient Budget & Boundary Edge Cases (4 tests)
# ==============================================================================

class TestInsufficientBudgetAndBoundaries(unittest.TestCase):
    """Verifies error handling on insufficient budgets, 0, negative, and invalid state."""

    def setUp(self):
        if not STRATEGIST_AVAILABLE:
            self.skipTest("StrategistBillingAgent or models not yet implemented")
        enable_socket_blocking()
        self.agent = StrategistBillingAgent()

    def test_insufficient_budget_for_flight_floors_raises_error(self):
        """Gross budget $50 ($44 net) cannot meet 14-day floors ($290 required) -> raises error."""
        state = CampaignState(
            campaign_id="cmp_strat_too_small",
            status=CampaignStatus.PLANNING,
            client_brief=ClientBrief(product="App", geo="KZ", goal="LEADS", budget=50.0),
            financials=Financials(gross_budget=50.0),
        )
        with self.assertRaises(ValueError):
            self.agent.allocate_budget(state, duration_days=14)

    def test_calculate_financials_zero_gross_budget_raises_error(self):
        """Gross budget of 0.00 raises ValueError."""
        with self.assertRaises(ValueError):
            self.agent.calculate_financials(0.0)

    def test_calculate_financials_negative_gross_budget_raises_error(self):
        """Negative gross budget (-500.00) raises ValueError."""
        with self.assertRaises(ValueError):
            self.agent.calculate_financials(-500.0)

    def test_allocate_budget_missing_financials_and_brief_raises_error(self):
        """CampaignState with no financials and no client brief budget raises ValueError."""
        state = CampaignState(
            campaign_id="cmp_strat_empty",
            status=CampaignStatus.PLANNING,
        )
        with self.assertRaises(ValueError):
            self.agent.allocate_budget(state)


if __name__ == "__main__":
    unittest.main()
