"""
ai_target.agents.supervisor
Supervisor & Intake Orchestrator Agent (Milestone 5).

Responsibilities:
1. Conducts interactive CLI / simulated Telegram bot dialogue with the client to collect
   the 4 mandatory parameters: product, target GEO, campaign goal, and budget.
2. Normalizes arbitrary user goal strings and geographic tokens into canonical representations.
3. Initializes and routes CampaignState across Strategist, Copywriter, Technical Executors,
   and Analytics Guardrails agents.
4. Enforces the uncompromising Payment Verification Hard Gate (payment_verified == True)
   before permitting transition to LIVE.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

from ai_target.adapters.billing_adapter import BillingAggregatorAdapter
from ai_target.agents.analytics import AnalyticsGuardrailsAgent
from ai_target.agents.copywriter import CreativeCopywriterAgent
from ai_target.agents.meta_tiktok import MetaTikTokExecutor
from ai_target.agents.strategist import StrategistBillingAgent
from ai_target.agents.telegram_ecosystem import TelegramEcosystemExecutor
from ai_target.state.models import (
    CampaignState,
    CampaignStatus,
    ClientBrief,
    Financials,
    OptimizationRecommendation,
)


GOAL_SYNONYM_MAP: Dict[str, str] = {
    "lead": "LEADS",
    "leads": "LEADS",
    "leadgen": "LEADS",
    "заявки": "LEADS",
    "лиды": "LEADS",
    "sale": "SALES",
    "sales": "SALES",
    "purchases": "SALES",
    "продажи": "SALES",
    "subscriber": "TELEGRAM_SUBSCRIBERS",
    "subscribers": "TELEGRAM_SUBSCRIBERS",
    "telegram_subscribers": "TELEGRAM_SUBSCRIBERS",
    "подписчики": "TELEGRAM_SUBSCRIBERS",
    "install": "APP_INSTALLS",
    "installs": "APP_INSTALLS",
    "app_installs": "APP_INSTALLS",
    "установки": "APP_INSTALLS",
    "traffic": "TRAFFIC",
    "clicks": "TRAFFIC",
    "трафик": "TRAFFIC",
}

GEO_SYNONYM_MAP: Dict[str, str] = {
    "kazakhstan": "KZ",
    "казахстан": "KZ",
    "kz": "KZ",
    "uzbekistan": "UZ",
    "узбекистан": "UZ",
    "uz": "UZ",
    "dubai": "AE",
    "uae": "AE",
    "united arab emirates": "AE",
    "оаэ": "AE",
    "дубай": "AE",
    "ae": "AE",
    "russia": "RU",
    "россия": "RU",
    "ru": "RU",
    "usa": "US",
    "united states": "US",
    "сша": "US",
    "us": "US",
    "uk": "GB",
    "united kingdom": "GB",
    "великобритания": "GB",
    "gb": "GB",
    "germany": "DE",
    "германия": "DE",
    "de": "DE",
    "france": "FR",
    "франция": "FR",
    "fr": "FR",
    "turkey": "TR",
    "турция": "TR",
    "tr": "TR",
    "armenia": "AM",
    "армения": "AM",
    "am": "AM",
    "georgia": "GE",
    "грузия": "GE",
    "ge": "GE",
    "kyrgyzstan": "KG",
    "кыргызстан": "KG",
    "kg": "KG",
    "belarus": "BY",
    "беларусь": "BY",
    "by": "BY",
    "azerbaijan": "AZ",
    "азербайджан": "AZ",
    "az": "AZ",
    "india": "IN",
    "индия": "IN",
    "in": "IN",
    "indonesia": "ID",
    "индонезия": "ID",
    "id": "ID",
    "brazil": "BR",
    "бразилия": "BR",
    "br": "BR",
    "global": "GLOBAL",
    "worldwide": "GLOBAL",
    "мир": "GLOBAL",
}


def normalize_goal_token(raw_goal: str) -> str:
    """Normalizes varied goal descriptions into canonical objective strings."""
    if not raw_goal or not str(raw_goal).strip():
        raise ValueError("Goal cannot be empty.")
    token = str(raw_goal).strip().lower()
    return GOAL_SYNONYM_MAP.get(token, str(raw_goal).strip().upper())


def normalize_geo_tokens(raw_geos: Union[List[str], str]) -> List[str]:
    """Normalizes country/region names into standard uppercase ISO-2 codes."""
    if isinstance(raw_geos, str):
        items = [x.strip() for x in raw_geos.split(",") if x.strip()]
    else:
        items = [str(x).strip() for x in raw_geos if str(x).strip()]

    if not items:
        raise ValueError("Target GEO list cannot be empty.")

    normalized: List[str] = []
    for item in items:
        code = GEO_SYNONYM_MAP.get(item.lower(), item.upper())
        normalized.append(code)
    return normalized


class CliIntakeHandler:
    """
    Handles CLI / simulated Telegram bot parameter intake for the 4 core client brief fields:
    product_name (product), target_geo (geo), goal, and budget.
    """

    def __init__(self, simulated_inputs: Optional[Dict[str, Any]] = None) -> None:
        self.simulated_inputs = simulated_inputs or {}

    def collect_brief(self) -> ClientBrief:
        """Collects and validates the 4 mandatory client brief parameters into a ClientBrief model."""
        product = self.simulated_inputs.get("product_name") or self.simulated_inputs.get("product") or ""
        raw_geo = self.simulated_inputs.get("target_geo") or self.simulated_inputs.get("geo") or []

        if "goal" in self.simulated_inputs:
            raw_goal = self.simulated_inputs["goal"]
            if raw_goal is None or not str(raw_goal).strip():
                raise ValueError("Goal cannot be empty.")
        else:
            raw_goal = "LEADS"

        raw_budget = self.simulated_inputs.get("budget", 0.0)
        if isinstance(raw_budget, bool):
            raise ValueError("Budget cannot be a boolean.")

        target_geo = normalize_geo_tokens(raw_geo)
        normalized_goal = normalize_goal_token(str(raw_goal))

        return ClientBrief(
            product_name=str(product).strip(),
            target_geo=target_geo,
            goal=normalized_goal,
            budget=float(raw_budget),
            product_description=self.simulated_inputs.get("product_description"),
            target_audience=self.simulated_inputs.get("target_audience"),
        )


class SupervisorAgent:
    """
    Master Supervisor Agent orchestrating the 6-role multi-agent advertising workflow.
    """

    def __init__(self, mode: str = "sandbox") -> None:
        self.mode = mode
        self.strategist = StrategistBillingAgent()
        self.copywriter = CreativeCopywriterAgent()
        self.meta_tiktok_executor = MetaTikTokExecutor(mode=mode)
        self.telegram_executor = TelegramEcosystemExecutor(mode=mode)
        self.analytics = AnalyticsGuardrailsAgent()
        self.billing_adapter = BillingAggregatorAdapter(mode=mode)

    def normalize_goal(self, raw_goal: str) -> str:
        """Normalizes varied goal descriptions into canonical objective strings."""
        return normalize_goal_token(raw_goal)

    def normalize_geo(self, raw_geos: Union[List[str], str]) -> List[str]:
        """Normalizes country/region names into standard uppercase ISO-2 codes."""
        return normalize_geo_tokens(raw_geos)

    def create_campaign(self, brief: ClientBrief) -> CampaignState:
        """Initializes a new CampaignState in INTAKE status with the validated ClientBrief."""
        if brief.goal:
            brief.goal = self.normalize_goal(brief.goal)
        if brief.target_geo:
            brief.target_geo = self.normalize_geo(brief.target_geo)
            brief.geo = ", ".join(brief.target_geo)

        state = CampaignState(
            status=CampaignStatus.INTAKE,
            client_brief=brief,
            financials=self.strategist.calculate_financials(brief.budget),
        )
        state.record_audit_event(
            agent="SupervisorAgent",
            action="CREATE_CAMPAIGN",
            details={
                "product": brief.product_name,
                "geo": brief.target_geo,
                "goal": brief.goal,
                "budget": brief.budget,
            },
        )
        return state

    def start_planning(self, state: CampaignState) -> CampaignState:
        """Transitions CampaignState from INTAKE to PLANNING."""
        state.transition_to(CampaignStatus.PLANNING)
        return state

    def can_launch(self, state: CampaignState) -> Tuple[bool, str]:
        """
        Checks whether the campaign satisfies all prerequisites to transition to LIVE,
        specifically verifying the payment verification hard gate.
        """
        if not state.financials or not state.financials.payment_verified:
            return (
                False,
                f"Launch blocked: payment is not verified (payment_verified=False) for campaign '{state.campaign_id}'.",
            )
        return True, "Payment verified; campaign is eligible to launch."

    def run_planning_and_staging_pipeline(
        self,
        state: CampaignState,
        base_url: str = "https://example.com/offer",
    ) -> CampaignState:
        """
        Executes the full pre-launch subagent pipeline:
        INTAKE -> PLANNING -> Financials & MediaPlan -> Creatives & UTMs -> Sandbox Staging -> AWAITING_APPROVAL.
        """
        if state.status == CampaignStatus.INTAKE:
            self.start_planning(state)

        if not state.financials and state.client_brief:
            state.financials = self.strategist.calculate_financials(state.client_brief.budget)

        if state.financials:
            inv = self.billing_adapter.create_invoice(
                gross_budget=state.financials.gross_budget,
                partner=state.financials.billing_partner,
                currency=state.financials.currency,
            )
            state.record_audit_event(
                agent="BillingAggregatorAdapter",
                action="INVOICE_CREATED",
                details={"invoice_id": inv["invoice_id"], "gross_budget": inv["gross_budget"]},
            )

        state.media_plan = self.strategist.allocate_budget(state)
        self.copywriter.generate_all_campaign_creatives(state=state, base_url=base_url)
        self.meta_tiktok_executor.stage_campaigns(state)
        self.telegram_executor.stage_campaigns(state)

        if state.status == CampaignStatus.PLANNING:
            state.transition_to(CampaignStatus.AWAITING_APPROVAL)

        return state

    def confirm_payment_and_launch(
        self,
        state: CampaignState,
        transaction_hash: str = "tx_verified_sandbox_001",
    ) -> CampaignState:
        """Marks payment as verified via billing webhook and transitions campaign to LIVE."""
        if not state.financials:
            gross = state.client_brief.budget if state.client_brief else 1000.0
            state.financials = Financials(gross_budget=gross)

        webhook_res = self.billing_adapter.simulate_payment_webhook(
            amount_paid=state.financials.gross_budget,
        )
        state.financials.payment_verified = bool(webhook_res["payment_verified"])
        state.financials.payment_reference_id = transaction_hash or webhook_res["transaction_hash"]
        state.financials.payment_verified_at = datetime.now(timezone.utc)

        state.transition_to(CampaignStatus.LIVE)

        for dep in state.live_deployments:
            plat_str = str(getattr(dep.platform, "value", dep.platform)).lower()
            if plat_str == "tiktok":
                dep.status = "ENABLE"
                self.meta_tiktok_executor.tiktok_adapter.update_status(dep.external_campaign_id, "ENABLE")
            elif "meta" in plat_str or "instagram" in plat_str:
                dep.status = "ACTIVE"
                self.meta_tiktok_executor.meta_adapter.update_status(dep.external_campaign_id, "ACTIVE")
            elif "adsgram" in plat_str:
                dep.status = "ACTIVE"
                self.telegram_executor.adsgram_adapter.update_status(dep.external_campaign_id, "ACTIVE")
            else:
                dep.status = "ACTIVE"

        return state

    def evaluate_reels_and_crm(self, state: CampaignState) -> Dict[str, Any]:
        """
        Evaluates all per-Reel metrics and full-funnel CRM stats ('сколько человек написали и сколько продалось'),
        automatically pauses underperforming Reels, diagnoses why conversion is low, generates proposals
        in PENDING_USER_DECISION mode, and returns the executive dashboard report.
        """
        self.analytics.apply_guardrails(state)
        return self.analytics.generate_funnel_report(state)

    def get_marketing_team_dashboard(self, state: CampaignState) -> Dict[str, Any]:
        """
        Returns the 1–2 Person Marketing Team executive dashboard:
        Spend -> Views -> Clicks -> Messages ('сколько написали') -> Sales ('сколько продалось'),
        paused Reels, root-cause diagnostics ('почему конверсия маленькая'), and pending recommendations.
        """
        return self.analytics.generate_funnel_report(state)

    def review_recommendation(
        self,
        state: CampaignState,
        recommendation_id: str,
        approve: bool,
        user_comment: Optional[str] = None,
        decided_by: str = "marketer",
    ) -> OptimizationRecommendation:
        """
        Human-in-the-loop decision handler ('предлагать, но решение за ними'):
        Allows the 1–2 person marketing team to approve or reject a proposed optimization.
        If approved and the recommendation relates to creative hook/offer/fatigue, automatically
        rotates in a fresh creative variant via CreativeCopywriterAgent.
        """
        target_rec: Optional[OptimizationRecommendation] = None
        for rec in state.pending_recommendations:
            if rec.recommendation_id == recommendation_id:
                target_rec = rec
                break

        if target_rec is None:
            raise ValueError(f"Recommendation '{recommendation_id}' not found in pending_recommendations.")

        target_rec.decision_status = "APPROVED" if approve else "REJECTED"
        target_rec.decided_by = decided_by
        target_rec.decided_at = datetime.now(timezone.utc)
        target_rec.user_comment = user_comment

        if approve and target_rec.category in ("CREATIVE_HOOK", "OFFER_HEADLINE", "AUDIENCE_FATIGUE"):
            self.copywriter.rotate_fatigued_creatives(state, force_rotation=True)

        state.record_audit_event(
            agent="SupervisorAgent",
            action="USER_DECISION_RECORDED",
            details={
                "recommendation_id": target_rec.recommendation_id,
                "target_id": target_rec.target_id,
                "category": target_rec.category,
                "decision_status": target_rec.decision_status,
                "decided_by": decided_by,
                "user_comment": user_comment,
            },
        )
        return target_rec

    def approve_recommendation(
        self,
        state: CampaignState,
        recommendation_id: str,
        user_comment: Optional[str] = None,
        decided_by: str = "marketer",
    ) -> OptimizationRecommendation:
        """Approves a pending optimization recommendation ('решение за ними -> одобрено')."""
        return self.review_recommendation(
            state=state,
            recommendation_id=recommendation_id,
            approve=True,
            user_comment=user_comment,
            decided_by=decided_by,
        )

    def reject_recommendation(
        self,
        state: CampaignState,
        recommendation_id: str,
        user_comment: Optional[str] = None,
        decided_by: str = "marketer",
    ) -> OptimizationRecommendation:
        """Rejects a pending optimization recommendation ('решение за ними -> отклонено')."""
        return self.review_recommendation(
            state=state,
            recommendation_id=recommendation_id,
            approve=False,
            user_comment=user_comment,
            decided_by=decided_by,
        )

