"""
Tier 4: Real-World Scenarios E2E Verification Suite.
Simulates complete multi-agent operational workflows:
- Scenario 1: Full Campaign Lifecycle (Intake -> Strategy -> Copy -> Staging -> Payment -> LIVE -> 24h Monitoring -> Completion)
- Scenario 2: Early Kill-Switch Bleed (Spend reaches 1.5x CPA with 0 conversions -> Automatic pause across platforms)
- Scenario 3: Creative Fatigue & Hot-Swap (Audience saturation frequency > 2.8 -> Fatigue alert -> Variant replacement)
- Scenario 4: TON Dynamic Bidding Auction Surge (Competition spike -> Dynamic bid adjustment adhering to TON bounds)
- Scenario 5: Payment Gate Rejection & Resolution (Unpaid launch blocked -> Webhook confirmed -> Launch succeeds)

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


class TestTier4RealWorldScenarios(unittest.TestCase):
    """End-to-end multi-agent operational scenario simulations."""

    def setUp(self):
        if not (AI_TARGET_STATE_AVAILABLE and AI_TARGET_SUPERVISOR_AVAILABLE and
                AI_TARGET_STRATEGIST_AVAILABLE and AI_TARGET_COPYWRITER_AVAILABLE and
                AI_TARGET_EXECUTORS_AVAILABLE and AI_TARGET_ANALYTICS_AVAILABLE):
            self.skipTest("Complete ai_target multi-agent system not yet implemented")

    def test_scenario_1_full_campaign_happy_path(self):
        """
        Scenario 1: Happy Path Full Lifecycle.
        1. Supervisor intake captures brief (Product, GEO, Goal, Budget).
        2. Strategist calculates 12% commission, net media spend, 4% cashback, and allocates budget.
        3. Copywriter generates compliant creatives with UTM parameters.
        4. Executors generate staged payloads in PAUSED status.
        5. Supervisor moves state to AWAITING_APPROVAL.
        6. Client completes payment -> Payment confirmed -> State moves to LIVE.
        7. 24-hour simulation loop runs at 2-hour intervals.
        8. 50+ conversions achieved -> Meta learning phase completes -> Campaign succeeds.
        """
        supervisor = SupervisorAgent()
        strategist = StrategistBillingAgent()
        copywriter = CreativeCopywriterAgent()
        meta_tt_exec = MetaTikTokExecutor(mode="sandbox")
        tg_exec = TelegramEcosystemExecutor(mode="sandbox")
        analytics = AnalyticsGuardrailsAgent()

        # Step 1: Intake
        brief = ClientBrief(
            product_name="Trading Signals App",
            target_geo=["KZ", "UZ"],
            goal="LEADS",
            budget=1500.0,
            product_description="AI-driven trading signals for Telegram"
        )
        state = supervisor.create_campaign(brief)
        self.assertEqual(state.status, CampaignStatus.INTAKE)

        # Step 2: Transition to PLANNING and calculate Financials & Media Plan
        state = supervisor.start_planning(state)
        self.assertEqual(state.status, CampaignStatus.PLANNING)

        financials = strategist.calculate_financials(state.client_brief.budget)
        self.assertAlmostEqual(financials.service_commission_amount, 180.0, places=2)
        self.assertAlmostEqual(financials.net_ad_spend, 1320.0, places=2)
        state.financials = financials

        media_plan = strategist.allocate_budget(state)
        state.media_plan = media_plan
        self.assertTrue(media_plan.platform_threshold_checks_passed)

        # Step 3: Creative Copywriter generates variants with UTMs
        creatives = copywriter.generate_all_campaign_creatives(
            product_name=brief.product_name,
            media_plan=media_plan,
            base_url="https://tradingsignals.io/join"
        )
        state.creatives = creatives
        self.assertGreaterEqual(len(state.creatives), 2)
        for cr in state.creatives:
            self.assertTrue(cr.moderation_passed)

        # Step 4: Technical Executors generate staged payloads
        for alloc in media_plan.allocations:
            if alloc.platform == PlatformEnum.META_INSTAGRAM:
                payload = meta_tt_exec.build_meta_payload(
                    campaign_name=f"{brief.product_name}_Meta",
                    daily_budget_usd=alloc.daily_budget,
                    creative_id="cr_meta_01",
                    destination_url="https://tradingsignals.io/join?utm_source=meta&utm_medium=reels&utm_campaign=q4&utm_content=v1"
                )
                self.assertEqual(payload["campaign"]["status"], "PAUSED")
                state.live_deployments.append(
                    LiveDeploymentRecord(
                        deployment_id="dep_meta_01",
                        platform=PlatformEnum.META_INSTAGRAM,
                        external_campaign_id="cmp_meta_01",
                        status="PAUSED",
                        raw_payload=payload
                    )
                )

        # Step 5: Advance to AWAITING_APPROVAL
        state.transition_to(CampaignStatus.AWAITING_APPROVAL)
        self.assertEqual(state.status, CampaignStatus.AWAITING_APPROVAL)

        # Step 6: Payment Verification
        billing_fixture = load_fixture("billing_responses.json")
        state.financials.payment_verified = True
        state.financials.payment_reference_id = billing_fixture["webhook_simulate"]["transaction_hash"]

        # Deploy to LIVE
        state.transition_to(CampaignStatus.LIVE)
        self.assertEqual(state.status, CampaignStatus.LIVE)

        # Step 7: Simulate 24-hour telemetry in 2-hour time-steps (12 steps)
        cumulative_spend = 0.0
        cumulative_conversions = 0
        for step in range(1, 13):
            step_spend = 40.0
            step_conversions = 5
            cumulative_spend += step_spend
            cumulative_conversions += step_conversions

            snapshot = PerformanceMetrics(
                spend=cumulative_spend,
                impressions=step * 5000,
                reach=step * 2500,
                clicks=step * 150,
                conversions=cumulative_conversions,
                target_cpa=15.0,
                frequency=2.0
            )
            state.performance_metrics.append(snapshot)
            state = analytics.apply_guardrails(state)
            self.assertEqual(state.status, CampaignStatus.LIVE)

        # Step 8: Verify outcomes
        final_metric = state.performance_metrics[-1]
        self.assertGreaterEqual(final_metric.conversions, 50)
        self.assertLessEqual(final_metric.cpa, 15.0)  # Realized CPA <= Target CPA
        learning_status = analytics.evaluate_learning_phase(final_metric.conversions, hours_elapsed=24)
        self.assertEqual(learning_status, "LEARNING_COMPLETE")

    def test_scenario_2_early_kill_switch_bleed(self):
        """
        Scenario 2: Early Kill-Switch Bleed.
        1. Campaign is LIVE with Target CPA = $40.0 USDT.
        2. Over periodic checks, spend increases: $20 -> $45 -> $65 USDT.
        3. 0 conversions are generated.
        4. At spend = $65.0 USDT (>= 1.5x $40.0 = $60.0), Kill-Switch triggers.
        5. State mutates to PAUSED, platform deployments are paused, and an alert is recorded.
        """
        analytics = AnalyticsGuardrailsAgent()

        state = CampaignState(
            campaign_id="cmp_scenario_bleed",
            status=CampaignStatus.LIVE,
            financials=Financials(gross_budget=1000.0, payment_verified=True),
            live_deployments=[
                LiveDeploymentRecord(
                    deployment_id="dep_01",
                    platform=PlatformEnum.META_INSTAGRAM,
                    external_campaign_id="cmp_meta_100",
                    status="ACTIVE"
                )
            ]
        )

        target_cpa = 40.0

        # Step 1 (t=2h): Spend $20, 0 conv -> No trigger
        m1 = PerformanceMetrics(spend=20.0, conversions=0, target_cpa=target_cpa)
        state.performance_metrics.append(m1)
        state = analytics.apply_guardrails(state)
        self.assertEqual(state.status, CampaignStatus.LIVE)
        self.assertFalse(m1.guardrail_triggered)

        # Step 2 (t=4h): Spend $45, 0 conv -> No trigger (< 60.0)
        m2 = PerformanceMetrics(spend=45.0, conversions=0, target_cpa=target_cpa)
        state.performance_metrics.append(m2)
        state = analytics.apply_guardrails(state)
        self.assertEqual(state.status, CampaignStatus.LIVE)
        self.assertFalse(m2.guardrail_triggered)

        # Step 3 (t=6h): Spend $65, 0 conv -> Kill-Switch MUST trigger (65.0 >= 1.5 * 40.0 = 60.0)
        m3 = PerformanceMetrics(spend=65.0, conversions=0, target_cpa=target_cpa)
        state.performance_metrics.append(m3)
        state = analytics.apply_guardrails(state)

        # Verify CampaignState halted to PAUSED
        self.assertEqual(state.status, CampaignStatus.PAUSED)
        self.assertTrue(m3.guardrail_triggered)
        self.assertEqual(m3.guardrail_action, "KILL_SWITCH")

    def test_scenario_3_creative_fatigue_and_hot_swap(self):
        """
        Scenario 3: Creative Fatigue & Hot-Swap.
        1. Campaign is LIVE in OPTIMIZING status.
        2. Ad delivery saturates audience: Reach = 10,000, Impressions = 29,000 -> Frequency = 2.90 (> 2.80).
        3. Fatigue Detector raises FATIGUE_ALERT.
        4. Creative Copywriter Agent swaps in Variant B.
        5. State preserves audit trail and deployment continuity.
        """
        analytics = AnalyticsGuardrailsAgent()
        copywriter = CreativeCopywriterAgent()

        state = CampaignState(
            campaign_id="cmp_scenario_fatigue",
            status=CampaignStatus.OPTIMIZING,
            financials=Financials(gross_budget=1000.0, payment_verified=True),
            creatives=[
                CreativeItem(
                    creative_id="cr_v1",
                    platform=PlatformEnum.META_INSTAGRAM,
                    format=AdFormatEnum.REELS_HOOK,
                    body_text="Hook V1: Are you missing out on crypto gains?",
                    call_to_action="LEARN_MORE",
                    raw_destination_url="https://example.com",
                    utm_tagged_url="https://example.com?utm_source=meta&utm_medium=reels&utm_campaign=c1&utm_content=v1",
                    ab_variant="A",
                    moderation_passed=True
                )
            ]
        )

        # Frequency exceeds 2.80 threshold
        m_fatigued = PerformanceMetrics(
            impressions=29000,
            reach=10000,
            frequency=2.90,
            spend=120.0,
            conversions=8,
            target_cpa=20.0
        )
        state.performance_metrics.append(m_fatigued)
        state = analytics.apply_guardrails(state)

        # Verify Fatigue Alert raised
        self.assertTrue(m_fatigued.guardrail_triggered)
        self.assertEqual(m_fatigued.guardrail_action, "FATIGUE_ALERT")

        # Copywriter executes rotation
        updated_state = copywriter.rotate_fatigued_creatives(state)
        self.assertGreaterEqual(len(updated_state.creatives), 2)
        # Verify Variant B was added
        self.assertTrue(any(c.ab_variant == "B" for c in updated_state.creatives))

    def test_scenario_4_ton_dynamic_bidding_auction_surge(self):
        """
        Scenario 4: TON Dynamic Bidding under Auction Surge.
        1. Adsly.Pro campaign starts at baseline CPM = 0.20 TON.
        2. Channel competition index spikes from 0.50 to 0.85 (bidding war).
        3. Realized CPA is healthy (0.70 TON vs Target CPA of 1.00 TON).
        4. Dynamic bidder raises bid to maintain ad position while respecting [0.10, 5.00] TON bounds.
        """
        analytics = AnalyticsGuardrailsAgent()

        baseline_cpm = 0.20
        new_cpm = analytics.calculate_dynamic_ton_bid(
            current_cpm=baseline_cpm,
            competition_index=0.85,  # Surge
            target_cpa=1.00,
            realized_cpa=0.70        # Profitable
        )
        # Bid must increase above baseline
        self.assertGreater(new_cpm, baseline_cpm)
        # Must respect bounds
        self.assertGreaterEqual(new_cpm, 0.10)
        self.assertLessEqual(new_cpm, 5.00)

    def test_scenario_5_payment_gate_rejection_and_resolution(self):
        """
        Scenario 5: Payment Gate Rejection and Resolution Flow.
        1. Supervisor completes intake and subagents stage campaign.
        2. State is at AWAITING_APPROVAL with payment_verified = False.
        3. Attempt to launch triggers PermissionError.
        4. Client submits payment -> Billing webhook confirms payment.
        5. payment_verified is updated to True.
        6. Launch is re-attempted and succeeds into LIVE.
        """
        supervisor = SupervisorAgent()
        state = CampaignState(
            campaign_id="cmp_scenario_gate",
            status=CampaignStatus.AWAITING_APPROVAL,
            financials=Financials(gross_budget=1000.0, payment_verified=False)
        )

        # Attempt launch: MUST fail
        with self.assertRaises(PermissionError):
            state.transition_to(CampaignStatus.LIVE)
        self.assertEqual(state.status, CampaignStatus.AWAITING_APPROVAL)

        # Webhook confirmation arrives
        state.financials.payment_verified = True
        state.financials.payment_reference_id = "tx_settled_998877"

        # Re-attempt launch: MUST succeed
        state.transition_to(CampaignStatus.LIVE)
        self.assertEqual(state.status, CampaignStatus.LIVE)


if __name__ == "__main__":
    unittest.main()
