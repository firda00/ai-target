"""
ai_target.agents.telegram_ecosystem
Technical Executor Agent for Telegram Ecosystem (Adsly.Pro TON Cabinet & AdsGram Mini Apps) (Milestone 3).

Responsibilities:
1. Parses competitor Telegram channels via Adsly.Pro sandbox, extracting subscribers,
   engagement rate (ER), and estimated CPM in TON (>= 0.10 TON).
2. Computes starting TON bids respecting the hard >= 0.10 TON floor.
3. Validates and builds Adsly.Pro ad payloads (<= 160 chars, no raw URLs, cpm_ton >= 0.10, PAUSED status).
4. Builds AdsGram Mini-App payloads (daily_budget_usdt >= 10.0 USDT, PAUSED status).
5. Deploys payloads to offline sandbox adapters (AdslyProAdapter, AdsGramAdapter).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from pydantic import Field

from ai_target.adapters.adsgram_adapter import ADSGRAM_MIN_DAILY_BUDGET_USDT, AdsGramAdapter
from ai_target.adapters.adsly_adapter import ADSLY_MIN_CPM_TON, AdslyProAdapter
from ai_target.state.models import (
    CampaignState,
    LiveDeploymentRecord,
    LiveDeployments,
    PlatformEnum,
    StateBaseModel,
)
from ai_target.utils.moderation import validate_telegram_ads_copy


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


class CompetitorChannelInfo(StateBaseModel):
    """Structured competitor Telegram channel metadata returned by channel parser."""
    channel_id: int = Field(...)
    username: str = Field(...)
    title: str = Field(...)
    subscribers: int = Field(..., gt=0)
    engagement_rate: float = Field(..., gt=0.0)
    avg_post_views: int = Field(default=1000, ge=0)
    estimated_cpm_ton: float = Field(..., ge=0.10)
    niche: str = Field(default="General")
    language: str = Field(default="ru")
    verified: bool = Field(default=False)


class TelegramEcosystemExecutor:
    """
    Technical Executor Agent for Telegram Ads (via Adsly.Pro TON cabinet)
    and Telegram Mini-Apps (via AdsGram).
    """

    def __init__(self, mode: str = "sandbox") -> None:
        self.mode = mode
        self.adsly_adapter = AdslyProAdapter(mode=mode)
        self.adsgram_adapter = AdsGramAdapter(mode=mode)

    def parse_competitor_channels(
        self,
        keywords: Optional[List[str]] = None,
        limit: int = 3,
    ) -> List[CompetitorChannelInfo]:
        """
        Parses competitor channels via Adsly.Pro mock API, returning structured
        CompetitorChannelInfo models with subscribers > 0, ER > 0, and estimated_cpm_ton >= 0.10.
        """
        raw_res = self.adsly_adapter.search_channels(keywords=keywords, limit=limit)
        channel_list = raw_res.get("data", [])
        parsed: List[CompetitorChannelInfo] = []

        for item in channel_list:
            cpm = max(ADSLY_MIN_CPM_TON, float(item.get("estimated_cpm_ton", 0.15)))
            parsed.append(
                CompetitorChannelInfo(
                    channel_id=int(item.get("channel_id", 1000001)),
                    username=str(item.get("username", "@competitor_channel")),
                    title=str(item.get("title", "Competitor Channel")),
                    subscribers=max(1, int(item.get("subscribers", 10000))),
                    engagement_rate=max(0.001, float(item.get("engagement_rate", 0.05))),
                    avg_post_views=int(item.get("avg_post_views", 1000)),
                    estimated_cpm_ton=round(cpm, 4),
                    niche=str(item.get("niche", "General")),
                    language=str(item.get("language", "ru")),
                    verified=bool(item.get("verified", False)),
                )
            )
        return parsed

    def compute_starting_bid_ton(
        self,
        estimated_cpm: float = 0.15,
        competition: str = "medium",
    ) -> float:
        """
        Calculates starting bid in TON based on estimated channel CPM and competition level,
        strictly clamped to the >= 0.10 TON minimum floor.
        """
        est_val = _require_finite_float(estimated_cpm, "estimated_cpm")
        comp_norm = str(competition or "medium").lower()
        multiplier = 1.0
        if comp_norm == "high":
            multiplier = 1.15
        elif comp_norm == "low":
            multiplier = 0.95

        raw_bid = est_val * multiplier
        clamped_bid = max(ADSLY_MIN_CPM_TON, round(raw_bid, 4))
        return clamped_bid

    def validate_or_build_ad_payload(
        self,
        title: str,
        text: str,
        cpm_ton: float,
        budget_ton: float,
        promoted_entity: str = "@official_bot",
        target_channels: Optional[List[str]] = None,
        ad_status: str = "PAUSED",
    ) -> Dict[str, Any]:
        """
        Validates and builds an Adsly.Pro TON ad payload:
        - Enforces cpm_ton >= 0.10 TON (raises ValueError if < 0.10)
        - Enforces budget_ton > 0
        - Validates text <= 160 chars & no raw external URLs
        - Enforces ad_status = 'PAUSED'
        """
        if not title or not str(title).strip():
            raise ValueError("Ad title cannot be empty.")
        cpm_val = _require_finite_float(cpm_ton, "cpm_ton")
        budget_val = _require_finite_float(budget_ton, "budget_ton")

        if cpm_val < ADSLY_MIN_CPM_TON:
            raise ValueError(
                f"Adsly.Pro starting bid cpm_ton must be >= {ADSLY_MIN_CPM_TON} TON (got {cpm_ton})."
            )
        if budget_val <= 0:
            raise ValueError(f"Adsly.Pro budget_ton must be > 0 (got {budget_ton}).")

        # Validate Telegram Ads moderation constraints (<= 160 chars, no raw URLs)
        validate_telegram_ads_copy(text)

        return {
            "title": str(title).strip(),
            "text": str(text),
            "promoted_entity": str(promoted_entity),
            "cpm_ton": round(cpm_val, 4),
            "budget_ton": round(budget_val, 2),
            "target_channels": target_channels or ["@ton_signals_pro", "@crypto_insider_hub"],
            "ad_status": "PAUSED",
        }

    def build_adsgram_payload(
        self,
        campaign_name: str,
        daily_budget_usdt: float,
        format: str = "REWARDED_VIDEO",
        destination_url: str = "https://t.me/app_bot/start",
        cpm_usdt: float = 1.20,
    ) -> Dict[str, Any]:
        """
        Builds an AdsGram Mini-App campaign payload:
        - Enforces daily_budget_usdt >= 10.0 USDT
        - Enforces status = 'PAUSED'
        """
        if not campaign_name or not str(campaign_name).strip():
            raise ValueError("campaign_name cannot be empty.")
        budget_val = _require_finite_float(daily_budget_usdt, "daily_budget_usdt")
        cpm_val = _require_finite_float(cpm_usdt, "cpm_usdt")

        if budget_val < ADSGRAM_MIN_DAILY_BUDGET_USDT:
            raise ValueError(
                f"AdsGram daily_budget_usdt must be >= {ADSGRAM_MIN_DAILY_BUDGET_USDT} USDT (got {daily_budget_usdt})."
            )
        if cpm_val <= 0:
            raise ValueError(f"AdsGram cpm_usdt must be > 0 (got {cpm_usdt}).")

        return {
            "campaign_name": str(campaign_name).strip(),
            "daily_budget_usdt": round(budget_val, 2),
            "format": str(format).upper(),
            "cpm_usdt": round(cpm_val, 2),
            "destination_url": str(destination_url),
            "status": "PAUSED",
        }

    def deploy_adsly_sandbox(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Deploys an Adsly.Pro TON ad payload to the offline sandbox adapter."""
        return self.adsly_adapter.create_ad(payload)

    def deploy_adsgram_sandbox(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Deploys an AdsGram campaign payload to the offline sandbox adapter."""
        return self.adsgram_adapter.create_campaign(payload)

    def stage_campaigns(self, state: CampaignState) -> List[LiveDeploymentRecord]:
        """Stages Telegram Ecosystem allocations (Adsly.Pro and AdsGram) in PAUSED status."""
        records: List[LiveDeploymentRecord] = []
        if not state.media_plan or not state.media_plan.allocations:
            return records

        prod_name = state.client_brief.product_name if state.client_brief else "Campaign"
        creatives_list = list(state.creatives) if state.creatives else []

        for alloc in state.media_plan.allocations:
            plat_str = str(getattr(alloc.platform, "value", alloc.platform)).lower()
            if "adsly" in plat_str:
                matching_cr = [
                    c for c in creatives_list
                    if "adsly" in str(getattr(c.platform, "value", c.platform)).lower()
                ]
                copy_text = (
                    matching_cr[0].body_text
                    if matching_cr
                    else f"Try {prod_name[:30]} on Telegram. Launch @official_bot today!"
                )
                cpm_ton = max(ADSLY_MIN_CPM_TON, float(alloc.cpm_estimate or 0.20))
                payload = self.validate_or_build_ad_payload(
                    title=f"{prod_name[:25]}_Adsly",
                    text=copy_text,
                    cpm_ton=cpm_ton,
                    budget_ton=max(1.0, alloc.allocated_budget),
                )
                res = self.deploy_adsly_sandbox(payload)
                rec = LiveDeploymentRecord(
                    platform=PlatformEnum.TELEGRAM_ADSLY,
                    external_campaign_id=res["data"]["ad_id"],
                    status="PAUSED",
                    raw_payload=payload,
                    adapter_mode=self.mode,
                )
                records.append(rec)

            elif "adsgram" in plat_str:
                matching_cr = [
                    c for c in creatives_list
                    if "adsgram" in str(getattr(c.platform, "value", c.platform)).lower()
                ]
                dest_url = matching_cr[0].utm_tagged_url if matching_cr else "https://t.me/app_bot/start"
                payload = self.build_adsgram_payload(
                    campaign_name=f"{prod_name[:25]}_AdsGram",
                    daily_budget_usdt=max(ADSGRAM_MIN_DAILY_BUDGET_USDT, alloc.daily_budget),
                    destination_url=dest_url,
                )
                res = self.deploy_adsgram_sandbox(payload)
                rec = LiveDeploymentRecord(
                    platform=PlatformEnum.TELEGRAM_ADSGRAM,
                    external_campaign_id=res["campaign_id"],
                    status="PAUSED",
                    raw_payload=payload,
                    adapter_mode=self.mode,
                )
                records.append(rec)

        if isinstance(state.live_deployments, LiveDeployments):
            for r in records:
                state.live_deployments.add_deployment(r)
        elif isinstance(state.live_deployments, list):
            state.live_deployments.extend(records)

        state.record_audit_event(
            agent="TelegramEcosystemExecutor",
            action="STAGE_CAMPAIGNS",
            details={"staged_count": len(records)},
        )
        return records
