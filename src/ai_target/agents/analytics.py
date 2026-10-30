"""
ai_target.agents.analytics
Analytics & Guardrails Agent (Milestone 4 + Full-Funnel Reel Diagnostics & CRM).

Responsibilities:
1. Evaluates campaign telemetry at discrete 2-hour intervals.
2. Tracks Meta Ads learning phase (50 optimization events threshold -> LEARNING vs LEARNING_COMPLETE).
3. Enforces automated Kill-Switch when spend >= 1.5x target CPA with 0 conversions,
   halting CampaignState to PAUSED and pausing active deployments.
4. Detects Creative Fatigue when impression frequency > 2.80, raising FATIGUE_ALERT.
5. Smoothly adjusts TON CPM bids for Adsly.Pro based on competition index and CPA performance,
   strictly clamped within [0.10, 5.00] TON.
6. Evaluates individual Reels / creatives (`ReelCreativeMetrics`), automatically pausing underperforming
   Reels (`status="PAUSED"`), diagnosing root causes (`why_low_conversion`) across Hook -> Click ->
   Message/Lead -> Sale, and generating actionable recommendations (`PENDING_USER_DECISION`) for a
   1–2 person marketing team while tracking how many people messaged (`messages_received`) and
   how many bought (`sales_count`).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Union

from ai_target.state.models import (
    CampaignState,
    CampaignStatus,
    OptimizationRecommendation,
    PerformanceMetrics,
    ReelCreativeMetrics,
)


KILL_SWITCH_CPA_MULTIPLIER: float = 1.50
CREATIVE_FATIGUE_FREQUENCY_THRESHOLD: float = 2.80
META_LEARNING_PHASE_EVENTS_THRESHOLD: int = 50
MIN_TON_BID_FLOOR: float = 0.10
MAX_TON_BID_CEILING: float = 5.00
LOW_HOOK_RATE_THRESHOLD: float = 20.0
LOW_CTR_THRESHOLD: float = 1.0
LOW_LEAD_TO_SALE_RATE_THRESHOLD: float = 10.0


def _require_finite_float(val: Any, name: str) -> float:
    if isinstance(val, bool) or val is None:
        raise ValueError(f"{name} must be a valid finite number, got {val!r}.")
    try:
        num = float(val)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric, got {val!r}.") from exc
    if not math.isfinite(num):
        raise ValueError(f"{name} must be finite (not NaN/Inf), got {val!r}.")
    return num


class AnalyticsGuardrailsAgent:
    """
    Autonomous monitoring, Kill-Switch, Creative Fatigue detector,
    per-Reel conversion diagnostician, full-funnel CRM tracker,
    and dynamic TON bidding agent.
    """

    def __init__(self, check_interval_hours: int = 2) -> None:
        self.check_interval_hours = check_interval_hours

    def evaluate_learning_phase(self, conversions: int, hours_elapsed: int = 24) -> str:
        """
        Evaluates Meta Ads learning phase status.
        Requires >= 50 optimization events (conversions) to exit learning phase.
        Returns 'LEARNING_COMPLETE' if conversions >= 50, else 'LEARNING'.
        """
        if isinstance(conversions, bool) or conversions < 0:
            raise ValueError(f"conversions must be a non-negative integer, got {conversions!r}.")
        if int(conversions) >= META_LEARNING_PHASE_EVENTS_THRESHOLD:
            return "LEARNING_COMPLETE"
        return "LEARNING"

    def diagnose_conversion_bottlenecks(
        self,
        metrics: Union[ReelCreativeMetrics, PerformanceMetrics],
    ) -> List[OptimizationRecommendation]:
        """
        Diagnoses *why* conversion is low across the marketing & sales funnel
        (Hook -> Click/CTR -> Lead/Message -> Sale/Close -> Frequency/CPA) and
        generates concrete improvement proposals (`PENDING_USER_DECISION`) so the
        human marketer (1-2 person team) makes the final decision.
        """
        target_id = getattr(metrics, "creative_id", None) or "campaign"
        reasons: List[str] = []
        proposals: List[str] = []
        recommendations_objs: List[OptimizationRecommendation] = []

        impressions = getattr(metrics, "impressions", 0) or 0
        clicks = getattr(metrics, "clicks", 0) or 0
        three_sec_views = getattr(metrics, "three_sec_views", 0) or 0
        avg_watch_time = getattr(metrics, "avg_watch_time_sec", 0.0) or 0.0
        hook_rate = getattr(metrics, "hook_rate", 0.0) or 0.0
        ctr = getattr(metrics, "ctr", 0.0) or 0.0
        conversions = getattr(metrics, "conversions", 0) or 0
        conversion_rate = getattr(metrics, "conversion_rate", 0.0) or 0.0
        target_conv_rate = getattr(metrics, "target_conversion_rate", 1.0)
        messages_received = getattr(metrics, "messages_received", 0) or 0
        sales_count = getattr(metrics, "sales_count", 0) or 0
        lead_to_sale_rate = getattr(metrics, "lead_to_sale_rate", 0.0) or 0.0
        spend = getattr(metrics, "spend", 0.0) or 0.0
        target_cpa = getattr(metrics, "target_cpa", 10.0) or 10.0
        cpa = getattr(metrics, "cpa", 0.0) or 0.0
        frequency = getattr(metrics, "frequency", 1.0) or 1.0

        # 1. Weak Visual Hook (First 3 Seconds of Reel)
        if (hook_rate > 0.0 and hook_rate < LOW_HOOK_RATE_THRESHOLD) or (
            impressions >= 500 and three_sec_views > 0 and (three_sec_views / impressions * 100.0) < LOW_HOOK_RATE_THRESHOLD
        ) or (0.0 < avg_watch_time < 3.0):
            eff_hook = hook_rate if hook_rate > 0 else round((three_sec_views / impressions) * 100.0, 2) if impressions > 0 else 0.0
            why = (
                f"Слабый хук в первые 3 секунды рилса (Low Hook Rate: {eff_hook}% < {LOW_HOOK_RATE_THRESHOLD}%, "
                f"среднее время просмотра {avg_watch_time} сек) — аудитория пролистывает видео в самом начале."
            )
            prop = (
                "Предложение (решение за вами): Заменить первые 3 секунды рилса на динамичный визуальный хук "
                "с крупным заголовком проблемы/результата и протестировать Вариант B."
            )
            reasons.append(why)
            proposals.append(prop)
            recommendations_objs.append(
                OptimizationRecommendation(
                    target_id=target_id,
                    category="CREATIVE_HOOK",
                    bottleneck_stage="HOOK",
                    why_low_conversion=why,
                    proposed_change=prop,
                    decision_status="PENDING_USER_DECISION",
                )
            )

        # 2. Low CTR / Weak Offer or Call-To-Action
        if impressions >= 100 and (ctr < LOW_CTR_THRESHOLD or clicks == 0):
            eff_ctr = ctr if ctr > 0 else round((clicks / impressions) * 100.0, 2)
            why = (
                f"Низкий CTR ({eff_ctr}% < {LOW_CTR_THRESHOLD}% при {impressions} показах и {clicks} кликах) — "
                f"слабый оффер в видео или непонятный призыв к действию (CTA)."
            )
            prop = (
                "Предложение (решение за вами): Усилить оффер (добавить конкретную выгоду/бонус за переход) "
                "и добавить заметный текстовый призыв к действию (CTA) в концовку рилса."
            )
            reasons.append(why)
            proposals.append(prop)
            recommendations_objs.append(
                OptimizationRecommendation(
                    target_id=target_id,
                    category="OFFER_HEADLINE",
                    bottleneck_stage="CLICK",
                    why_low_conversion=why,
                    proposed_change=prop,
                    decision_status="PENDING_USER_DECISION",
                )
            )

        # 3. High/Moderate Clicks, Low Leads/Messages (Landing page / Telegram Bot onboarding drop-off)
        eff_conv_rate = conversion_rate if conversion_rate > 0 else (round((conversions / clicks) * 100.0, 2) if clicks > 0 else 0.0)
        if clicks >= 20 and (eff_conv_rate < target_conv_rate or (messages_received == 0 and conversions == 0)):
            why = (
                f"Низкая конверсия из клика в обращение/лид ({eff_conv_rate}% при {clicks} кликах, "
                f"написали: {messages_received}) — несовпадение обещания в рилсе с посадочной страницей/ботом "
                f"или слишком сложный первый шаг."
            )
            prop = (
                "Предложение (решение за вами): Синхронизировать первое сообщение в боте/директе или заголовок лендинга "
                "с оффером из рилса и добавить кнопки быстрого ответа в 1 клик."
            )
            reasons.append(why)
            proposals.append(prop)
            recommendations_objs.append(
                OptimizationRecommendation(
                    target_id=target_id,
                    category="LANDING_BOT_FLOW",
                    bottleneck_stage="LEAD_MESSAGE",
                    why_low_conversion=why,
                    proposed_change=prop,
                    decision_status="PENDING_USER_DECISION",
                )
            )

        # 4. Many People Messaged (`messages_received`), Few Bought (`sales_count`) -> Sales Script / CRM Bottleneck
        eff_l2s = lead_to_sale_rate if lead_to_sale_rate > 0 else (
            round((sales_count / messages_received) * 100.0, 2) if messages_received > 0 else 0.0
        )
        if messages_received >= 5 and eff_l2s < LOW_LEAD_TO_SALE_RATE_THRESHOLD:
            why = (
                f"Низкая конверсия из переписки в продажу ({eff_l2s}%: написали {messages_received} чел., "
                f"купили {sales_count}) — узкое место в отделе продаж/переписке: долгий ответ, слабый скрипт продаж "
                f"или неотработанные возражения по цене."
            )
            prop = (
                "Предложение (решение за вами): Включить мгновенный авто-ответ/квалификацию за 60 секунд, "
                "обновить скрипт продаж (добавить кейсы/отзывы) и запустить авторассылку дожима по тем, кто написал, но не купил."
            )
            reasons.append(why)
            proposals.append(prop)
            recommendations_objs.append(
                OptimizationRecommendation(
                    target_id=target_id,
                    category="SALES_SCRIPT",
                    bottleneck_stage="SALE_CLOSE",
                    why_low_conversion=why,
                    proposed_change=prop,
                    decision_status="PENDING_USER_DECISION",
                )
            )

        # 5. High CPA / Budget Bleed
        if spend >= target_cpa and (cpa > target_cpa * 1.2 or (conversions == 0 and messages_received == 0 and sales_count == 0)):
            why = (
                f"Превышен порог стоимости результата (CPA {cpa} USDT при целевом CPA {target_cpa} USDT, "
                f"расход {spend} USDT, конверсий {conversions}) — связка креатив-аудитория не окупается."
            )
            prop = (
                "Предложение (решение за вами): Оставить этот рилс отключенным и перераспределить его дневной бюджет "
                "на креативы с лучшей конверсией или сузить таргетинг на более теплый сегмент."
            )
            reasons.append(why)
            proposals.append(prop)
            recommendations_objs.append(
                OptimizationRecommendation(
                    target_id=target_id,
                    category="BUDGET_REALLOCATION",
                    bottleneck_stage="CPA_EFFICIENCY",
                    why_low_conversion=why,
                    proposed_change=prop,
                    decision_status="PENDING_USER_DECISION",
                )
            )

        # 6. High Frequency / Audience Fatigue
        if frequency > CREATIVE_FATIGUE_FREQUENCY_THRESHOLD:
            why = (
                f"Выгорание аудитории (Frequency {frequency} > {CREATIVE_FATIGUE_FREQUENCY_THRESHOLD}) — "
                f"одни и те же пользователи видят рилс слишком часто, из-за чего конверсия падает."
            )
            prop = (
                "Предложение (решение за вами): Запустить свежий вариант креатива (Variant B/C) с новым визуальным углом "
                "и расширить географию/интересы аудитории."
            )
            reasons.append(why)
            proposals.append(prop)
            recommendations_objs.append(
                OptimizationRecommendation(
                    target_id=target_id,
                    category="AUDIENCE_FATIGUE",
                    bottleneck_stage="FREQUENCY",
                    why_low_conversion=why,
                    proposed_change=prop,
                    decision_status="PENDING_USER_DECISION",
                )
            )

        metrics.why_low_conversion = reasons
        metrics.recommendations = proposals
        return recommendations_objs

    def evaluate_reel_metrics(self, reel: ReelCreativeMetrics) -> Optional[str]:
        """
        Evaluates an individual Reel / creative (`ReelCreativeMetrics`):
        - Recomputes funnel metrics (hook_rate, ctr, conversion_rate, cpa, lead_to_sale_rate, cost_per_message, cost_per_sale).
        - If conversion is low or CPA is too high, automatically pauses the Reel (`status="PAUSED"`, `auto_paused=True`)
          and populates root-cause diagnostics (`why_low_conversion`) and recommendations (`recommendations`).
        Returns 'PAUSE_REEL', 'RECOMMEND_OPTIMIZATION', or None.
        """
        # Recompute derived metrics via model validator without polluting model_fields_set
        reel.compute_reel_funnel_metrics()
        if reel.reach > 0 and reel.impressions > 0 and ("frequency" not in reel.model_fields_set or reel.frequency == 1.0):
            object.__setattr__(reel, "frequency", round(reel.impressions / reel.reach, 2))

        # Check auto-pause conditions for low conversion on this Reel
        zero_conv_bleed = (
            reel.conversions == 0
            and reel.messages_received == 0
            and reel.sales_count == 0
            and reel.target_cpa > 0
            and round(reel.spend, 4) >= round(reel.target_cpa, 4)
        )
        low_conv_rate_bleed = (
            (reel.clicks >= 20 or round(reel.spend, 4) >= round(reel.target_cpa, 4))
            and reel.conversion_rate < reel.target_conversion_rate
            and (reel.cpa > reel.target_cpa or reel.conversions == 0)
        )
        high_cpa_bleed = (
            reel.target_cpa > 0
            and round(reel.spend, 4) >= round(KILL_SWITCH_CPA_MULTIPLIER * reel.target_cpa, 4)
            and round(reel.cpa, 4) >= round(KILL_SWITCH_CPA_MULTIPLIER * reel.target_cpa, 4)
        )
        low_hook_and_ctr_bleed = (
            reel.impressions >= 500
            and round(reel.spend, 4) >= round(0.5 * reel.target_cpa, 4)
            and (0.0 < reel.hook_rate < LOW_HOOK_RATE_THRESHOLD or reel.ctr < LOW_CTR_THRESHOLD)
            and reel.conversion_rate < reel.target_conversion_rate
        )

        if zero_conv_bleed or low_conv_rate_bleed or high_cpa_bleed or low_hook_and_ctr_bleed:
            reel.status = "PAUSED"
            reel.auto_paused = True
            self.diagnose_conversion_bottlenecks(reel)
            if not reel.why_low_conversion:
                fallback_why = (
                    f"Низкая конверсия рилса '{reel.creative_id}' (конверсия {reel.conversion_rate}%, "
                    f"CPA {reel.cpa} USDT > цели {reel.target_cpa} USDT, написали {reel.messages_received}, "
                    f"купили {reel.sales_count})."
                )
                fallback_prop = (
                    "Предложение (решение за вами): Заменить хук первых 3 секунд и оффер рилса или перенести бюджет на лучший креатив."
                )
                reel.why_low_conversion = [fallback_why]
                reel.recommendations = [fallback_prop]
            reel.pause_reason = (
                f"Auto-paused Reel '{reel.creative_id}': low conversion ({reel.conversion_rate}%, "
                f"CPA={reel.cpa} vs target={reel.target_cpa}, messages={reel.messages_received}, sales={reel.sales_count}). "
                f"Reason: {reel.why_low_conversion[0]}"
            )
            return "PAUSE_REEL"

        # If Reel is currently ACTIVE and no longer triggers auto-pause, clear stale auto_paused / pause_reason flags
        if reel.status == "ACTIVE" and (reel.auto_paused or reel.pause_reason is not None):
            reel.auto_paused = False
            reel.pause_reason = None

        # Check if there are CRM / sales-script or fatigue bottlenecks even if the Reel itself brings cheap leads
        recs = self.diagnose_conversion_bottlenecks(reel)
        if recs:
            return "RECOMMEND_OPTIMIZATION"

        return None

    def analyze_and_pause_underperforming_reels(
        self,
        state: CampaignState,
    ) -> List[OptimizationRecommendation]:
        """
        Inspects all per-Reel telemetry items in `state.reel_metrics`:
        1. Automatically pauses any Reel with low conversion (`reel.status = 'PAUSED'`, `reel.auto_paused = True`)
           and updates the corresponding `CreativeItem.status = 'PAUSED'` in `state.creatives`.
        2. Diagnoses *why* conversion is low (`why_low_conversion`) and generates actionable proposals
           (`OptimizationRecommendation` with `decision_status='PENDING_USER_DECISION'`) stored in
           `state.pending_recommendations` so the final decision remains with the human marketer.
        """
        new_recommendations: List[OptimizationRecommendation] = []
        existing_pending_keys = {
            (r.target_id, r.category, r.bottleneck_stage)
            for r in state.pending_recommendations
            if r.decision_status == "PENDING_USER_DECISION"
        }
        existing_decided_keys = {
            (r.target_id, r.category, r.bottleneck_stage, r.why_low_conversion)
            for r in state.pending_recommendations
            if r.decision_status != "PENDING_USER_DECISION"
        }

        already_audited_paused_ids = {
            e.get("details", {}).get("creative_id")
            for e in state.audit_trail
            if e.get("action") == "REEL_AUTO_PAUSED"
        }

        for reel in state.reel_metrics:
            action = self.evaluate_reel_metrics(reel)
            recs = self.diagnose_conversion_bottlenecks(reel)

            if action == "PAUSE_REEL":
                # Also pause the matching creative item in state.creatives
                for cr in state.creatives:
                    if cr.creative_id == reel.creative_id:
                        cr.status = "PAUSED"

                # If a deployment specifically runs this creative_id, pause its ad payload status
                for dep in state.live_deployments:
                    if not isinstance(dep.raw_payload, dict) or not isinstance(dep.raw_payload.get("ad"), dict):
                        continue
                    ad_dict = dep.raw_payload["ad"]
                    plat_str = str(getattr(dep.platform, "value", dep.platform)).lower()
                    ad_cr_id = (
                        ad_dict.get("creative", {}).get("creative_id")
                        if isinstance(ad_dict.get("creative"), dict)
                        else None
                    )
                    if ad_cr_id == reel.creative_id:
                        if "tiktok" in plat_str:
                            ad_dict["operation_status"] = "DISABLE"
                            ad_dict["status"] = "PAUSED"
                        else:
                            ad_dict["status"] = "PAUSED"

                    if isinstance(ad_dict.get("creatives"), list):
                        for cr_entry in ad_dict["creatives"]:
                            if isinstance(cr_entry, dict) and cr_entry.get("creative_id") == reel.creative_id:
                                if "tiktok" in plat_str:
                                    cr_entry["operation_status"] = "DISABLE"
                                    cr_entry["status"] = "PAUSED"
                                else:
                                    cr_entry["status"] = "PAUSED"

                if not recs:
                    recs = [
                        OptimizationRecommendation(
                            target_id=reel.creative_id,
                            category="CREATIVE_HOOK",
                            bottleneck_stage="HOOK",
                            why_low_conversion=reel.why_low_conversion[0]
                            if reel.why_low_conversion
                            else f"Low conversion on Reel {reel.creative_id}",
                            proposed_change=reel.recommendations[0]
                            if reel.recommendations
                            else "Replace Reel hook/offer or reallocate budget to winning creative.",
                            decision_status="PENDING_USER_DECISION",
                        )
                    ]

                if reel.creative_id not in already_audited_paused_ids:
                    state.record_audit_event(
                        agent="AnalyticsGuardrailsAgent",
                        action="REEL_AUTO_PAUSED",
                        details={
                            "creative_id": reel.creative_id,
                            "creative_name": reel.creative_name,
                            "status": reel.status,
                            "spend": reel.spend,
                            "impressions": reel.impressions,
                            "clicks": reel.clicks,
                            "conversion_rate": reel.conversion_rate,
                            "messages_received": reel.messages_received,
                            "sales_count": reel.sales_count,
                            "cpa": reel.cpa,
                            "target_cpa": reel.target_cpa,
                            "why_low_conversion": list(reel.why_low_conversion),
                            "recommendations": list(reel.recommendations),
                            "decision_mode": "PENDING_USER_DECISION",
                        },
                    )
                    already_audited_paused_ids.add(reel.creative_id)
            elif reel.status == "ACTIVE":
                # Sync re-enabled active Reel status back to state.creatives
                for cr in state.creatives:
                    if cr.creative_id == reel.creative_id and cr.status == "PAUSED":
                        cr.status = "ACTIVE"

            for rec in recs:
                pending_key = (rec.target_id, rec.category, rec.bottleneck_stage)
                decided_key = (rec.target_id, rec.category, rec.bottleneck_stage, rec.why_low_conversion)
                if pending_key not in existing_pending_keys and decided_key not in existing_decided_keys:
                    state.pending_recommendations.append(rec)
                    existing_pending_keys.add(pending_key)
                    new_recommendations.append(rec)

        return new_recommendations

    def evaluate_metrics(self, metrics: PerformanceMetrics) -> Optional[str]:
        """
        Evaluates a single PerformanceMetrics snapshot in-place and returns the guardrail action
        ('KILL_SWITCH', 'FATIGUE_ALERT', or None).
        """
        # Recompute derived funnel and CRM metrics without polluting model_fields_set
        metrics.evaluate_telemetry_guardrails()

        # Check frequency if reach & impressions are provided and frequency was not explicitly set
        reach = getattr(metrics, "reach", 0) or 0
        if reach > 0 and metrics.impressions > 0 and ("frequency" not in metrics.model_fields_set or metrics.frequency == 1.0):
            object.__setattr__(metrics, "frequency", round(metrics.impressions / reach, 2))

        # Learning phase status
        if metrics.conversions >= META_LEARNING_PHASE_EVENTS_THRESHOLD or metrics.optimization_events_count >= META_LEARNING_PHASE_EVENTS_THRESHOLD:
            object.__setattr__(metrics, "learning_phase_status", "LEARNING_COMPLETE")
        else:
            object.__setattr__(metrics, "learning_phase_status", "LEARNING")

        # Populate diagnostic reasons & recommendations if any funnel stage is weak
        self.diagnose_conversion_bottlenecks(metrics)

        # Guardrail 1: Kill-Switch (spend >= 1.50x target_cpa with 0 conversions)
        if (
            metrics.conversions == 0
            and metrics.target_cpa > 0
            and round(metrics.spend, 4) >= round(KILL_SWITCH_CPA_MULTIPLIER * metrics.target_cpa, 4)
        ):
            object.__setattr__(metrics, "guardrail_triggered", True)
            object.__setattr__(metrics, "guardrail_action", "KILL_SWITCH")
            note_msg = (
                f"Kill-switch triggered: spend {metrics.spend} >= "
                f"1.5x target CPA ({metrics.target_cpa}) with 0 conversions."
            )
            if metrics.frequency > CREATIVE_FATIGUE_FREQUENCY_THRESHOLD:
                note_msg += (
                    f" Concurrent creative fatigue detected: frequency {metrics.frequency} > "
                    f"{CREATIVE_FATIGUE_FREQUENCY_THRESHOLD}."
                )
            object.__setattr__(metrics, "notes", note_msg)
            return "KILL_SWITCH"

        # Guardrail 2: Creative Fatigue (frequency > 2.80 strictly)
        if metrics.frequency > CREATIVE_FATIGUE_FREQUENCY_THRESHOLD:
            object.__setattr__(metrics, "guardrail_triggered", True)
            object.__setattr__(metrics, "guardrail_action", "FATIGUE_ALERT")
            object.__setattr__(
                metrics,
                "notes",
                (
                    f"Creative fatigue detected: frequency {metrics.frequency} > "
                    f"{CREATIVE_FATIGUE_FREQUENCY_THRESHOLD}."
                ),
            )
            return "FATIGUE_ALERT"

        object.__setattr__(metrics, "guardrail_triggered", False)
        object.__setattr__(metrics, "guardrail_action", None)
        return None

    def calculate_dynamic_ton_bid(
        self,
        current_cpm: float,
        competition_index: float = 0.5,
        target_cpa: float = 1.0,
        realized_cpa: float = 1.0,
    ) -> float:
        """
        Smoothly adjusts TON CPM bid based on auction competition index [0.0, 1.0]
        and CPA efficiency (target_cpa / realized_cpa), strictly clamped to [0.10, 5.00] TON.
        """
        cpm_val = _require_finite_float(current_cpm, "current_cpm")
        comp_val = _require_finite_float(competition_index, "competition_index")
        target_val = _require_finite_float(target_cpa, "target_cpa")
        realized_val = _require_finite_float(realized_cpa, "realized_cpa")

        if cpm_val <= 0:
            raise ValueError(f"current_cpm must be strictly positive, got {current_cpm}.")

        clamped_comp = max(0.0, min(1.0, comp_val))
        base_cpm = max(MIN_TON_BID_FLOOR, cpm_val)
        comp_factor = 1.0 + (clamped_comp - 0.5) * 0.40

        if realized_val > 0 and target_val > 0:
            efficiency_ratio = target_val / realized_val
            # Dampen efficiency factor to keep bid adjustments smooth (0.75x to 1.35x)
            eff_factor = max(0.75, min(1.35, 0.5 + 0.5 * efficiency_ratio))
        else:
            eff_factor = 1.0

        adjusted = base_cpm * comp_factor * eff_factor
        clamped = max(MIN_TON_BID_FLOOR, min(MAX_TON_BID_CEILING, round(adjusted, 4)))
        return clamped

    def _register_campaign_recommendations(
        self,
        state: CampaignState,
        metrics: PerformanceMetrics,
    ) -> None:
        existing_pending_keys = {
            (r.target_id, r.category, r.bottleneck_stage)
            for r in state.pending_recommendations
            if r.decision_status == "PENDING_USER_DECISION"
        }
        existing_decided_keys = {
            (r.target_id, r.category, r.bottleneck_stage, r.why_low_conversion)
            for r in state.pending_recommendations
            if r.decision_status != "PENDING_USER_DECISION"
        }
        for rec in self.diagnose_conversion_bottlenecks(metrics):
            pending_key = (rec.target_id, rec.category, rec.bottleneck_stage)
            decided_key = (rec.target_id, rec.category, rec.bottleneck_stage, rec.why_low_conversion)
            if pending_key not in existing_pending_keys and decided_key not in existing_decided_keys:
                state.pending_recommendations.append(rec)
                existing_pending_keys.add(pending_key)

    def apply_guardrails(self, state: CampaignState) -> CampaignState:
        """
        Inspects the latest performance metrics and per-Reel telemetry on CampaignState,
        evaluates guardrails, auto-pauses underperforming Reels, records root-cause diagnostics
        & recommendations (`PENDING_USER_DECISION`), and dispatches campaign-level state transitions.
        """
        if state.reel_metrics:
            self.analyze_and_pause_underperforming_reels(state)

        if not state.performance_metrics:
            return state

        latest = state.performance_metrics[-1]
        action = self.evaluate_metrics(latest)
        self._register_campaign_recommendations(state, latest)

        if action == "KILL_SWITCH":
            # Transition campaign to PAUSED if currently active
            if state.status in (CampaignStatus.LIVE, CampaignStatus.OPTIMIZING):
                state.transition_to(CampaignStatus.PAUSED)
            else:
                state.status = CampaignStatus.PAUSED

            # Pause all live deployments
            for dep in state.live_deployments:
                if str(getattr(dep.platform, "value", dep.platform)).lower() == "tiktok":
                    dep.status = "DISABLE"
                else:
                    dep.status = "PAUSED"

            state.record_audit_event(
                agent="AnalyticsGuardrailsAgent",
                action="KILL_SWITCH_TRIGGERED",
                details={
                    "spend": latest.spend,
                    "target_cpa": latest.target_cpa,
                    "conversions": latest.conversions,
                    "messages_received": latest.messages_received,
                    "sales_count": latest.sales_count,
                    "frequency": latest.frequency,
                    "fatigue_also_detected": latest.frequency > CREATIVE_FATIGUE_FREQUENCY_THRESHOLD,
                    "why_low_conversion": list(latest.why_low_conversion),
                    "recommendations": list(latest.recommendations),
                    "new_status": state.status.value,
                },
            )

        elif action == "FATIGUE_ALERT":
            state.record_audit_event(
                agent="AnalyticsGuardrailsAgent",
                action="FATIGUE_ALERT_RAISED",
                details={
                    "frequency": latest.frequency,
                    "threshold": CREATIVE_FATIGUE_FREQUENCY_THRESHOLD,
                    "why_low_conversion": list(latest.why_low_conversion),
                    "recommendations": list(latest.recommendations),
                },
            )

        return state

    def generate_funnel_report(self, state: CampaignState) -> Dict[str, Any]:
        """
        Generates a comprehensive '1-2 Person Marketing Team' executive dashboard & CRM funnel report:
        - Shows full funnel: Spend -> Impressions -> Clicks -> How many people wrote (`messages_received`) -> How many bought (`sales_count`) -> Revenue & ROAS.
        - Lists which Reels are active vs auto-paused (`paused_reels`).
        - Explains *why* conversion was low (`why_low_conversion`).
        - Lists actionable recommendations awaiting the marketer's decision (`PENDING_USER_DECISION`).
        """
        if state.reel_metrics:
            self.analyze_and_pause_underperforming_reels(state)

        if state.performance_metrics:
            latest_pm = state.performance_metrics[-1]
            self.evaluate_metrics(latest_pm)
            self._register_campaign_recommendations(state, latest_pm)

        # Aggregate totals from reel_metrics if present, or fall back to latest performance_metrics
        if state.reel_metrics:
            total_spend = round(sum(r.spend for r in state.reel_metrics), 2)
            total_impressions = sum(r.impressions for r in state.reel_metrics)
            total_clicks = sum(r.clicks for r in state.reel_metrics)
            messages_received = sum(r.messages_received for r in state.reel_metrics)
            sales_count = sum(r.sales_count for r in state.reel_metrics)
            total_conversions = sum(r.conversions for r in state.reel_metrics)
            total_revenue = round(sum(r.revenue for r in state.reel_metrics), 2)
        elif state.performance_metrics:
            latest = state.performance_metrics[-1]
            total_spend = round(latest.spend, 2)
            total_impressions = latest.impressions
            total_clicks = latest.clicks
            messages_received = latest.messages_received
            sales_count = latest.sales_count
            total_conversions = latest.conversions
            total_revenue = round(latest.revenue, 2)
        else:
            total_spend = 0.0
            total_impressions = 0
            total_clicks = 0
            messages_received = 0
            sales_count = 0
            total_conversions = 0
            total_revenue = 0.0

        # If campaign-level performance_metrics also has higher CRM counts (e.g. tracked at campaign level), take the max
        if state.performance_metrics:
            latest = state.performance_metrics[-1]
            messages_received = max(messages_received, latest.messages_received)
            sales_count = max(sales_count, latest.sales_count)
            total_revenue = max(total_revenue, round(latest.revenue, 2))
            if total_spend == 0.0:
                total_spend = round(latest.spend, 2)
            if total_impressions == 0:
                total_impressions = latest.impressions
            if total_clicks == 0:
                total_clicks = latest.clicks

        ctr = round((total_clicks / total_impressions) * 100.0, 2) if total_impressions > 0 else 0.0
        click_to_message_rate = round((messages_received / total_clicks) * 100.0, 2) if total_clicks > 0 else 0.0
        lead_to_sale_rate = round((sales_count / messages_received) * 100.0, 2) if messages_received > 0 else 0.0
        cost_per_message = round(total_spend / messages_received, 2) if messages_received > 0 else round(total_spend, 2)
        cost_per_sale = round(total_spend / sales_count, 2) if sales_count > 0 else round(total_spend, 2)
        roas = round(total_revenue / total_spend, 2) if total_spend > 0 and total_revenue > 0 else 0.0

        active_reels = [r.creative_id for r in state.reel_metrics if r.status == "ACTIVE"]
        paused_reels = [
            {
                "creative_id": r.creative_id,
                "creative_name": r.creative_name or r.creative_id,
                "status": r.status,
                "auto_paused": r.auto_paused,
                "spend": r.spend,
                "impressions": r.impressions,
                "hook_rate": r.hook_rate,
                "clicks": r.clicks,
                "ctr": r.ctr,
                "conversion_rate": r.conversion_rate,
                "messages_received": r.messages_received,
                "sales_count": r.sales_count,
                "cpa": r.cpa,
                "target_cpa": r.target_cpa,
                "pause_reason": r.pause_reason,
                "why_low_conversion": list(r.why_low_conversion),
                "recommendations": list(r.recommendations),
            }
            for r in state.reel_metrics
            if r.status == "PAUSED"
        ]

        all_reasons: List[str] = []
        for r in state.reel_metrics:
            for reason in r.why_low_conversion:
                if reason not in all_reasons:
                    all_reasons.append(reason)
        if state.performance_metrics:
            for reason in state.performance_metrics[-1].why_low_conversion:
                if reason not in all_reasons:
                    all_reasons.append(reason)

        pending_recs = [
            {
                "recommendation_id": rec.recommendation_id,
                "target_id": rec.target_id,
                "category": rec.category,
                "bottleneck_stage": rec.bottleneck_stage,
                "why_low_conversion": rec.why_low_conversion,
                "proposed_change": rec.proposed_change,
                "decision_status": rec.decision_status,
            }
            for rec in state.pending_recommendations
            if rec.decision_status == "PENDING_USER_DECISION"
        ]

        summary_lines = [
            f"=== ОТЧЕТ ИИ-МАРКЕТОЛОГА (Кампания {state.campaign_id} | Статус: {state.status.value}) ===",
            f"Воронка продаж (Full Funnel): Потрачено: {total_spend} USDT | Показы: {total_impressions} | "
            f"Клики: {total_clicks} (CTR {ctr}%) | Написали (Лиды): {messages_received} "
            f"(Цена обращения: {cost_per_message} USDT) | Купили (Продажи): {sales_count} "
            f"(Конверсия в продажу: {lead_to_sale_rate}%, CAC: {cost_per_sale} USDT) | "
            f"Выручка: {total_revenue} USDT (ROAS: {roas}x)",
            f"Рилсы / Креативы: Активных: {len(active_reels)} | Авто-отключено (PAUSED): {len(paused_reels)}",
        ]
        for pr in paused_reels:
            reasons_str = "; ".join(pr["why_low_conversion"]) if pr["why_low_conversion"] else pr["pause_reason"]
            summary_lines.append(
                f"  [-] Отключен рилс '{pr['creative_id']}' (расход {pr['spend']} USDT, написали: {pr['messages_received']}, "
                f"купили: {pr['sales_count']}): {reasons_str}"
            )
        if pending_recs:
            summary_lines.append(f"Рекомендации на утверждение маркетолога (Решение за вами: {len(pending_recs)} шт.):")
            for rec in pending_recs:
                summary_lines.append(
                    f"  [?] [{rec['recommendation_id']}] ({rec['target_id']} / {rec['bottleneck_stage']}): "
                    f"{rec['proposed_change']} [Статус: {rec['decision_status']}]"
                )

        return {
            "campaign_id": state.campaign_id,
            "campaign_status": state.status.value,
            "total_spend": total_spend,
            "total_impressions": total_impressions,
            "total_clicks": total_clicks,
            "ctr": ctr,
            "total_conversions": total_conversions,
            "messages_received": messages_received,
            "leads_count": messages_received,
            "sales_count": sales_count,
            "orders_closed": sales_count,
            "click_to_message_rate": click_to_message_rate,
            "lead_to_sale_rate": lead_to_sale_rate,
            "cost_per_message": cost_per_message,
            "cost_per_sale": cost_per_sale,
            "total_revenue": total_revenue,
            "roas": roas,
            "total_reels_evaluated": len(state.reel_metrics),
            "active_reels": active_reels,
            "paused_reels": paused_reels,
            "why_low_conversion": all_reasons,
            "pending_recommendations": pending_recs,
            "summary_text": "\n".join(summary_lines),
        }

