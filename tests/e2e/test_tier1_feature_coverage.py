"""
Tier 1: Feature Coverage E2E Verification Suite.
Covers R1 through R6 in isolation (>= 5 tests per requirement) plus fixture integrity.
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
        LiveDeploymentRecord,
        PerformanceMetrics
    )
    AI_TARGET_STATE_AVAILABLE = True
except ImportError:
    AI_TARGET_STATE_AVAILABLE = False

try:
    from ai_target.utils.utm import build_tracked_url, append_utm_params
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
# Fixture Integrity Tests (Always active)
# ==============================================================================

class TestFixtureIntegrity(unittest.TestCase):
    """Verifies that all required mock JSON fixtures are present, valid JSON, and schema-compliant."""

    def test_meta_responses_fixture(self):
        data = load_fixture("meta_responses.json")
        self.assertIn("campaign_create", data)
        self.assertIn("adset_create", data)
        self.assertIn("ad_create", data)
        self.assertEqual(data["campaign_create"]["status"], "PAUSED")
        self.assertEqual(data["adset_create"]["status"], "PAUSED")
        self.assertEqual(data["ad_create"]["status"], "PAUSED")

    def test_tiktok_responses_fixture(self):
        data = load_fixture("tiktok_responses.json")
        self.assertIn("campaign_create", data)
        self.assertIn("adgroup_create", data)
        self.assertIn("ad_create", data)
        self.assertEqual(data["campaign_create"]["data"]["operation_status"], "DISABLE")
        self.assertEqual(data["adgroup_create"]["data"]["operation_status"], "DISABLE")

    def test_adsly_responses_fixture(self):
        data = load_fixture("adsly_responses.json")
        self.assertIn("channels_search", data)
        self.assertIn("ad_create", data)
        self.assertGreaterEqual(len(data["channels_search"]["data"]), 1)
        self.assertGreaterEqual(data["ad_create"]["data"]["cpm_ton"], 0.10)
        self.assertEqual(data["ad_create"]["data"]["ad_status"], "PAUSED")

    def test_adsgram_responses_fixture(self):
        data = load_fixture("adsgram_responses.json")
        self.assertIn("campaign_create", data)
        self.assertIn("analytics_get", data)
        self.assertGreaterEqual(data["campaign_create"]["daily_budget_usdt"], 10.0)
        self.assertEqual(data["campaign_create"]["status"], "PAUSED")

    def test_billing_responses_fixture(self):
        data = load_fixture("billing_responses.json")
        self.assertIn("invoice_create", data)
        self.assertIn("webhook_simulate", data)
        self.assertIn("cashback_ledger", data)
        self.assertEqual(data["invoice_create"]["commission_rate"], 0.12)
        self.assertTrue(data["webhook_simulate"]["payment_verified"])


# ==============================================================================
# Requirement 1: Supervisor Agent & Intake Dialogue (>= 5 tests)
# ==============================================================================

class TestR1SupervisorIntake(unittest.TestCase):
    """Feature verification for Supervisor Agent (R1)."""

    def setUp(self):
        if not AI_TARGET_SUPERVISOR_AVAILABLE or not AI_TARGET_STATE_AVAILABLE:
            self.skipTest("ai_target.agents.supervisor not yet implemented")

    def test_r1_01_cli_intake_parameter_collection(self):
        """Verifies CLI intake captures all 4 required parameters: product, GEO, goal, budget."""
        brief_data = {
            "product_name": "Crypto Trading Bot",
            "target_geo": ["KZ", "UZ"],
            "goal": "LEADS",
            "budget": 1200.0
        }
        handler = CliIntakeHandler(simulated_inputs=brief_data)
        brief = handler.collect_brief()
        self.assertEqual(brief.product_name, "Crypto Trading Bot")
        self.assertEqual(brief.target_geo, ["KZ", "UZ"])
        self.assertEqual(brief.goal, "LEADS")
        self.assertEqual(brief.budget, 1200.0)

    def test_r1_02_supervisor_initializes_state_in_intake(self):
        """Verifies supervisor instantiates CampaignState in INTAKE status with valid ClientBrief."""
        supervisor = SupervisorAgent()
        brief = ClientBrief(
            product_name="Telegram Mini App",
            target_geo=["GLOBAL"],
            goal="APP_INSTALLS",
            budget=2000.0
        )
        state = supervisor.create_campaign(brief=brief)
        self.assertEqual(state.status, CampaignStatus.INTAKE)
        self.assertIsNotNone(state.campaign_id)
        self.assertEqual(state.client_brief.product_name, "Telegram Mini App")

    def test_r1_03_supervisor_goal_normalization(self):
        """Verifies supervisor normalizes varied input goal strings into canonical objectives."""
        supervisor = SupervisorAgent()
        self.assertEqual(supervisor.normalize_goal("leads"), "LEADS")
        self.assertEqual(supervisor.normalize_goal("sales"), "SALES")
        self.assertEqual(supervisor.normalize_goal("subscribers"), "TELEGRAM_SUBSCRIBERS")
        self.assertEqual(supervisor.normalize_goal("installs"), "APP_INSTALLS")

    def test_r1_04_supervisor_geo_normalization(self):
        """Verifies supervisor normalizes geographical region tokens to standard ISO codes."""
        supervisor = SupervisorAgent()
        normalized = supervisor.normalize_geo(["Kazakhstan", "Uzbekistan", "Dubai"])
        self.assertIn("KZ", normalized)
        self.assertIn("UZ", normalized)
        self.assertIn("AE", normalized)

    def test_r1_05_supervisor_orchestrates_transition_to_planning(self):
        """Verifies supervisor orchestrates transition from INTAKE to PLANNING once brief is valid."""
        supervisor = SupervisorAgent()
        brief = ClientBrief(
            product_name="SaaS Analytics",
            target_geo=["US", "GB"],
            goal="TRAFFIC",
            budget=1500.0
        )
        state = supervisor.create_campaign(brief=brief)
        updated_state = supervisor.start_planning(state)
        self.assertEqual(updated_state.status, CampaignStatus.PLANNING)

    def test_r1_06_supervisor_blocks_launch_when_unpaid(self):
        """Verifies supervisor halts ad deployment and returns error when payment is unverified."""
        supervisor = SupervisorAgent()
        state = CampaignState(
            campaign_id="cmp_test_101",
            status=CampaignStatus.AWAITING_APPROVAL,
            financials=Financials(gross_budget=1000.0, payment_verified=False)
        )
        can_launch, reason = supervisor.can_launch(state)
        self.assertFalse(can_launch)
        self.assertIn("payment", reason.lower())


# ==============================================================================
# Requirement 2: Strategist & Billing Agent (>= 5 tests)
# ==============================================================================

class TestR2StrategistBilling(unittest.TestCase):
    """Feature verification for Strategist & Billing Agent (R2)."""

    def setUp(self):
        if not AI_TARGET_STRATEGIST_AVAILABLE or not AI_TARGET_STATE_AVAILABLE:
            self.skipTest("ai_target.agents.strategist not yet implemented")

    def test_r2_01_service_commission_deduction_12_percent(self):
        """Verifies agency service commission is exactly 12% of gross budget."""
        strategist = StrategistBillingAgent()
        gross_budget = 1000.0
        financials = strategist.calculate_financials(gross_budget)
        self.assertAlmostEqual(financials.service_commission_amount, 120.0, places=2)
        self.assertAlmostEqual(financials.service_commission_rate, 0.12, places=4)

    def test_r2_02_net_ad_spend_calculation_88_percent(self):
        """Verifies net ad spend is exactly 88% of gross client budget."""
        strategist = StrategistBillingAgent()
        gross_budget = 2500.0
        financials = strategist.calculate_financials(gross_budget)
        expected_net = round(2500.0 * 0.88, 2)
        self.assertAlmostEqual(financials.net_ad_spend, expected_net, places=2)

    def test_r2_03_clickru_cashback_calculation(self):
        """Verifies Click.ru agency cashback estimation within 3-5% tier rate."""
        strategist = StrategistBillingAgent()
        net_spend = 880.0
        cb_amount, cb_rate = strategist.estimate_cashback(net_spend, partner="click_ru")
        self.assertGreaterEqual(cb_rate, 0.03)
        self.assertLessEqual(cb_rate, 0.05)
        self.assertAlmostEqual(cb_amount, round(net_spend * cb_rate, 2), places=2)

    def test_r2_04_elama_cashback_calculation(self):
        """Verifies eLama agency cashback estimation within 3-6% tier rate."""
        strategist = StrategistBillingAgent()
        net_spend = 880.0
        cb_amount, cb_rate = strategist.estimate_cashback(net_spend, partner="elama")
        self.assertGreaterEqual(cb_rate, 0.03)
        self.assertLessEqual(cb_rate, 0.06)
        self.assertAlmostEqual(cb_amount, round(net_spend * cb_rate, 2), places=2)

    def test_r2_05_platform_budget_allocation_satisfies_thresholds(self):
        """Verifies media plan allocates net budget enforcing platform minimum thresholds."""
        strategist = StrategistBillingAgent()
        state = CampaignState(
            campaign_id="cmp_strat_01",
            status=CampaignStatus.PLANNING,
            client_brief=ClientBrief(
                product_name="Web3 Game",
                target_geo=["KZ", "UZ"],
                goal="LEADS",
                budget=1500.0
            ),
            financials=Financials(gross_budget=1500.0)
        )
        media_plan = strategist.allocate_budget(state)
        self.assertTrue(media_plan.platform_threshold_checks_passed)
        for alloc in media_plan.allocations:
            if alloc.platform == PlatformEnum.META_INSTAGRAM:
                self.assertGreaterEqual(alloc.daily_budget, 10.0)
            elif alloc.platform == PlatformEnum.TELEGRAM_ADSGRAM:
                self.assertGreaterEqual(alloc.daily_budget, 10.0)
            elif alloc.platform == PlatformEnum.TELEGRAM_ADSLY:
                self.assertGreaterEqual(alloc.cpm_estimate, 0.10)

    def test_r2_06_allocation_total_does_not_exceed_net_budget(self):
        """Verifies sum of allocated channel budgets does not exceed net ad spend."""
        strategist = StrategistBillingAgent()
        gross = 1000.0
        net = round(gross * 0.88, 2)
        state = CampaignState(
            campaign_id="cmp_strat_02",
            status=CampaignStatus.PLANNING,
            client_brief=ClientBrief(
                product_name="E-Commerce Store",
                target_geo=["US"],
                goal="SALES",
                budget=gross
            ),
            financials=Financials(gross_budget=gross, net_ad_spend=net)
        )
        media_plan = strategist.allocate_budget(state)
        self.assertLessEqual(media_plan.total_allocated, net)


# ==============================================================================
# Requirement 3: Creative Copywriter Agent (>= 5 tests)
# ==============================================================================

class TestR3CreativeCopywriter(unittest.TestCase):
    """Feature verification for Creative Copywriter Agent (R3)."""

    def setUp(self):
        if not AI_TARGET_COPYWRITER_AVAILABLE or not AI_TARGET_UTILS_AVAILABLE:
            self.skipTest("ai_target.agents.copywriter or utils not yet implemented")

    def test_r3_01_telegram_ads_copy_length_within_160_chars(self):
        """Verifies generated Telegram Ads copy does not exceed 160 characters."""
        copywriter = CreativeCopywriterAgent()
        variants = copywriter.generate_telegram_ads_copy("DeFi Trading Platform", "crypto traders")
        for v in variants:
            self.assertLessEqual(len(v.body_text), 160)
            self.assertTrue(validate_telegram_ads_copy(v.body_text))

    def test_r3_02_telegram_ads_copy_rejects_raw_external_links(self):
        """Verifies moderation rejects Telegram Ads copy containing raw external URLs."""
        valid_copy = "Trade TON and USDT with 0% fee. Join official bot @trade_ton_bot!"
        invalid_copy = "Trade TON with 0% fee on https://trade-ton.com join now!"
        self.assertTrue(validate_telegram_ads_copy(valid_copy))
        with self.assertRaises(ModerationError):
            validate_telegram_ads_copy(invalid_copy)

    def test_r3_03_reels_stories_hook_structure(self):
        """Verifies Instagram Reels/Stories creative contains 3-second hook, body, and CTA."""
        copywriter = CreativeCopywriterAgent()
        creative = copywriter.generate_reels_hook("Productivity App", "busy founders")
        self.assertIsNotNone(creative.headline)
        self.assertIsNotNone(creative.body_text)
        self.assertIsNotNone(creative.call_to_action)

    def test_r3_04_richads_push_banner_length_limits(self):
        """Verifies RichAds push creative complies with title <= 30 chars and body <= 45 chars."""
        copywriter = CreativeCopywriterAgent()
        push = copywriter.generate_push_creative("Flash Sale Shoes")
        self.assertLessEqual(len(push.headline), 30)
        self.assertLessEqual(len(push.body_text), 45)

    def test_r3_05_utm_parameter_injection_all_keys(self):
        """Verifies URL generator attaches all 4 mandatory UTM parameters."""
        base_url = "https://example.com/landing"
        tagged = build_tracked_url(
            base_url=base_url,
            utm_source="meta",
            utm_medium="reels",
            utm_campaign="leadgen_q4",
            utm_content="hook_curiosity_v1"
        )
        self.assertIn("utm_source=meta", tagged)
        self.assertIn("utm_medium=reels", tagged)
        self.assertIn("utm_campaign=leadgen_q4", tagged)
        self.assertIn("utm_content=hook_curiosity_v1", tagged)

    def test_r3_06_telega_in_native_post_length(self):
        """Verifies Telega.in native seed post length falls between 500 and 1500 characters."""
        copywriter = CreativeCopywriterAgent()
        post = copywriter.generate_telega_in_post("FinTech Masterclass")
        self.assertGreaterEqual(len(post.body_text), 500)
        self.assertLessEqual(len(post.body_text), 1500)


# ==============================================================================
# Requirement 4: Technical Executor Agents (Meta, TikTok, Telegram) (>= 5 tests)
# ==============================================================================

class TestR4TechnicalExecutors(unittest.TestCase):
    """Feature verification for Technical Executor Agents & Adapters (R4)."""

    def setUp(self):
        if not AI_TARGET_EXECUTORS_AVAILABLE or not AI_TARGET_STATE_AVAILABLE:
            self.skipTest("ai_target.agents.meta_tiktok or telegram_ecosystem not yet implemented")

    def test_r4_01_meta_payload_hierarchy_and_paused_status(self):
        """Verifies Meta executor outputs Campaign -> AdSet -> Ad payloads strictly in PAUSED status."""
        executor = MetaTikTokExecutor(mode="sandbox")
        payload = executor.build_meta_payload(
            campaign_name="Test_Meta_Cmp",
            daily_budget_usd=15.0,
            creative_id="cr_101",
            destination_url="https://example.com/promo?utm_source=meta&utm_medium=reels&utm_campaign=c1&utm_content=a"
        )
        self.assertEqual(payload["campaign"]["status"], "PAUSED")
        self.assertEqual(payload["adset"]["status"], "PAUSED")
        self.assertEqual(payload["ad"]["status"], "PAUSED")
        # Daily budget in cents (minimum 1000 = $10.00)
        self.assertEqual(payload["adset"]["daily_budget"], 1500)

    def test_r4_02_tiktok_payload_hierarchy_and_disable_status(self):
        """Verifies TikTok executor outputs Campaign -> AdGroup -> Ad with operation_status DISABLE."""
        executor = MetaTikTokExecutor(mode="sandbox")
        payload = executor.build_tiktok_payload(
            campaign_name="Test_TikTok_Cmp",
            daily_budget_usd=60.0,
            adgroup_budget_usd=30.0,
            destination_url="https://example.com/promo?utm_source=tiktok&utm_medium=video&utm_campaign=c1&utm_content=a"
        )
        self.assertEqual(payload["campaign"]["operation_status"], "DISABLE")
        self.assertEqual(payload["adgroup"]["operation_status"], "DISABLE")
        self.assertEqual(payload["ad"]["creatives"][0]["operation_status"], "DISABLE")

    def test_r4_03_telegram_competitor_channel_parsing(self):
        """Verifies Telegram ecosystem executor parses competitor channels extracting ER and estimated CPM."""
        executor = TelegramEcosystemExecutor(mode="sandbox")
        channels = executor.parse_competitor_channels(keywords=["crypto", "ton"], limit=3)
        self.assertGreaterEqual(len(channels), 1)
        for ch in channels:
            self.assertGreater(ch.subscribers, 0)
            self.assertGreater(ch.engagement_rate, 0.0)
            self.assertGreaterEqual(ch.estimated_cpm_ton, 0.10)

    def test_r4_04_adsly_ton_starting_bid_floor(self):
        """Verifies Adsly.Pro starting bid is calculated and adheres to >= 0.10 TON floor."""
        executor = TelegramEcosystemExecutor(mode="sandbox")
        bid = executor.compute_starting_bid_ton(estimated_cpm=0.08, competition="low")
        self.assertGreaterEqual(bid, 0.10)

    def test_r4_05_adsgram_mini_app_payload_creation(self):
        """Verifies AdsGram payload sets daily budget >= 10.0 USDT and status PAUSED."""
        executor = TelegramEcosystemExecutor(mode="sandbox")
        payload = executor.build_adsgram_payload(
            campaign_name="MiniApp_Ad",
            daily_budget_usdt=15.0,
            format="REWARDED_VIDEO",
            destination_url="https://t.me/app_bot/start?utm_source=adsgram&utm_medium=rewarded&utm_campaign=c1&utm_content=a"
        )
        self.assertGreaterEqual(payload["daily_budget_usdt"], 10.0)
        self.assertEqual(payload["status"], "PAUSED")

    def test_r4_06_mock_adapter_offline_roundtrip(self):
        """Verifies mock adapters deploy campaigns offline without network and return mock IDs."""
        executor = MetaTikTokExecutor(mode="sandbox")
        deploy_res = executor.deploy_meta_sandbox({"name": "Test_Campaign", "status": "PAUSED"})
        self.assertTrue(deploy_res["success"])
        self.assertTrue(deploy_res["id"].startswith("cmp_meta_"))


# ==============================================================================
# Requirement 5: Analytics & Guardrails Agent (>= 5 tests)
# ==============================================================================

class TestR5AnalyticsGuardrails(unittest.TestCase):
    """Feature verification for Analytics & Guardrails Agent (R5)."""

    def setUp(self):
        if not AI_TARGET_ANALYTICS_AVAILABLE or not AI_TARGET_STATE_AVAILABLE:
            self.skipTest("ai_target.agents.analytics not yet implemented")

    def test_r5_01_two_hour_interval_telemetry_evaluation(self):
        """Verifies discrete 2-hour interval time-step evaluation of campaign telemetry."""
        agent = AnalyticsGuardrailsAgent()
        metrics = PerformanceMetrics(
            spend=50.0,
            impressions=10000,
            reach=5000,
            clicks=250,
            conversions=5,
            target_cpa=12.0
        )
        action = agent.evaluate_metrics(metrics)
        self.assertFalse(metrics.guardrail_triggered)
        self.assertAlmostEqual(metrics.cpa, 10.0, places=2)

    def test_r5_02_meta_learning_phase_50_conversions(self):
        """Verifies tracking of 50 optimization events transitioning from LEARNING to LEARNING_COMPLETE."""
        agent = AnalyticsGuardrailsAgent()
        status_under = agent.evaluate_learning_phase(conversions=49, hours_elapsed=48)
        status_complete = agent.evaluate_learning_phase(conversions=50, hours_elapsed=48)
        self.assertEqual(status_under, "LEARNING")
        self.assertEqual(status_complete, "LEARNING_COMPLETE")

    def test_r5_03_kill_switch_triggers_on_1_5x_cpa_zero_conv(self):
        """Verifies kill-switch triggers and mutates status to PAUSED when spend >= 1.5x CPA with 0 conversions."""
        agent = AnalyticsGuardrailsAgent()
        metrics = PerformanceMetrics(
            spend=150.0,
            impressions=15000,
            reach=7000,
            clicks=300,
            conversions=0,
            target_cpa=100.0
        )
        action = agent.evaluate_metrics(metrics)
        self.assertTrue(metrics.guardrail_triggered)
        self.assertEqual(metrics.guardrail_action, "KILL_SWITCH")

    def test_r5_04_creative_fatigue_alert_when_frequency_exceeds_2_8(self):
        """Verifies creative fatigue alert fires when impression frequency exceeds 2.8."""
        agent = AnalyticsGuardrailsAgent()
        metrics = PerformanceMetrics(
            spend=80.0,
            impressions=29000,
            reach=10000,  # Frequency = 2.9
            clicks=150,
            conversions=4,
            target_cpa=25.0,
            frequency=2.9
        )
        action = agent.evaluate_metrics(metrics)
        self.assertTrue(metrics.guardrail_triggered)
        self.assertEqual(metrics.guardrail_action, "FATIGUE_ALERT")

    def test_r5_05_dynamic_ton_bid_adjustment(self):
        """Verifies dynamic CPM adjustments based on competition and performance respecting >= 0.1 TON floor."""
        agent = AnalyticsGuardrailsAgent()
        new_bid = agent.calculate_dynamic_ton_bid(
            current_cpm=0.20,
            competition_index=0.8,
            target_cpa=2.0,
            realized_cpa=1.5
        )
        self.assertGreaterEqual(new_bid, 0.10)

    def test_r5_06_kill_switch_action_dispatches_pause(self):
        """Verifies kill-switch action dispatches state pause mutation to CampaignState."""
        agent = AnalyticsGuardrailsAgent()
        state = CampaignState(
            campaign_id="cmp_guard_01",
            status=CampaignStatus.LIVE,
            financials=Financials(gross_budget=1000.0, payment_verified=True),
            performance_metrics=[
                PerformanceMetrics(spend=155.0, conversions=0, target_cpa=100.0)
            ]
        )
        updated_state = agent.apply_guardrails(state)
        self.assertEqual(updated_state.status, CampaignStatus.PAUSED)


# ==============================================================================
# Requirement 6: Shared CampaignState Schema & Architecture (>= 5 tests)
# ==============================================================================

class TestR6CampaignStateSchema(unittest.TestCase):
    """Feature verification for CampaignState Schema & State Lifecycle (R6)."""

    def setUp(self):
        if not AI_TARGET_STATE_AVAILABLE:
            self.skipTest("ai_target.state.models not yet implemented")

    def test_r6_01_campaign_state_pydantic_validation(self):
        """Verifies CampaignState model validates all required constituent fields."""
        state = CampaignState(
            campaign_id="cmp_schema_101",
            client_brief=ClientBrief(
                product_name="Trading Bot",
                target_geo=["GLOBAL"],
                goal="LEADS",
                budget=1000.0
            ),
            financials=Financials(gross_budget=1000.0)
        )
        self.assertEqual(state.campaign_id, "cmp_schema_101")
        self.assertEqual(state.status, CampaignStatus.INTAKE)
        self.assertEqual(state.client_brief.product_name, "Trading Bot")
        self.assertEqual(state.financials.gross_budget, 1000.0)

    def test_r6_02_state_lifecycle_fsm_valid_progression(self):
        """Verifies valid lifecycle progression: INTAKE -> PLANNING -> AWAITING_APPROVAL -> LIVE -> OPTIMIZING -> PAUSED."""
        state = CampaignState(
            campaign_id="cmp_fsm_01",
            status=CampaignStatus.INTAKE,
            financials=Financials(gross_budget=1000.0, payment_verified=True)
        )
        state.transition_to(CampaignStatus.PLANNING)
        self.assertEqual(state.status, CampaignStatus.PLANNING)

        state.transition_to(CampaignStatus.AWAITING_APPROVAL)
        self.assertEqual(state.status, CampaignStatus.AWAITING_APPROVAL)

        state.transition_to(CampaignStatus.LIVE)
        self.assertEqual(state.status, CampaignStatus.LIVE)

        state.transition_to(CampaignStatus.OPTIMIZING)
        self.assertEqual(state.status, CampaignStatus.OPTIMIZING)

        state.transition_to(CampaignStatus.PAUSED)
        self.assertEqual(state.status, CampaignStatus.PAUSED)

    def test_r6_03_state_lifecycle_fsm_invalid_transition_rejected(self):
        """Verifies illegal transition jumps (e.g. INTAKE directly to LIVE) raise ValueError."""
        state = CampaignState(
            campaign_id="cmp_fsm_02",
            status=CampaignStatus.INTAKE,
            financials=Financials(gross_budget=1000.0, payment_verified=True)
        )
        with self.assertRaises(ValueError):
            state.transition_to(CampaignStatus.LIVE)

    def test_r6_04_payment_verification_gate_blocks_live_transition(self):
        """Verifies attempting to transition to LIVE when payment_verified is False raises PermissionError."""
        state = CampaignState(
            campaign_id="cmp_fsm_03",
            status=CampaignStatus.AWAITING_APPROVAL,
            financials=Financials(gross_budget=1000.0, payment_verified=False)
        )
        with self.assertRaises(PermissionError):
            state.transition_to(CampaignStatus.LIVE)
        self.assertEqual(state.status, CampaignStatus.AWAITING_APPROVAL)

    def test_r6_05_payment_verification_gate_allows_live_when_verified(self):
        """Verifies transition to LIVE succeeds when payment_verified is True."""
        state = CampaignState(
            campaign_id="cmp_fsm_04",
            status=CampaignStatus.AWAITING_APPROVAL,
            financials=Financials(gross_budget=1000.0, payment_verified=True)
        )
        state.transition_to(CampaignStatus.LIVE)
        self.assertEqual(state.status, CampaignStatus.LIVE)

    def test_r6_06_campaign_state_serialization_roundtrip(self):
        """Verifies CampaignState serializes to JSON string and parses back identically."""
        state = CampaignState(
            campaign_id="cmp_json_01",
            status=CampaignStatus.PLANNING,
            client_brief=ClientBrief(
                product_name="Mobile App",
                target_geo=["KZ"],
                goal="APP_INSTALLS",
                budget=500.0
            ),
            financials=Financials(gross_budget=500.0)
        )
        json_data = state.model_dump_json()
        reloaded = CampaignState.model_validate_json(json_data)
        self.assertEqual(reloaded.campaign_id, state.campaign_id)
        self.assertEqual(reloaded.status, state.status)
        self.assertEqual(reloaded.client_brief.product_name, state.client_brief.product_name)


if __name__ == "__main__":
    unittest.main()
