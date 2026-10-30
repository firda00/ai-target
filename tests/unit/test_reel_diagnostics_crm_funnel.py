"""
Unit & Integration Tests for Per-Reel Conversion Diagnostics, Auto-Pause,
Human-in-the-Loop Recommendations ('Решение за ними'), and Full-Funnel CRM Tracking
('Сколько человек написали и сколько продалось') for a 1–2 Person Marketing Team.
"""

import pytest
from pydantic import ValidationError

from ai_target.agents import AnalyticsGuardrailsAgent, SupervisorAgent
from ai_target.cli import run_demo_simulation
from ai_target.state import (
    ActionProposal,
    AdFormatEnum,
    CampaignState,
    CampaignStatus,
    ClientBrief,
    CreativeItem,
    CreativePerformanceMetrics,
    Financials,
    LiveDeploymentRecord,
    OptimizationRecommendation,
    PerformanceMetrics,
    PlatformEnum,
    ReelCreativeMetrics,
    ReelTelemetry,
)


class TestPerReelAutoPauseAndDiagnostics:
    """Verifies per-Reel conversion analysis, automatic pausing of weak Reels, and root-cause diagnostics."""

    def test_weak_reel_auto_paused_while_winning_reel_and_campaign_stay_active(self):
        supervisor = SupervisorAgent(mode="sandbox")
        brief = ClientBrief(
            product_name="AI Sales Assistant",
            target_geo=["KZ", "UZ"],
            goal="SALES",
            budget=2000.0,
        )
        state = supervisor.create_campaign(brief)
        state = supervisor.run_planning_and_staging_pipeline(state)
        state = supervisor.confirm_payment_and_launch(state)
        assert state.status == CampaignStatus.LIVE

        # Attach creative IDs from generated creatives to test CreativeItem status sync
        meta_creatives = [
            c for c in state.creatives if c.platform == PlatformEnum.META_INSTAGRAM
        ]
        winner_id = meta_creatives[0].creative_id if len(meta_creatives) >= 1 else "cr_reel_1"
        loser_id = meta_creatives[1].creative_id if len(meta_creatives) >= 2 else "cr_reel_2"

        reel_winner = ReelCreativeMetrics(
            creative_id=winner_id,
            creative_name="Reel 1: Strong Problem-Solution Hook",
            spend=45.0,
            impressions=10000,
            reach=5000,
            three_sec_views=3500,
            avg_watch_time_sec=7.2,
            clicks=300,
            messages_received=30,
            sales_count=9,
            revenue=900.0,
            target_cpa=15.0,
        )
        reel_loser = ReelCreativeMetrics(
            creative_id=loser_id,
            creative_name="Reel 2: Slow Talking Head Hook",
            spend=25.0,
            impressions=5000,
            reach=2500,
            three_sec_views=450,  # 9% hook rate (< 20%)
            avg_watch_time_sec=1.9,
            clicks=20,            # 0.4% CTR (< 1%)
            messages_received=0,  # 0 messages
            sales_count=0,        # 0 sales
            revenue=0.0,
            target_cpa=15.0,
        )
        state.reel_metrics = [reel_winner, reel_loser]

        report = supervisor.evaluate_reels_and_crm(state)

        # Campaign remains LIVE because overall performance is healthy, only the bad Reel is paused
        assert state.status == CampaignStatus.LIVE
        assert reel_winner.status == "ACTIVE"
        assert reel_winner.auto_paused is False

        assert reel_loser.status == "PAUSED"
        assert reel_loser.auto_paused is True
        assert reel_loser.pause_reason is not None
        assert len(reel_loser.why_low_conversion) >= 2
        assert len(reel_loser.recommendations) >= 2

        # Verify corresponding CreativeItem in state.creatives was also marked PAUSED
        if len(meta_creatives) >= 2:
            assert meta_creatives[0].status == "ACTIVE"
            assert meta_creatives[1].status == "PAUSED"

        # Verify report accurately reflects active vs paused Reels and CRM totals
        assert winner_id in report["active_reels"]
        assert len(report["paused_reels"]) == 1
        assert report["paused_reels"][0]["creative_id"] == loser_id
        assert report["messages_received"] == 30
        assert report["sales_count"] == 9
        assert report["lead_to_sale_rate"] == 30.0
        assert report["total_revenue"] == 900.0
        assert report["roas"] == round(900.0 / 70.0, 2)

        # Verify audit trail event recorded
        pause_events = [e for e in state.audit_trail if e["action"] == "REEL_AUTO_PAUSED"]
        assert len(pause_events) == 1
        assert pause_events[0]["details"]["creative_id"] == loser_id
        assert pause_events[0]["details"]["decision_mode"] == "PENDING_USER_DECISION"

    def test_diagnose_all_funnel_bottlenecks_individually(self):
        analytics = AnalyticsGuardrailsAgent()

        # 1. Weak Hook & Low CTR
        m_hook = ReelCreativeMetrics(
            creative_id="cr_hook_weak",
            spend=15.0,
            impressions=2000,
            three_sec_views=200,  # 10% hook rate
            avg_watch_time_sec=1.5,
            clicks=10,            # 0.5% CTR
            messages_received=1,
            sales_count=1,
            target_cpa=10.0,
        )
        recs_hook = analytics.diagnose_conversion_bottlenecks(m_hook)
        stages = {r.bottleneck_stage for r in recs_hook}
        assert "HOOK" in stages
        assert "CLICK" in stages
        assert all(r.decision_status == "PENDING_USER_DECISION" for r in recs_hook)

        # 2. High Clicks, Low Messages/Leads (Landing page / Telegram Bot drop-off)
        m_landing = ReelCreativeMetrics(
            creative_id="cr_landing_drop",
            spend=20.0,
            impressions=3000,
            three_sec_views=900,  # 30% hook rate (good)
            avg_watch_time_sec=5.5,
            clicks=90,            # 3.0% CTR (good)
            messages_received=0,  # 0% conversion to lead/message
            sales_count=0,
            target_cpa=15.0,
            target_conversion_rate=2.0,
        )
        recs_landing = analytics.diagnose_conversion_bottlenecks(m_landing)
        assert any(r.bottleneck_stage == "LEAD_MESSAGE" and r.category == "LANDING_BOT_FLOW" for r in recs_landing)

        # 3. Many People Wrote (`messages_received`), Few Bought (`sales_count`) -> Sales Script Bottleneck
        m_sales = ReelCreativeMetrics(
            creative_id="cr_sales_script_issue",
            spend=50.0,
            impressions=5000,
            three_sec_views=1500,  # 30% hook rate
            avg_watch_time_sec=6.0,
            clicks=200,            # 4% CTR
            messages_received=40,  # 40 people messaged!
            sales_count=1,         # Only 1 person bought (2.5% lead-to-sale rate < 10%)
            target_cpa=10.0,
        )
        action = analytics.evaluate_reel_metrics(m_sales)
        # Cost per lead is $1.25 (well below target_cpa $10), so Reel is NOT paused, but sales script recommendation is raised
        assert action == "RECOMMEND_OPTIMIZATION"
        assert m_sales.status == "ACTIVE"
        assert m_sales.lead_to_sale_rate == 2.5
        assert any("написали 40" in reason for reason in m_sales.why_low_conversion)

        # 4. Audience Fatigue (Frequency > 2.8)
        m_fatigue = ReelCreativeMetrics(
            creative_id="cr_fatigued",
            spend=40.0,
            impressions=32000,
            reach=10000,  # frequency = 3.2
            three_sec_views=8000,
            clicks=600,
            messages_received=20,
            sales_count=5,
            target_cpa=10.0,
        )
        recs_fatigue = analytics.diagnose_conversion_bottlenecks(m_fatigue)
        assert any(r.bottleneck_stage == "FREQUENCY" and r.category == "AUDIENCE_FATIGUE" for r in recs_fatigue)


class TestHumanInTheLoopDecisionWorkflow:
    """Verifies that recommendations stay in PENDING_USER_DECISION until approved or rejected by the marketer."""

    def test_approve_and_reject_recommendations_via_supervisor(self):
        supervisor = SupervisorAgent(mode="sandbox")
        state = run_demo_simulation(
            product_name="AI CRM Bot",
            target_geo="KZ",
            goal="SALES",
            budget=1500.0,
        )

        # Demo simulation has 1 winning Reel and 1 weak Reel that gets auto-paused
        assert len(state.pending_recommendations) >= 2
        assert all(r.decision_status == "PENDING_USER_DECISION" for r in state.pending_recommendations)

        first_rec = state.pending_recommendations[0]
        second_rec = state.pending_recommendations[1]
        initial_creatives_count = len(state.creatives)

        # Marketer approves the first recommendation (e.g. CREATIVE_HOOK)
        approved = supervisor.approve_recommendation(
            state=state,
            recommendation_id=first_rec.recommendation_id,
            user_comment="Согласен, меняем первые 3 секунды рилса на вариант B",
            decided_by="solo_marketer",
        )
        assert approved.decision_status == "APPROVED"
        assert approved.decided_by == "solo_marketer"
        assert approved.decided_at is not None
        assert approved.user_comment == "Согласен, меняем первые 3 секунды рилса на вариант B"
        assert len(state.creatives) > initial_creatives_count
        assert any(e["action"] == "ROTATE_FATIGUED_CREATIVES" for e in state.audit_trail)

        # Marketer rejects the second recommendation
        rejected = supervisor.reject_recommendation(
            state=state,
            recommendation_id=second_rec.recommendation_id,
            user_comment="Пока оставим текущий текст кнопки",
            decided_by="solo_marketer",
        )
        assert rejected.decision_status == "REJECTED"
        assert rejected.decided_by == "solo_marketer"

        # Verify audit trail entries
        decision_events = [e for e in state.audit_trail if e["action"] == "USER_DECISION_RECORDED"]
        assert len(decision_events) == 2
        assert decision_events[0]["details"]["decision_status"] == "APPROVED"
        assert decision_events[1]["details"]["decision_status"] == "REJECTED"

        # Calling get_marketing_team_dashboard after decisions must not re-add the already decided recommendations
        dashboard = supervisor.get_marketing_team_dashboard(state)
        pending_ids = {r["recommendation_id"] for r in dashboard["pending_recommendations"]}
        assert first_rec.recommendation_id not in pending_ids
        assert second_rec.recommendation_id not in pending_ids

        # Unknown recommendation_id raises ValueError
        with pytest.raises(ValueError, match="not found"):
            supervisor.approve_recommendation(state, "rec_nonexistent_999")


class TestFullFunnelCRMMetricsAndEdgeCases:
    """Verifies CRM tracking ('сколько написали и сколько продалось'), aliases, and boundary conditions."""

    def test_crm_aliases_and_derived_calculations(self):
        # Test leads_count / orders_closed aliases on ReelCreativeMetrics and PerformanceMetrics
        reel = CreativePerformanceMetrics(
            creative_id="cr_alias_test",
            spend=100.0,
            impressions=10000,
            three_sec_views=2500,
            clicks=250,
            leads_count=25,
            orders_closed=5,
            revenue=500.0,
            target_cpa=10.0,
        )
        assert isinstance(reel, ReelTelemetry)
        assert reel.messages_received == 25
        assert reel.leads_count == 25
        assert reel.sales_count == 5
        assert reel.orders_closed == 5
        assert reel.conversions == 25
        assert reel.hook_rate == 25.0
        assert reel.ctr == 2.5
        assert reel.conversion_rate == 10.0
        assert reel.cpa == 4.0
        assert reel.cost_per_message == 4.0
        assert reel.cost_per_sale == 20.0
        assert reel.lead_to_sale_rate == 20.0
        assert reel.roas == 5.0

        # Mutate via alias properties and verify derived CRM and conversion metrics immediately recompute
        reel.leads_count = 50
        reel.orders_closed = 10
        assert reel.messages_received == 50
        assert reel.sales_count == 10
        assert reel.conversions == 50
        assert reel.conversion_rate == 20.0
        assert reel.cpa == 2.0
        assert reel.cost_per_message == 2.0
        assert reel.cost_per_sale == 10.0
        assert reel.lead_to_sale_rate == 20.0

        pm = PerformanceMetrics(
            spend=200.0,
            impressions=20000,
            three_sec_views=5000,
            clicks=400,
            leads_count=50,
            orders_closed=10,
            revenue=1200.0,
            target_cpa=10.0,
        )
        assert pm.messages_received == 50
        assert pm.sales_count == 10
        assert pm.conversions == 50
        assert pm.learning_phase_status == "COMPLETED"
        assert pm.cost_per_message == 4.0
        assert pm.cost_per_sale == 20.0
        assert pm.lead_to_sale_rate == 20.0
        assert pm.roas == 6.0

    def test_zero_traffic_and_negative_inputs_edge_cases(self):
        # Zero spend, zero impressions, zero clicks, zero messages, zero sales
        empty_reel = ReelCreativeMetrics(creative_id="cr_zero")
        assert empty_reel.cpa == 0.0
        assert empty_reel.cost_per_message == 0.0
        assert empty_reel.cost_per_sale == 0.0
        assert empty_reel.lead_to_sale_rate == 0.0
        assert empty_reel.roas == 0.0

        analytics = AnalyticsGuardrailsAgent()
        assert analytics.evaluate_reel_metrics(empty_reel) is None
        assert empty_reel.status == "ACTIVE"

        # Negative values must be rejected by Pydantic validation
        with pytest.raises(ValidationError):
            ReelCreativeMetrics(creative_id="cr_neg", messages_received=-1)
        with pytest.raises(ValidationError):
            ReelCreativeMetrics(creative_id="cr_neg", sales_count=-5)
        with pytest.raises(ValidationError):
            PerformanceMetrics(messages_received=-2)
        with pytest.raises(ValidationError):
            PerformanceMetrics(sales_count=-1)

    def test_deployment_ad_status_paused_when_matching_reel_paused(self):
        analytics = AnalyticsGuardrailsAgent()
        state = CampaignState(
            status=CampaignStatus.LIVE,
            financials=Financials(gross_budget=1000.0, payment_verified=True),
            live_deployments=[
                LiveDeploymentRecord(
                    platform=PlatformEnum.META_INSTAGRAM,
                    external_campaign_id="cmp_meta_1",
                    status="ACTIVE",
                    raw_payload={
                        "campaign": {"status": "ACTIVE"},
                        "ad": {"status": "ACTIVE", "creative": {"creative_id": "cr_bad_reel"}},
                    },
                ),
                LiveDeploymentRecord(
                    platform=PlatformEnum.TIKTOK,
                    external_campaign_id="cmp_tt_1",
                    status="ENABLE",
                    raw_payload={
                        "campaign": {"operation_status": "ENABLE"},
                        "ad": {
                            "operation_status": "ENABLE",
                            "creatives": [{"creative_id": "cr_bad_tiktok", "operation_status": "ENABLE"}],
                        },
                    },
                ),
            ],
            reel_metrics=[
                ReelCreativeMetrics(
                    creative_id="cr_bad_reel",
                    platform=PlatformEnum.META_INSTAGRAM,
                    spend=30.0,
                    impressions=3000,
                    clicks=10,
                    messages_received=0,
                    sales_count=0,
                    target_cpa=15.0,
                ),
                ReelCreativeMetrics(
                    creative_id="cr_bad_tiktok",
                    platform=PlatformEnum.TIKTOK,
                    spend=30.0,
                    impressions=4000,
                    clicks=12,
                    messages_received=0,
                    sales_count=0,
                    target_cpa=15.0,
                ),
            ],
        )
        analytics.apply_guardrails(state)
        assert state.reel_metrics[0].status == "PAUSED"
        assert state.reel_metrics[1].status == "PAUSED"
        assert state.live_deployments[0].raw_payload["ad"]["status"] == "PAUSED"
        assert state.live_deployments[1].raw_payload["ad"]["creatives"][0]["operation_status"] == "DISABLE"

        # Verify JSON serialization roundtrip preserves reel_metrics and pending_recommendations
        dumped = state.model_dump_json()
        restored = CampaignState.model_validate_json(dumped)
        assert len(restored.reel_metrics) == 2
        assert restored.reel_metrics[0].status == "PAUSED"
        assert len(restored.pending_recommendations) >= 2
        assert restored.pending_recommendations[0].decision_status == "PENDING_USER_DECISION"

    def test_multi_step_reel_recovery_and_reenable_clears_auto_paused(self):
        supervisor = SupervisorAgent(mode="sandbox")
        cr = CreativeItem(
            creative_id="cr_recover_1",
            platform=PlatformEnum.META_INSTAGRAM,
            format=AdFormatEnum.REELS_HOOK,
            headline="Hook 1",
            body_text="Test body",
            raw_destination_url="https://example.com",
            utm_tagged_url="https://example.com?utm_source=meta&utm_medium=cpc&utm_campaign=c1&utm_content=v1",
        )
        reel = ReelCreativeMetrics(
            creative_id="cr_recover_1",
            spend=25.0,
            impressions=4000,
            three_sec_views=300,
            avg_watch_time_sec=1.5,
            clicks=10,
            messages_received=0,
            sales_count=0,
            target_cpa=15.0,
        )
        state = CampaignState(
            status=CampaignStatus.LIVE,
            financials=Financials(gross_budget=1000.0, payment_verified=True),
            creatives=[cr],
            reel_metrics=[reel],
        )

        # Step 1: Underperforming Reel is auto-paused
        report_step1 = supervisor.evaluate_reels_and_crm(state)
        assert reel.status == "PAUSED"
        assert reel.auto_paused is True
        assert state.creatives[0].status == "PAUSED"
        assert "cr_recover_1" not in report_step1["active_reels"]
        assert len(report_step1["paused_reels"]) == 1

        # Step 2: Marketer replaces the hook, re-enables the Reel, and new telemetry shows strong conversions
        reel.status = "ACTIVE"
        reel.three_sec_views = 1600
        reel.avg_watch_time_sec = 6.5
        reel.clicks = 160
        reel.messages_received = 20
        reel.sales_count = 5
        reel.revenue = 500.0

        report_step2 = supervisor.evaluate_reels_and_crm(state)
        assert reel.status == "ACTIVE"
        assert reel.auto_paused is False
        assert reel.pause_reason is None
        assert state.creatives[0].status == "ACTIVE"
        assert "cr_recover_1" in report_step2["active_reels"]
        assert len(report_step2["paused_reels"]) == 0
        assert reel.conversions == 20
        assert reel.hook_rate == 40.0
        assert reel.ctr == 4.0
        assert reel.conversion_rate == 12.5
        assert reel.lead_to_sale_rate == 25.0

