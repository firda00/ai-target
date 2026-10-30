"""
Unit tests for ai_target.state.models.
Verifies Pydantic v2 schemas, validations, state transitions, and guardrails.
"""

import pytest
from ai_target.state.models import (
    AdFormatEnum,
    CampaignState,
    CampaignStatus,
    ChannelAllocation,
    ClientBrief,
    CreativeItem,
    Financials,
    InvalidStateTransitionError,
    MediaPlan,
    PaymentVerificationError,
    PerformanceMetrics,
    PlatformEnum,
)


class TestCampaignStatusEnums:
    def test_status_enum_values(self):
        assert CampaignStatus.INTAKE == "INTAKE"
        assert CampaignStatus.PLANNING == "PLANNING"
        assert CampaignStatus.AWAITING_APPROVAL == "AWAITING_APPROVAL"
        assert CampaignStatus.LIVE == "LIVE"
        assert CampaignStatus.OPTIMIZING == "OPTIMIZING"
        assert CampaignStatus.PAUSED == "PAUSED"

    def test_string_interoperability(self):
        assert CampaignStatus("LIVE") == CampaignStatus.LIVE


class TestClientBriefModel:
    def test_valid_client_brief_canonical(self):
        brief = ClientBrief(
            product="Crypto Wallet",
            geo="KZ, UZ",
            goal="LEADS",
            budget=1500.0,
        )
        assert brief.product == "Crypto Wallet"
        assert brief.product_name == "Crypto Wallet"
        assert brief.geo == "KZ, UZ"
        assert brief.budget == 1500.0

    def test_client_brief_alias_inputs(self):
        brief = ClientBrief(
            product_name="Telegram Mini App",
            target_geo=["AE", "KZ"],
            goal="INSTALLS",
            budget=2000.0,
        )
        assert brief.product == "Telegram Mini App"
        assert "AE" in brief.geo

    def test_invalid_negative_or_zero_budget(self):
        with pytest.raises(ValueError):
            ClientBrief(product="Test", geo="KZ", goal="LEADS", budget=0.0)
        with pytest.raises(ValueError):
            ClientBrief(product="Test", geo="KZ", goal="LEADS", budget=-100.0)


class TestFinancialsModel:
    def test_auto_compute_commission_and_net_spend(self):
        fin = Financials(gross_budget=1000.0)
        assert fin.service_commission == 120.0  # 12%
        assert fin.net_media_budget == 880.0    # 88%
        assert fin.payment_verified is False
        assert fin.projected_cashback == round(880.0 * 0.05, 2)

    def test_elama_cashback_partner_calculation(self):
        fin = Financials(gross_budget=2000.0, billing_partner="elama")
        assert fin.service_commission == 240.0
        assert fin.net_media_budget == 1760.0
        assert fin.projected_cashback == round(1760.0 * 0.04, 2)

    def test_compatibility_properties(self):
        fin = Financials(gross_budget=1000.0)
        assert fin.service_commission_amount == 120.0
        assert fin.net_ad_spend == 880.0
        assert fin.estimated_cashback_amount == fin.projected_cashback


class TestChannelAllocationAndMediaPlan:
    def test_valid_allocations(self):
        alloc = ChannelAllocation(
            platform=PlatformEnum.META_INSTAGRAM,
            allocated_budget=300.0,
            daily_budget=10.0,
        )
        assert alloc.daily_budget == 10.0

    def test_instagram_reels_sub_10_daily_threshold_rejected(self):
        with pytest.raises(ValueError, match="minimum daily budget of 10.0 USDT"):
            ChannelAllocation(
                platform=PlatformEnum.META_INSTAGRAM,
                allocated_budget=100.0,
                daily_budget=9.99,
            )

    def test_adsgram_sub_10_daily_threshold_rejected(self):
        with pytest.raises(ValueError, match="minimum daily budget of 10.0 USDT"):
            ChannelAllocation(
                platform=PlatformEnum.TELEGRAM_ADSGRAM,
                allocated_budget=100.0,
                daily_budget=5.0,
            )

    def test_adsly_sub_point_one_ton_cpm_rejected(self):
        with pytest.raises(ValueError, match="must be >= 0.10 TON"):
            ChannelAllocation(
                platform=PlatformEnum.TELEGRAM_ADSLY,
                allocated_budget=100.0,
                daily_budget=10.0,
                cpm_estimate=0.08,
            )

    def test_media_plan_aggregation(self):
        plan = MediaPlan(allocations=[
            ChannelAllocation(platform=PlatformEnum.META_INSTAGRAM, allocated_budget=200.0, daily_budget=10.0),
            ChannelAllocation(platform=PlatformEnum.TELEGRAM_ADSGRAM, allocated_budget=300.0, daily_budget=15.0),
        ])
        assert plan.total_allocated == 500.0
        assert plan.platform_threshold_checks_passed is True


class TestCreativeItemAndModeration:
    def test_telegram_ads_over_160_chars_moderation_fail(self):
        item = CreativeItem(
            platform=PlatformEnum.TELEGRAM_ADSLY,
            format=AdFormatEnum.TELEGRAM_ADS_TEXT,
            body_text="A" * 161,
            raw_destination_url="https://example.com",
            utm_tagged_url="https://example.com?utm_source=telegram_ads&utm_medium=cpm&utm_campaign=c1&utm_content=v1",
        )
        assert item.moderation_passed is False
        assert any("exceeds 160 chars" in flag for flag in item.moderation_flags)

    def test_telegram_ads_raw_url_moderation_fail(self):
        item = CreativeItem(
            platform=PlatformEnum.TELEGRAM_ADSLY,
            format=AdFormatEnum.TELEGRAM_ADS_TEXT,
            body_text="Check out https://mywebsite.com for great deals!",
            raw_destination_url="https://example.com",
            utm_tagged_url="https://example.com?utm_source=telegram_ads&utm_medium=cpm&utm_campaign=c1&utm_content=v1",
        )
        assert item.moderation_passed is False
        assert any("Raw external links" in flag for flag in item.moderation_flags)

    def test_richads_push_character_caps(self):
        item = CreativeItem(
            platform=PlatformEnum.RICHADS,
            format=AdFormatEnum.PUSH_BANNER,
            headline="T" * 31,
            body_text="B" * 50,
            raw_destination_url="https://example.com",
            utm_tagged_url="https://example.com?utm_source=richads&utm_medium=push&utm_campaign=c1&utm_content=v1",
        )
        assert item.moderation_passed is False
        assert any("headline exceeds 30" in flag for flag in item.moderation_flags)
        assert any("body exceeds 45" in flag for flag in item.moderation_flags)

    def test_valid_creative_passes_moderation(self):
        item = CreativeItem(
            platform=PlatformEnum.TELEGRAM_ADSLY,
            format=AdFormatEnum.TELEGRAM_ADS_TEXT,
            body_text="Join our fitness community @fit_bot today and start training!",
            raw_destination_url="https://t.me/fit_bot",
            utm_tagged_url="https://t.me/fit_bot?utm_source=telegram_ads&utm_medium=cpm&utm_campaign=fit_q4&utm_content=v1",
        )
        assert item.moderation_passed is True
        assert len(item.moderation_flags) == 0


class TestPerformanceMetricsGuardrails:
    def test_kill_switch_spend_1_5x_target_cpa_zero_conversions(self):
        metrics = PerformanceMetrics(
            spend=150.0,
            target_cpa=100.0,
            conversions=0,
        )
        assert metrics.guardrail_triggered is True
        assert metrics.guardrail_action == "KILL_SWITCH"
        assert "Kill-switch triggered" in metrics.notes

    def test_kill_switch_not_triggered_below_threshold(self):
        metrics = PerformanceMetrics(
            spend=149.0,
            target_cpa=100.0,
            conversions=0,
        )
        assert metrics.guardrail_triggered is False
        assert metrics.guardrail_action is None

    def test_kill_switch_not_triggered_with_conversions(self):
        metrics = PerformanceMetrics(
            spend=200.0,
            target_cpa=100.0,
            conversions=2,
        )
        assert metrics.guardrail_triggered is False
        assert metrics.cpa == 100.0

    def test_creative_fatigue_threshold(self):
        metrics = PerformanceMetrics(frequency=2.85)
        assert metrics.guardrail_triggered is True
        assert metrics.guardrail_action == "FATIGUE_ALERT"

    def test_learning_phase_50_events(self):
        metrics = PerformanceMetrics(optimization_events_count=52)
        assert metrics.learning_phase_status == "COMPLETED"


class TestCampaignStateLifecycleAndHardGate:
    def test_default_state_initialization(self):
        state = CampaignState()
        assert state.status == CampaignStatus.INTAKE
        assert state.campaign_id.startswith("cmp_")
        assert len(state.creatives) == 0

    def test_legal_state_transitions(self):
        state = CampaignState()
        state.transition_to(CampaignStatus.PLANNING)
        assert state.status == CampaignStatus.PLANNING
        state.transition_to(CampaignStatus.AWAITING_APPROVAL)
        assert state.status == CampaignStatus.AWAITING_APPROVAL

    def test_hard_gate_blocks_live_when_payment_unverified(self):
        state = CampaignState(
            status=CampaignStatus.AWAITING_APPROVAL,
            financials=Financials(gross_budget=1000.0, payment_verified=False),
        )
        with pytest.raises(PaymentVerificationError):
            state.transition_to(CampaignStatus.LIVE)

    def test_hard_gate_allows_live_when_payment_verified(self):
        state = CampaignState(
            status=CampaignStatus.AWAITING_APPROVAL,
            financials=Financials(gross_budget=1000.0, payment_verified=True),
        )
        state.transition_to(CampaignStatus.LIVE)
        assert state.status == CampaignStatus.LIVE

    def test_direct_assignment_hard_gate_protection(self):
        state = CampaignState(
            status=CampaignStatus.AWAITING_APPROVAL,
            financials=Financials(gross_budget=1000.0, payment_verified=False),
        )
        with pytest.raises(PaymentVerificationError):
            state.status = CampaignStatus.LIVE

    def test_illegal_jump_raises_invalid_transition(self):
        state = CampaignState(status=CampaignStatus.INTAKE)
        with pytest.raises(InvalidStateTransitionError):
            state.transition_to(CampaignStatus.LIVE)

    def test_json_roundtrip_serialization(self):
        state = CampaignState(
            client_brief=ClientBrief(product="Bot", geo="KZ", goal="LEADS", budget=1000.0),
            financials=Financials(gross_budget=1000.0, payment_verified=False),
        )
        json_data = state.model_dump_json()
        restored = CampaignState.model_validate_json(json_data)
        assert restored.campaign_id == state.campaign_id
        assert restored.client_brief.product == "Bot"
        assert restored.financials.service_commission == 120.0
