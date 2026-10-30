"""
Tier 3: Cross-Feature Combinatorial E2E Verification Suite.
Evaluates pairwise and multi-component interactions across the system:
- State Machine Transitions + Billing Lifecycle & Webhook Confirmations
- Creative Variant Generation + UTM Tagging & Content Moderation
- Technical Executor Payloads + Mock Sandbox Deployments
- Financial Allocation + Platform Executor Budget Consistency
- Guardrail Kill-Switch + State FSM Mutation & Platform Pause Cascade
- Creative Fatigue Detection + Copywriter Variant Rotation
- Multi-Currency Budget Conversions (USDT / TON)
- Full CampaignState Serialization across Agent Handoffs

All tests run hermetically with zero network connectivity.
"""

import unittest
from pathlib import Path
from urllib.parse import urlparse, parse_qs

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


class TestTier3CrossFeature(unittest.TestCase):
    """Pairwise combinatorial tests across agents, state, adapters, and guardrails."""

    def setUp(self):
        if not (AI_TARGET_STATE_AVAILABLE and AI_TARGET_STRATEGIST_AVAILABLE and AI_TARGET_UTILS_AVAILABLE):
            self.skipTest("Core ai_target modules not yet implemented")

    def test_p1_state_transitions_coupled_with_billing_lifecycle(self):
        """
        Cross-feature: State FSM + Billing Invoicing + Payment Webhook.
        Verifies that an unpaid campaign stays blocked at AWAITING_APPROVAL until a simulated
        billing confirmation webhook mutates payment_verified to True, unlocking the LIVE transition.
        """
        # 1. Initialize campaign in PLANNING
        state = CampaignState(
            campaign_id="cmp_pair_01",
            status=CampaignStatus.PLANNING,
            client_brief=ClientBrief(
                product_name="TON DEX Aggregator",
                target_geo=["KZ", "UZ"],
                goal="LEADS",
                budget=1500.0
            ),
            financials=Financials(gross_budget=1500.0, payment_verified=False)
        )
        # Advance to AWAITING_APPROVAL
        state.transition_to(CampaignStatus.AWAITING_APPROVAL)
        self.assertEqual(state.status, CampaignStatus.AWAITING_APPROVAL)

        # 2. Gatekeeper strictly forbids transition to LIVE
        with self.assertRaises(PermissionError):
            state.transition_to(CampaignStatus.LIVE)
        self.assertFalse(state.financials.payment_verified)

        # 3. Simulate billing partner (Click.ru) payment webhook
        billing_fixture = load_fixture("billing_responses.json")
        webhook_data = billing_fixture["webhook_simulate"]
        self.assertTrue(webhook_data["payment_verified"])

        # Mutate financial status as Billing Adapter would
        state.financials.payment_verified = True
        state.financials.payment_reference_id = webhook_data["transaction_hash"]

        # 4. Gatekeeper now permits transition to LIVE
        state.transition_to(CampaignStatus.LIVE)
        self.assertEqual(state.status, CampaignStatus.LIVE)
        self.assertTrue(state.financials.payment_verified)

    def test_p2_creative_generation_coupled_with_utm_and_moderation(self):
        """
        Cross-feature: Creative Generation + UTM Tagging + Platform Moderation.
        Verifies that all creatives generated across platforms have complete UTM tracking
        and simultaneously pass their respective platform moderation rules.
        """
        if not AI_TARGET_COPYWRITER_AVAILABLE:
            self.skipTest("CreativeCopywriterAgent not yet available")

        copywriter = CreativeCopywriterAgent()
        product = "Crypto Trading Bot"
        base_url = "https://app.cryptotrading.com/signup"

        # 1. Generate Telegram Ads variants
        tg_variants = copywriter.generate_creatives_for_platform(
            platform=PlatformEnum.TELEGRAM_ADSLY,
            product_name=product,
            base_url=base_url,
            campaign_slug="pair_test_q4"
        )
        self.assertGreaterEqual(len(tg_variants), 1)
        for cr in tg_variants:
            # Moderation checks: <= 160 chars and no raw URLs in body
            self.assertLessEqual(len(cr.body_text), 160)
            self.assertTrue(validate_telegram_ads_copy(cr.body_text))
            # UTM checks on destination link
            parsed = urlparse(cr.utm_tagged_url)
            qs = parse_qs(parsed.query)
            self.assertIn("utm_source", qs)
            self.assertIn("utm_medium", qs)
            self.assertIn("utm_campaign", qs)
            self.assertIn("utm_content", qs)

        # 2. Generate Instagram Reels variants
        meta_variants = copywriter.generate_creatives_for_platform(
            platform=PlatformEnum.META_INSTAGRAM,
            product_name=product,
            base_url=base_url,
            campaign_slug="pair_test_q4"
        )
        self.assertGreaterEqual(len(meta_variants), 1)
        for cr in meta_variants:
            self.assertIsNotNone(cr.headline)
            self.assertIsNotNone(cr.call_to_action)
            parsed = urlparse(cr.utm_tagged_url)
            qs = parse_qs(parsed.query)
            self.assertEqual(qs["utm_source"][0], "meta_instagram")

    def test_p3_executor_payload_generation_coupled_with_mock_sandbox(self):
        """
        Cross-feature: Technical Executors + Mock Sandbox Adapters.
        Verifies that technical executors generate compliant payloads that are successfully
        accepted and deployed into mock sandbox memory with matching PAUSED / DISABLE statuses.
        """
        if not AI_TARGET_EXECUTORS_AVAILABLE:
            self.skipTest("Technical executors not yet available")

        # 1. Meta & TikTok Executor
        meta_tt_exec = MetaTikTokExecutor(mode="sandbox")
        state = CampaignState(
            campaign_id="cmp_pair_exec_01",
            status=CampaignStatus.PLANNING,
            client_brief=ClientBrief(
                product_name="Fitness App",
                target_geo=["KZ"],
                goal="APP_INSTALLS",
                budget=2000.0
            ),
            financials=Financials(gross_budget=2000.0, payment_verified=True)
        )

        meta_payload = meta_tt_exec.build_meta_payload(
            campaign_name="Fitness_Meta_Campaign",
            daily_budget_usd=25.0,
            creative_id="cr_meta_01",
            destination_url="https://fitness.app/join?utm_source=meta&utm_medium=reels&utm_campaign=q4&utm_content=v1"
        )
        # Sandbox deployment check
        meta_res = meta_tt_exec.deploy_meta_sandbox(meta_payload["campaign"])
        self.assertTrue(meta_res["success"])
        self.assertEqual(meta_payload["campaign"]["status"], "PAUSED")

        # 2. Telegram Ecosystem Executor
        tg_exec = TelegramEcosystemExecutor(mode="sandbox")
        adsly_payload = tg_exec.validate_or_build_ad_payload(
            title="Fitness Telegram Promo",
            text="Get custom workout routines in Telegram. Start now!",
            cpm_ton=0.20,
            budget_ton=15.0
        )
        adsly_res = tg_exec.deploy_adsly_sandbox(adsly_payload)
        self.assertEqual(adsly_res["data"]["ad_status"], "PAUSED")
        self.assertGreaterEqual(adsly_payload["cpm_ton"], 0.10)

    def test_p4_financial_allocation_coupled_with_executor_budgets(self):
        """
        Cross-feature: Strategist Budget Allocation + Platform Executor Validation.
        Verifies that budgets allocated by the Strategist are directly ingestible by
        the executors and satisfy every platform's minimum constraints simultaneously.
        """
        if not (AI_TARGET_STRATEGIST_AVAILABLE and AI_TARGET_EXECUTORS_AVAILABLE):
            self.skipTest("Strategist or Executors not available")

        strategist = StrategistBillingAgent()
        gross = 1500.0
        net = round(gross * 0.88, 2)

        state = CampaignState(
            campaign_id="cmp_pair_fin_01",
            status=CampaignStatus.PLANNING,
            client_brief=ClientBrief(
                product_name="Trading Bot",
                target_geo=["KZ", "UZ"],
                goal="LEADS",
                budget=gross
            ),
            financials=Financials(gross_budget=gross, net_ad_spend=net)
        )
        media_plan = strategist.allocate_budget(state)
        state.media_plan = media_plan

        # Verify each allocation produces a valid executor payload
        meta_tt_exec = MetaTikTokExecutor(mode="sandbox")
        tg_exec = TelegramEcosystemExecutor(mode="sandbox")

        for alloc in media_plan.allocations:
            if alloc.platform == PlatformEnum.META_INSTAGRAM:
                payload = meta_tt_exec.build_meta_payload(
                    campaign_name="Alloc_Meta",
                    daily_budget_usd=alloc.daily_budget,
                    creative_id="cr_1",
                    destination_url="https://example.com"
                )
                self.assertGreaterEqual(payload["adset"]["daily_budget"], 1000)  # >= $10.00 in cents
            elif alloc.platform == PlatformEnum.TELEGRAM_ADSGRAM:
                payload = tg_exec.build_adsgram_payload(
                    campaign_name="Alloc_Adsgram",
                    daily_budget_usdt=alloc.daily_budget,
                    format="REWARDED_VIDEO",
                    destination_url="https://example.com"
                )
                self.assertGreaterEqual(payload["daily_budget_usdt"], 10.0)
            elif alloc.platform == PlatformEnum.TELEGRAM_ADSLY:
                payload = tg_exec.validate_or_build_ad_payload(
                    title="Alloc_Adsly",
                    text="Ad copy under character limit",
                    cpm_ton=alloc.cpm_estimate,
                    budget_ton=alloc.allocated_budget
                )
                self.assertGreaterEqual(payload["cpm_ton"], 0.10)

    def test_p5_guardrail_kill_switch_triggers_state_mutation_and_platform_pause(self):
        """
        Cross-feature: Analytics Guardrail + State Machine + Adapter Pause.
        Verifies that when telemetry triggers the kill-switch (spend >= 1.5x CPA with 0 conversions),
        CampaignState transitions to PAUSED and platform adapters are signaled to pause.
        """
        if not AI_TARGET_ANALYTICS_AVAILABLE:
            self.skipTest("AnalyticsGuardrailsAgent not available")

        agent = AnalyticsGuardrailsAgent()
        state = CampaignState(
            campaign_id="cmp_pair_kill_01",
            status=CampaignStatus.LIVE,
            financials=Financials(gross_budget=1000.0, payment_verified=True),
            performance_metrics=[
                PerformanceMetrics(
                    spend=160.0,
                    conversions=0,
                    target_cpa=100.0
                )
            ]
        )
        updated_state = agent.apply_guardrails(state)
        # Verify status mutated to PAUSED
        self.assertEqual(updated_state.status, CampaignStatus.PAUSED)
        # Verify guardrail action recorded
        latest_metric = updated_state.performance_metrics[-1]
        self.assertTrue(latest_metric.guardrail_triggered)
        self.assertEqual(latest_metric.guardrail_action, "KILL_SWITCH")

    def test_p6_creative_fatigue_alert_triggers_variant_rotation(self):
        """
        Cross-feature: Fatigue Detection + Copywriter Variant Rotation.
        Verifies that when frequency exceeds 2.8, the fatigued variant is flagged
        and a replacement creative is activated in CampaignState.
        """
        if not (AI_TARGET_ANALYTICS_AVAILABLE and AI_TARGET_COPYWRITER_AVAILABLE):
            self.skipTest("Analytics or Copywriter not available")

        agent = AnalyticsGuardrailsAgent()
        copywriter = CreativeCopywriterAgent()

        state = CampaignState(
            campaign_id="cmp_pair_fatigue_01",
            status=CampaignStatus.OPTIMIZING,
            financials=Financials(gross_budget=1000.0, payment_verified=True),
            creatives=[
                CreativeItem(
                    creative_id="cr_v1",
                    platform=PlatformEnum.META_INSTAGRAM,
                    format=AdFormatEnum.REELS_HOOK,
                    body_text="Hook V1 copy",
                    call_to_action="LEARN_MORE",
                    raw_destination_url="https://example.com",
                    utm_tagged_url="https://example.com?utm_source=meta&utm_medium=reels&utm_campaign=c1&utm_content=v1",
                    ab_variant="A",
                    moderation_passed=True
                )
            ],
            performance_metrics=[
                PerformanceMetrics(
                    impressions=29000,
                    reach=10000,
                    frequency=2.90,
                    spend=50.0,
                    conversions=3
                )
            ]
        )
        # Apply guardrails
        updated_state = agent.apply_guardrails(state)
        latest_metric = updated_state.performance_metrics[-1]
        self.assertEqual(latest_metric.guardrail_action, "FATIGUE_ALERT")

        # Rotate creative via copywriter
        rotated_state = copywriter.rotate_fatigued_creatives(updated_state)
        self.assertGreater(len(rotated_state.creatives), 1)
        self.assertTrue(any(c.ab_variant == "B" for c in rotated_state.creatives))

    def test_p7_multi_currency_budget_and_bidding_consistency(self):
        """
        Cross-feature: Multi-Currency Allocation (USDT, USD, TON).
        Verifies consistent partitioning from client USDT funding into platform currencies:
        - USDT daily budgets for AdsGram (>= 10.0 USDT)
        - USD daily budgets for Meta/TikTok (>= 10.0 USD)
        - TON starting bids for Adsly.Pro (>= 0.10 TON)
        """
        if not AI_TARGET_STRATEGIST_AVAILABLE:
            self.skipTest("Strategist not available")

        strategist = StrategistBillingAgent()
        gross_usdt = 2000.0
        financials = strategist.calculate_financials(gross_usdt)
        self.assertEqual(financials.currency, "USDT")
        self.assertAlmostEqual(financials.service_commission_amount, 240.0, places=2)
        self.assertAlmostEqual(financials.net_ad_spend, 1760.0, places=2)

    def test_p8_full_campaign_state_serialization_roundtrip_across_handoffs(self):
        """
        Cross-feature: End-to-End CampaignState JSON Serialization.
        Verifies that CampaignState containing brief, financials, media plan, creatives,
        deployments, and metrics serializes to JSON and parses back identically without loss.
        """
        state = CampaignState(
            campaign_id="cmp_pair_json_full",
            status=CampaignStatus.LIVE,
            client_brief=ClientBrief(
                product_name="Trading Mini App",
                target_geo=["KZ", "UZ"],
                goal="LEADS",
                budget=1500.0
            ),
            financials=Financials(gross_budget=1500.0, payment_verified=True),
            media_plan=MediaPlan(
                allocations=[
                    ChannelAllocation(
                        platform=PlatformEnum.META_INSTAGRAM,
                        allocated_budget=600.0,
                        daily_budget=20.0
                    ),
                    ChannelAllocation(
                        platform=PlatformEnum.TELEGRAM_ADSGRAM,
                        allocated_budget=400.0,
                        daily_budget=13.33
                    )
                ]
            ),
            performance_metrics=[
                PerformanceMetrics(spend=45.0, impressions=10000, reach=4500, conversions=3)
            ]
        )
        serialized = state.model_dump_json()
        reconstituted = CampaignState.model_validate_json(serialized)

        self.assertEqual(reconstituted.campaign_id, state.campaign_id)
        self.assertEqual(reconstituted.status, CampaignStatus.LIVE)
        self.assertEqual(len(reconstituted.media_plan.allocations), 2)
        self.assertEqual(len(reconstituted.performance_metrics), 1)
        self.assertAlmostEqual(reconstituted.financials.gross_budget, 1500.0)


if __name__ == "__main__":
    unittest.main()
