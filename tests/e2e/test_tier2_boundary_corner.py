"""
Tier 2: Boundary & Corner Cases E2E Verification Suite.
Stress-tests extreme values, threshold boundaries, formatting limits, and invariant violations.
All tests run hermetically with zero network connectivity.
"""

import unittest
from pathlib import Path

# Load test infrastructure helpers
from tests.conftest import load_fixture, BlockedNetworkError

# Dynamic imports from target implementation
try:
    from ai_target.state.models import (
        CampaignState,
        CampaignStatus,
        ClientBrief,
        Financials,
        MediaPlan,
        ChannelAllocation,
        PlatformEnum,
        AdFormatEnum,
        CreativeItem,
        PerformanceMetrics
    )
    AI_TARGET_STATE_AVAILABLE = True
except ImportError:
    AI_TARGET_STATE_AVAILABLE = False

try:
    from ai_target.utils.utm import build_tracked_url
    from ai_target.utils.moderation import validate_telegram_ads_copy, ModerationError
    AI_TARGET_UTILS_AVAILABLE = True
except ImportError:
    AI_TARGET_UTILS_AVAILABLE = False

try:
    from ai_target.agents.supervisor import SupervisorAgent, CliIntakeHandler
    AI_TARGET_SUPERVISOR_AVAILABLE = True
except ImportError:
    AI_TARGET_SUPERVISOR_AVAILABLE = False

try:
    from ai_target.agents.strategist import StrategistBillingAgent
    AI_TARGET_STRATEGIST_AVAILABLE = True
except ImportError:
    AI_TARGET_STRATEGIST_AVAILABLE = False

try:
    from ai_target.agents.copywriter import CreativeCopywriterAgent
    AI_TARGET_COPYWRITER_AVAILABLE = True
except ImportError:
    AI_TARGET_COPYWRITER_AVAILABLE = False

try:
    from ai_target.agents.meta_tiktok import MetaTikTokExecutor
    from ai_target.agents.telegram_ecosystem import TelegramEcosystemExecutor
    AI_TARGET_EXECUTORS_AVAILABLE = True
except ImportError:
    AI_TARGET_EXECUTORS_AVAILABLE = False

try:
    from ai_target.agents.analytics import AnalyticsGuardrailsAgent
    AI_TARGET_ANALYTICS_AVAILABLE = True
except ImportError:
    AI_TARGET_ANALYTICS_AVAILABLE = False


# ==============================================================================
# Requirement 1: Supervisor Agent Boundaries (>= 5 tests)
# ==============================================================================

class TestR1SupervisorBoundaries(unittest.TestCase):
    """Boundary and corner testing for Supervisor Agent (R1)."""

    def setUp(self):
        if not AI_TARGET_STATE_AVAILABLE:
            self.skipTest("ai_target.state.models not yet implemented")

    def test_r1_boundary_zero_budget_rejected(self):
        """Verifies ClientBrief rejects gross budget of exactly 0."""
        with self.assertRaises(Exception):
            ClientBrief(
                product_name="Zero Budget App",
                target_geo=["KZ"],
                goal="LEADS",
                budget=0.0
            )

    def test_r1_boundary_negative_budget_rejected(self):
        """Verifies ClientBrief rejects negative gross budget."""
        with self.assertRaises(Exception):
            ClientBrief(
                product_name="Negative Budget App",
                target_geo=["KZ"],
                goal="LEADS",
                budget=-500.0
            )

    def test_r1_boundary_empty_product_name_rejected(self):
        """Verifies ClientBrief rejects empty product name string."""
        with self.assertRaises(Exception):
            ClientBrief(
                product_name="",
                target_geo=["KZ"],
                goal="LEADS",
                budget=1000.0
            )

    def test_r1_boundary_empty_target_geo_rejected(self):
        """Verifies ClientBrief rejects empty list of target GEOs."""
        with self.assertRaises(Exception):
            ClientBrief(
                product_name="Valid Product",
                target_geo=[],
                goal="LEADS",
                budget=1000.0
            )

    def test_r1_boundary_unicode_cyrillic_brief_handling(self):
        """Verifies ClientBrief handles full non-ASCII Cyrillic strings without corruption."""
        brief = ClientBrief(
            product_name="Приложение для тренировок 'Олимп'",
            target_geo=["KZ", "UZ", "RU"],
            goal="LEADS",
            budget=1500.0,
            product_description="Персональные фитнес-планы с поддержкой тренера в Telegram"
        )
        self.assertEqual(brief.product_name, "Приложение для тренировок 'Олимп'")
        self.assertIn("Telegram", brief.product_description)

    def test_r1_boundary_extreme_large_budget(self):
        """Verifies handling of extreme large budget ($10,000,000.00) without numerical overflow."""
        brief = ClientBrief(
            product_name="Enterprise Platform",
            target_geo=["GLOBAL"],
            goal="SALES",
            budget=10_000_000.0
        )
        self.assertEqual(brief.budget, 10_000_000.0)


# ==============================================================================
# Requirement 2: Strategist & Billing Boundaries (>= 5 tests)
# ==============================================================================

class TestR2StrategistBillingBoundaries(unittest.TestCase):
    """Boundary and corner testing for Strategist & Billing (R2)."""

    def setUp(self):
        if not AI_TARGET_STATE_AVAILABLE:
            self.skipTest("ai_target.state.models not yet implemented")

    def test_r2_boundary_micro_budget_commission(self):
        """Verifies precision of 12% commission calculation on micro-budget ($10.00)."""
        financials = Financials(gross_budget=10.0)
        self.assertAlmostEqual(financials.service_commission_amount, 1.20, places=2)
        self.assertAlmostEqual(financials.net_ad_spend, 8.80, places=2)

    def test_r2_boundary_adsgram_minimum_usdt_boundary(self):
        """Verifies AdsGram daily budget: 9.99 USDT is rejected, while 10.00 USDT is accepted."""
        # 9.99 USDT must raise ValueError
        with self.assertRaises(ValueError):
            ChannelAllocation(
                platform=PlatformEnum.TELEGRAM_ADSGRAM,
                allocated_budget=99.9,
                daily_budget=9.99
            )
        # 10.00 USDT must pass
        alloc = ChannelAllocation(
            platform=PlatformEnum.TELEGRAM_ADSGRAM,
            allocated_budget=100.0,
            daily_budget=10.00
        )
        self.assertEqual(alloc.daily_budget, 10.00)

    def test_r2_boundary_meta_reels_minimum_usdt_boundary(self):
        """Verifies Instagram Reels daily budget: 9.99 USDT is rejected, while 10.00 USDT is accepted."""
        with self.assertRaises(ValueError):
            ChannelAllocation(
                platform=PlatformEnum.META_INSTAGRAM,
                allocated_budget=99.9,
                daily_budget=9.99
            )
        alloc = ChannelAllocation(
            platform=PlatformEnum.META_INSTAGRAM,
            allocated_budget=100.0,
            daily_budget=10.00
        )
        self.assertEqual(alloc.daily_budget, 10.00)

    def test_r2_boundary_cashback_rate_bounds(self):
        """Verifies cashback rate validation enforces range 0.03 <= rate <= 0.06."""
        # Below 0.03 must be rejected
        with self.assertRaises(Exception):
            Financials(gross_budget=1000.0, agency_cashback_rate=0.029)
        # Above 0.06 must be rejected
        with self.assertRaises(Exception):
            Financials(gross_budget=1000.0, agency_cashback_rate=0.061)
        # 0.03 and 0.06 must pass
        f_min = Financials(gross_budget=1000.0, agency_cashback_rate=0.03)
        f_max = Financials(gross_budget=1000.0, agency_cashback_rate=0.06)
        self.assertEqual(f_min.agency_cashback_rate, 0.03)
        self.assertEqual(f_max.agency_cashback_rate, 0.06)

    def test_r2_boundary_adsly_cpm_minimum_estimate_boundary(self):
        """Verifies Adsly.Pro channel allocation rejects estimated CPM < 0.10 TON."""
        with self.assertRaises(ValueError):
            ChannelAllocation(
                platform=PlatformEnum.TELEGRAM_ADSLY,
                allocated_budget=50.0,
                daily_budget=5.0,
                cpm_estimate=0.09
            )
        alloc = ChannelAllocation(
            platform=PlatformEnum.TELEGRAM_ADSLY,
            allocated_budget=50.0,
            daily_budget=5.0,
            cpm_estimate=0.10
        )
        self.assertEqual(alloc.cpm_estimate, 0.10)


# ==============================================================================
# Requirement 3: Creative Moderation & UTM Boundaries (>= 5 tests)
# ==============================================================================

class TestR3CreativeModerationBoundaries(unittest.TestCase):
    """Boundary and corner testing for Creative Moderation & UTM Tagging (R3)."""

    def setUp(self):
        if not AI_TARGET_UTILS_AVAILABLE:
            self.skipTest("ai_target.utils not yet implemented")

    def test_r3_boundary_telegram_copy_159_chars_passes(self):
        """Verifies Telegram Ads copy with exactly 159 characters passes moderation."""
        text_159 = "A" * 159
        self.assertTrue(validate_telegram_ads_copy(text_159))

    def test_r3_boundary_telegram_copy_160_chars_passes(self):
        """Verifies Telegram Ads copy with exactly 160 characters passes moderation."""
        text_160 = "A" * 160
        self.assertTrue(validate_telegram_ads_copy(text_160))

    def test_r3_boundary_telegram_copy_161_chars_fails(self):
        """Verifies Telegram Ads copy with exactly 161 characters fails with ModerationError."""
        text_161 = "A" * 161
        with self.assertRaises(ModerationError):
            validate_telegram_ads_copy(text_161)

    def test_r3_boundary_telegram_copy_raw_urls_forbidden(self):
        """Verifies raw external links in Telegram Ads copy fail moderation."""
        cases = [
            "Join our group on https://example.com/now",
            "Visit http://trade-ton.io today!",
            "Go to www.myplatform.com to get bonus",
            "Sign up at crypto-bot.xyz right now"
        ]
        for c in cases:
            with self.assertRaises(ModerationError):
                validate_telegram_ads_copy(c)

    def test_r3_boundary_telegram_copy_allowed_handles_pass(self):
        """Verifies allowed Telegram usernames (@handle) pass copy moderation."""
        text = "Trade crypto with 0% fees. Check our verified channel @crypto_alpha_bot!"
        self.assertTrue(validate_telegram_ads_copy(text))

    def test_r3_boundary_utm_appending_existing_query_params(self):
        """Verifies UTM tagging correctly appends with '&' when base URL already has query parameters."""
        base_url = "https://example.com/product?category=trading&ref=affiliate"
        tagged = build_tracked_url(
            base_url=base_url,
            utm_source="meta",
            utm_medium="reels",
            utm_campaign="launch",
            utm_content="v1"
        )
        self.assertIn("category=trading", tagged)
        self.assertIn("ref=affiliate", tagged)
        self.assertIn("utm_source=meta", tagged)
        # Verify URL has exactly one '?'
        self.assertEqual(tagged.count("?"), 1)


# ==============================================================================
# Requirement 4: Technical Executor Boundaries (>= 5 tests)
# ==============================================================================

class TestR4ExecutorBoundaries(unittest.TestCase):
    """Boundary and corner testing for Platform Executors & Adapters (R4)."""

    def setUp(self):
        if not AI_TARGET_EXECUTORS_AVAILABLE:
            self.skipTest("ai_target.agents.meta_tiktok or telegram_ecosystem not yet implemented")

    def test_r4_boundary_adsly_cpm_0_09_ton_rejected(self):
        """Verifies Adsly.Pro executor rejects starting bid of 0.09 TON."""
        executor = TelegramEcosystemExecutor(mode="sandbox")
        with self.assertRaises(Exception):
            executor.validate_or_build_ad_payload(
                title="Test",
                text="Copy text under limit",
                cpm_ton=0.09,
                budget_ton=10.0
            )

    def test_r4_boundary_adsly_cpm_0_10_ton_accepted(self):
        """Verifies Adsly.Pro executor accepts starting bid of exactly 0.10 TON."""
        executor = TelegramEcosystemExecutor(mode="sandbox")
        payload = executor.validate_or_build_ad_payload(
            title="Test",
            text="Copy text under limit",
            cpm_ton=0.10,
            budget_ton=10.0
        )
        self.assertEqual(payload["cpm_ton"], 0.10)

    def test_r4_boundary_meta_budget_in_cents_conversion(self):
        """Verifies Meta executor strictly converts float USD daily budget into integer cents."""
        executor = MetaTikTokExecutor(mode="sandbox")
        payload = executor.build_meta_payload(
            campaign_name="Cents_Test",
            daily_budget_usd=12.34,
            creative_id="cr_1",
            destination_url="https://example.com"
        )
        self.assertEqual(payload["adset"]["daily_budget"], 1234)
        self.assertIsInstance(payload["adset"]["daily_budget"], int)

    def test_r4_boundary_meta_status_cannot_be_active(self):
        """Verifies Meta executor rejects or forces PAUSED status if ACTIVE is attempted."""
        executor = MetaTikTokExecutor(mode="sandbox")
        payload = executor.build_meta_payload(
            campaign_name="Test",
            daily_budget_usd=20.0,
            creative_id="cr_1",
            destination_url="https://example.com"
        )
        self.assertEqual(payload["campaign"]["status"], "PAUSED")
        self.assertEqual(payload["adset"]["status"], "PAUSED")
        self.assertEqual(payload["ad"]["status"], "PAUSED")

    def test_r4_boundary_tiktok_status_must_be_disable(self):
        """Verifies TikTok executor strictly enforces operation_status DISABLE."""
        executor = MetaTikTokExecutor(mode="sandbox")
        payload = executor.build_tiktok_payload(
            campaign_name="Test",
            daily_budget_usd=60.0,
            adgroup_budget_usd=30.0,
            destination_url="https://example.com"
        )
        self.assertEqual(payload["campaign"]["operation_status"], "DISABLE")
        self.assertEqual(payload["adgroup"]["operation_status"], "DISABLE")


# ==============================================================================
# Requirement 5: Analytics & Guardrails Boundaries (>= 5 tests)
# ==============================================================================

class TestR5AnalyticsGuardrailsBoundaries(unittest.TestCase):
    """Boundary and corner testing for Analytics & Guardrails (R5)."""

    def setUp(self):
        if not AI_TARGET_ANALYTICS_AVAILABLE or not AI_TARGET_STATE_AVAILABLE:
            self.skipTest("ai_target.agents.analytics not yet implemented")

    def test_r5_boundary_kill_switch_spend_1_49x_cpa_does_not_fire(self):
        """Verifies spend at exactly 1.49x target CPA with 0 conversions does NOT trigger kill-switch."""
        agent = AnalyticsGuardrailsAgent()
        target_cpa = 100.0
        metrics = PerformanceMetrics(
            spend=149.0,  # 1.49x target CPA
            conversions=0,
            target_cpa=target_cpa
        )
        agent.evaluate_metrics(metrics)
        self.assertFalse(metrics.guardrail_triggered)

    def test_r5_boundary_kill_switch_spend_1_50x_cpa_fires(self):
        """Verifies spend at exactly 1.50x target CPA with 0 conversions DOES trigger kill-switch."""
        agent = AnalyticsGuardrailsAgent()
        target_cpa = 100.0
        metrics = PerformanceMetrics(
            spend=150.0,  # Exactly 1.50x target CPA
            conversions=0,
            target_cpa=target_cpa
        )
        agent.evaluate_metrics(metrics)
        self.assertTrue(metrics.guardrail_triggered)
        self.assertEqual(metrics.guardrail_action, "KILL_SWITCH")

    def test_r5_boundary_kill_switch_with_one_conversion_does_not_fire(self):
        """Verifies spend at 1.50x target CPA with 1 conversion does NOT trigger zero-conversion kill-switch."""
        agent = AnalyticsGuardrailsAgent()
        target_cpa = 100.0
        metrics = PerformanceMetrics(
            spend=150.0,
            conversions=1,  # 1 conversion present
            target_cpa=target_cpa
        )
        agent.evaluate_metrics(metrics)
        self.assertFalse(metrics.guardrail_triggered)

    def test_r5_boundary_creative_fatigue_freq_2_79_does_not_fire(self):
        """Verifies frequency of 2.79 does NOT trigger fatigue alert."""
        agent = AnalyticsGuardrailsAgent()
        metrics = PerformanceMetrics(
            impressions=2790,
            reach=1000,
            frequency=2.79
        )
        agent.evaluate_metrics(metrics)
        self.assertFalse(metrics.guardrail_triggered)

    def test_r5_boundary_creative_fatigue_freq_2_80_does_not_fire(self):
        """Verifies frequency of exactly 2.80 does NOT trigger fatigue alert (condition is strictly > 2.8)."""
        agent = AnalyticsGuardrailsAgent()
        metrics = PerformanceMetrics(
            impressions=2800,
            reach=1000,
            frequency=2.80
        )
        agent.evaluate_metrics(metrics)
        self.assertFalse(metrics.guardrail_triggered)

    def test_r5_boundary_creative_fatigue_freq_2_81_fires(self):
        """Verifies frequency of 2.81 DOES trigger creative fatigue alert."""
        agent = AnalyticsGuardrailsAgent()
        metrics = PerformanceMetrics(
            impressions=2810,
            reach=1000,
            frequency=2.81
        )
        agent.evaluate_metrics(metrics)
        self.assertTrue(metrics.guardrail_triggered)
        self.assertEqual(metrics.guardrail_action, "FATIGUE_ALERT")

    def test_r5_boundary_meta_learning_phase_49_vs_50(self):
        """Verifies Meta learning phase boundary: 49 conversions is LEARNING, 50 conversions is LEARNING_COMPLETE."""
        agent = AnalyticsGuardrailsAgent()
        self.assertEqual(agent.evaluate_learning_phase(conversions=49, hours_elapsed=72), "LEARNING")
        self.assertEqual(agent.evaluate_learning_phase(conversions=50, hours_elapsed=72), "LEARNING_COMPLETE")

    def test_r5_boundary_dynamic_ton_bid_clamped_at_floor(self):
        """Verifies dynamic TON bid calculation producing lower value is clamped at >= 0.10 TON floor."""
        agent = AnalyticsGuardrailsAgent()
        # High target CPA vs very poor performance could reduce bid drastically
        bid = agent.calculate_dynamic_ton_bid(
            current_cpm=0.10,
            competition_index=0.1,
            target_cpa=1.0,
            realized_cpa=5.0
        )
        self.assertGreaterEqual(bid, 0.10)


# ==============================================================================
# Requirement 6: CampaignState Hard Gate & Lifecycle Boundaries (>= 5 tests)
# ==============================================================================

class TestR6CampaignStateBoundaries(unittest.TestCase):
    """Boundary and corner testing for CampaignState Schema & FSM (R6)."""

    def setUp(self):
        if not AI_TARGET_STATE_AVAILABLE:
            self.skipTest("ai_target.state.models not yet implemented")

    def test_r6_boundary_payment_verified_false_strictly_blocks_live(self):
        """Verifies hard gate: Attempting transition to LIVE when payment_verified=False raises PermissionError."""
        state = CampaignState(
            campaign_id="cmp_gate_01",
            status=CampaignStatus.AWAITING_APPROVAL,
            financials=Financials(gross_budget=1000.0, payment_verified=False)
        )
        with self.assertRaises(PermissionError):
            state.transition_to(CampaignStatus.LIVE)
        self.assertEqual(state.status, CampaignStatus.AWAITING_APPROVAL)

    def test_r6_boundary_payment_verified_true_permits_live(self):
        """Verifies hard gate: Transitioning to LIVE succeeds when payment_verified=True."""
        state = CampaignState(
            campaign_id="cmp_gate_02",
            status=CampaignStatus.AWAITING_APPROVAL,
            financials=Financials(gross_budget=1000.0, payment_verified=True)
        )
        state.transition_to(CampaignStatus.LIVE)
        self.assertEqual(state.status, CampaignStatus.LIVE)

    def test_r6_boundary_transition_paused_to_intake_forbidden(self):
        """Verifies FSM rejects transition from PAUSED directly back to INTAKE."""
        state = CampaignState(
            campaign_id="cmp_gate_03",
            status=CampaignStatus.PAUSED,
            financials=Financials(gross_budget=1000.0, payment_verified=True)
        )
        with self.assertRaises(ValueError):
            state.transition_to(CampaignStatus.INTAKE)

    def test_r6_boundary_transition_awaiting_approval_to_optimizing_forbidden(self):
        """Verifies FSM rejects skipping LIVE to reach OPTIMIZING."""
        state = CampaignState(
            campaign_id="cmp_gate_04",
            status=CampaignStatus.AWAITING_APPROVAL,
            financials=Financials(gross_budget=1000.0, payment_verified=True)
        )
        with self.assertRaises(ValueError):
            state.transition_to(CampaignStatus.OPTIMIZING)

    def test_r6_boundary_zero_gross_budget_financials_rejected(self):
        """Verifies Financials model rejects gross_budget <= 0."""
        with self.assertRaises(Exception):
            Financials(gross_budget=0.0)


if __name__ == "__main__":
    unittest.main()
