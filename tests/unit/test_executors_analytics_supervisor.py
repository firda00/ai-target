"""
Unit tests for Milestones 3, 4, and 5:
- Offline Sandbox Adapters (Meta, TikTok, Adsly.Pro, AdsGram, Billing)
- Technical Executors (MetaTikTokExecutor, TelegramEcosystemExecutor)
- Analytics & Guardrails Agent (AnalyticsGuardrailsAgent)
- Supervisor Orchestrator & CLI Intake (SupervisorAgent, CliIntakeHandler, cli)
"""

import pytest

from ai_target.adapters import (
    AdsGramAdapter,
    AdslyProAdapter,
    BillingAggregatorAdapter,
    MetaMarketingAdapter,
    SandboxAdapterError,
    TikTokMarketingAdapter,
)
from ai_target.agents import (
    AnalyticsGuardrailsAgent,
    CliIntakeHandler,
    MetaTikTokExecutor,
    SupervisorAgent,
    TelegramEcosystemExecutor,
)
from ai_target.cli import main as cli_main, run_demo_simulation
from ai_target.state import (
    CampaignState,
    CampaignStatus,
    ClientBrief,
    Financials,
    PerformanceMetrics,
)
from ai_target.utils.moderation import ModerationError


class TestOfflineSandboxAdapters:
    def test_meta_adapter_enforces_paused_and_cents(self):
        adapter = MetaMarketingAdapter()
        with pytest.raises(SandboxAdapterError):
            adapter.create_campaign({"name": "Active_Test", "status": "ACTIVE"})
        with pytest.raises(SandboxAdapterError):
            adapter.create_adset({"name": "Float_Test", "daily_budget": 15.0, "status": "PAUSED"})
        with pytest.raises(SandboxAdapterError):
            adapter.create_adset({"name": "Low_Budget", "daily_budget": 999, "status": "PAUSED"})

        cmp_res = adapter.create_campaign({"name": "Valid_Camp", "status": "PAUSED"})
        adset_res = adapter.create_adset({"name": "Valid_AdSet", "campaign_id": cmp_res["id"], "daily_budget": 1000, "status": "PAUSED"})
        ad_res = adapter.create_ad({"name": "Valid_Ad", "adset_id": adset_res["id"], "status": "PAUSED"})
        assert cmp_res["status"] == "PAUSED"
        assert adset_res["daily_budget"] == 1000
        assert ad_res["status"] == "PAUSED"

    def test_tiktok_adapter_enforces_disable(self):
        adapter = TikTokMarketingAdapter()
        with pytest.raises(SandboxAdapterError):
            adapter.create_campaign({"campaign_name": "Active_TT", "operation_status": "ENABLE"})
        with pytest.raises(SandboxAdapterError):
            adapter.create_adgroup({"adgroup_name": "Active_AdG", "operation_status": "ENABLE"})

        res = adapter.create_campaign({"campaign_name": "Valid_TT", "budget": 50.0, "operation_status": "DISABLE"})
        assert res["data"]["operation_status"] == "DISABLE"

    def test_adsly_adapter_enforces_ton_floor_and_moderation(self):
        adapter = AdslyProAdapter()
        with pytest.raises(SandboxAdapterError):
            adapter.create_ad({"title": "Low Bid", "text": "Valid copy", "cpm_ton": 0.09, "budget_ton": 10.0})
        with pytest.raises(ModerationError):
            adapter.create_ad({"title": "URL Copy", "text": "Visit https://evil.com now", "cpm_ton": 0.15, "budget_ton": 10.0})

        res = adapter.create_ad({"title": "Good TON Ad", "text": "Join @my_ton_bot today!", "cpm_ton": 0.15, "budget_ton": 15.0})
        ad_id = res["data"]["ad_id"]
        assert res["data"]["ad_status"] == "PAUSED"

        upd = adapter.update_bid(ad_id, 0.22)
        assert upd["data"]["new_cpm_ton"] == 0.22
        with pytest.raises(SandboxAdapterError):
            adapter.update_bid(ad_id, 0.05)

    def test_adsgram_and_billing_adapters(self):
        ag = AdsGramAdapter()
        with pytest.raises(SandboxAdapterError):
            ag.create_campaign({"campaign_name": "Low_AG", "daily_budget_usdt": 9.5, "status": "PAUSED"})
        res = ag.create_campaign({"campaign_name": "Valid_AG", "daily_budget_usdt": 10.0, "status": "PAUSED"})
        assert res["status"] == "PAUSED"

        billing = BillingAggregatorAdapter()
        inv = billing.create_invoice(1000.0)
        assert inv["commission_amount"] == 120.0
        assert inv["net_media_spend"] == 880.0
        wh = billing.simulate_payment_webhook(inv["invoice_id"], 1000.0)
        assert wh["payment_verified"] is True


class TestOrchestratorAndExecutors:
    def test_supervisor_full_pipeline_and_cli_demo(self):
        state = run_demo_simulation(
            product_name="DeFi Wallet",
            target_geo="Kazakhstan, Uzbekistan",
            goal="leads",
            budget=2000.0,
        )
        assert state.status == CampaignStatus.LIVE
        assert state.financials.payment_verified is True
        assert len(state.media_plan.allocations) >= 3
        assert len(state.creatives) >= 4
        assert len(state.live_deployments) >= 3

        exit_code = cli_main(["--product", "TestBot", "--geo", "KZ", "--goal", "LEADS", "--budget", "1500"])
        assert exit_code == 0

    def test_analytics_guardrails_edge_cases(self):
        agent = AnalyticsGuardrailsAgent()
        # Empty metrics list should be a safe no-op
        empty_state = CampaignState(
            status=CampaignStatus.LIVE,
            financials=Financials(gross_budget=1000.0, payment_verified=True),
        )
        assert agent.apply_guardrails(empty_state).status == CampaignStatus.LIVE

        # High competition and strong CPA should clamp at ceiling 5.00 TON
        high_bid = agent.calculate_dynamic_ton_bid(
            current_cpm=4.80,
            competition_index=1.0,
            target_cpa=5.0,
            realized_cpa=1.0,
        )
        assert high_bid == 5.00

    def test_nan_inf_and_boolean_rejected_across_adapters_executors_and_analytics(self):
        adsly = AdslyProAdapter()
        adsgram = AdsGramAdapter()
        tiktok = TikTokMarketingAdapter()
        billing = BillingAggregatorAdapter()
        meta_tt = MetaTikTokExecutor()
        tg_exec = TelegramEcosystemExecutor()
        analytics = AnalyticsGuardrailsAgent()

        for bad_val in (float("nan"), float("inf"), float("-inf"), True, False):
            with pytest.raises(SandboxAdapterError):
                adsly.create_ad({"title": "Bad", "text": "Join @bot", "cpm_ton": bad_val, "budget_ton": 10.0})
            with pytest.raises(SandboxAdapterError):
                adsly.update_bid("ad_1", bad_val)
            with pytest.raises(SandboxAdapterError):
                adsgram.create_campaign({"campaign_name": "Bad", "daily_budget_usdt": bad_val, "status": "PAUSED"})
            with pytest.raises(SandboxAdapterError):
                tiktok.create_campaign({"campaign_name": "Bad", "budget": bad_val, "operation_status": "DISABLE"})
            with pytest.raises(SandboxAdapterError):
                billing.create_invoice(bad_val)
            with pytest.raises(ValueError):
                meta_tt.build_meta_payload(campaign_name="Bad", daily_budget_usd=bad_val)
            with pytest.raises(ValueError):
                meta_tt.build_tiktok_payload(campaign_name="Bad", daily_budget_usd=bad_val)
            with pytest.raises(ValueError):
                tg_exec.validate_or_build_ad_payload(title="Bad", text="Join @bot", cpm_ton=bad_val, budget_ton=10.0)
            with pytest.raises(ValueError):
                tg_exec.build_adsgram_payload(campaign_name="Bad", daily_budget_usdt=bad_val)
            with pytest.raises(ValueError):
                analytics.calculate_dynamic_ton_bid(current_cpm=bad_val, competition_index=0.5)
            with pytest.raises(ValueError):
                analytics.calculate_dynamic_ton_bid(current_cpm=0.20, competition_index=bad_val)

    def test_meta_decimal_half_up_cents_conversion(self):
        executor = MetaTikTokExecutor()
        # 10.005 USD * 100 in IEEE-754 float is 1000.4999999999999; Decimal ROUND_HALF_UP yields 1001 cents
        payload = executor.build_meta_payload(campaign_name="Precision_Test", daily_budget_usd=10.005)
        assert payload["adset"]["daily_budget"] == 1001

    def test_performance_metrics_reach_validation_and_auto_frequency(self):
        with pytest.raises(Exception):
            PerformanceMetrics(reach=-10)

        m = PerformanceMetrics(impressions=29000, reach=10000, spend=50.0, conversions=5, target_cpa=15.0)
        assert m.frequency == 2.90
        assert m.guardrail_triggered is True
        assert m.guardrail_action == "FATIGUE_ALERT"

    def test_simultaneous_kill_switch_and_creative_fatigue_records_both(self):
        agent = AnalyticsGuardrailsAgent()
        state = CampaignState(
            status=CampaignStatus.LIVE,
            financials=Financials(gross_budget=1000.0, payment_verified=True),
            performance_metrics=[
                PerformanceMetrics(
                    spend=160.0,
                    conversions=0,
                    target_cpa=100.0,
                    impressions=30000,
                    reach=10000,
                    frequency=3.0,
                )
            ],
        )
        updated = agent.apply_guardrails(state)
        latest = updated.performance_metrics[-1]
        assert updated.status == CampaignStatus.PAUSED
        assert latest.guardrail_action == "KILL_SWITCH"
        assert "Kill-switch triggered" in latest.notes
        assert "Concurrent creative fatigue detected" in latest.notes
        kill_audit = [e for e in updated.audit_trail if e["action"] == "KILL_SWITCH_TRIGGERED"][-1]
        assert kill_audit["details"]["fatigue_also_detected"] is True

    def test_cli_intake_normalization_and_empty_goal_rejection(self):
        handler = CliIntakeHandler(
            simulated_inputs={
                "product_name": "DeFi Bot",
                "target_geo": "Kazakhstan, Germany, Грузия",
                "goal": "subscribers",
                "budget": 1500.0,
            }
        )
        brief = handler.collect_brief()
        assert brief.target_geo == ["KZ", "DE", "GE"]
        assert brief.goal == "TELEGRAM_SUBSCRIBERS"

        with pytest.raises(ValueError):
            CliIntakeHandler(
                simulated_inputs={
                    "product_name": "DeFi Bot",
                    "target_geo": ["KZ"],
                    "goal": "   ",
                    "budget": 1500.0,
                }
            ).collect_brief()

        sup = SupervisorAgent()
        state = sup.create_campaign(brief)
        state = sup.run_planning_and_staging_pipeline(state)
        assert len(sup.billing_adapter.ledger) == 1
        state = sup.confirm_payment_and_launch(state)
        assert state.financials.payment_verified_at is not None
        assert all(d.status in ("ACTIVE", "ENABLE") for d in state.live_deployments)
