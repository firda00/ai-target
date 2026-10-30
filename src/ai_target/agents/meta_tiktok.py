"""
ai_target.agents.meta_tiktok
Technical Executor Agent for Meta Marketing API and TikTok Marketing API v2.0 (Milestone 3).

Responsibilities:
1. Constructs Campaign -> AdSet -> Ad hierarchy payloads for Meta Marketing API
   strictly in 'PAUSED' status, converting USD daily budget to integer cents (>= 1000 cents / $10.00).
2. Constructs Campaign -> AdGroup -> Ad hierarchy payloads for TikTok Marketing API v2.0
   strictly with operation_status 'DISABLE'.
3. Stages and deploys payloads into offline sandbox adapters (MetaMarketingAdapter, TikTokMarketingAdapter)
   and records LiveDeploymentRecord entries in CampaignState.
"""

from __future__ import annotations

import math
import uuid
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from ai_target.adapters.meta_adapter import MetaMarketingAdapter
from ai_target.adapters.tiktok_adapter import TikTokMarketingAdapter
from ai_target.state.models import (
    CampaignState,
    LiveDeploymentRecord,
    LiveDeployments,
    PlatformEnum,
)


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


class MetaTikTokExecutor:
    """
    Technical Executor Agent for Meta (Instagram Reels/Stories) and TikTok Marketing API v2.0.
    Guarantees all generated and deployed entities start strictly in PAUSED / DISABLE status.
    """

    def __init__(self, mode: str = "sandbox") -> None:
        self.mode = mode
        self.meta_adapter = MetaMarketingAdapter(mode=mode)
        self.tiktok_adapter = TikTokMarketingAdapter(mode=mode)

    def build_meta_payload(
        self,
        campaign_name: str,
        daily_budget_usd: float,
        creative_id: str = "cr_meta_default",
        destination_url: str = "https://example.com",
        target_countries: Optional[List[str]] = None,
        objective: str = "OUTCOME_LEADS",
        status: str = "PAUSED",
    ) -> Dict[str, Any]:
        """
        Builds a compliant Meta Marketing API hierarchy payload:
        Campaign -> AdSet -> Ad, strictly enforcing status='PAUSED'
        and converting daily_budget_usd into integer cents (>= 1000 cents = $10.00).
        """
        if not campaign_name or not str(campaign_name).strip():
            raise ValueError("campaign_name cannot be empty.")

        budget_usd = _require_finite_float(daily_budget_usd, "daily_budget_usd")
        if budget_usd < 10.0:
            raise ValueError(
                f"Meta minimum daily budget is $10.00 USD (1000 cents), got ${daily_budget_usd}."
            )

        # Convert float USD to exact integer cents using Decimal half-up rounding
        cents_dec = (Decimal(str(budget_usd)) * Decimal("100")).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        daily_budget_cents: int = int(cents_dec)
        if daily_budget_cents < 1000:
            raise ValueError(
                f"Meta daily_budget in cents must be >= 1000 ($10.00), got {daily_budget_cents}."
            )
        countries = target_countries if target_countries else ["KZ", "UZ"]

        # Force PAUSED status regardless of input to satisfy safety invariant
        enforced_status = "PAUSED"

        campaign_payload = {
            "name": str(campaign_name).strip(),
            "objective": objective,
            "status": enforced_status,
            "buying_type": "AUCTION",
            "special_ad_categories": ["NONE"],
        }

        adset_payload = {
            "name": f"{campaign_name}_Reels_AdSet",
            "daily_budget": daily_budget_cents,
            "billing_event": "IMPRESSIONS",
            "optimization_goal": "LEAD_GENERATION",
            "targeting": {
                "geo_locations": {"countries": countries},
                "publisher_platforms": ["instagram"],
                "instagram_positions": ["reels", "story"],
            },
            "status": enforced_status,
        }

        ad_payload = {
            "name": f"{campaign_name}_Reels_Ad",
            "creative": {
                "creative_id": str(creative_id),
                "destination_url": str(destination_url),
            },
            "status": enforced_status,
        }

        return {
            "campaign": campaign_payload,
            "adset": adset_payload,
            "ad": ad_payload,
        }

    def build_tiktok_payload(
        self,
        campaign_name: str,
        daily_budget_usd: float = 50.0,
        adgroup_budget_usd: float = 20.0,
        destination_url: str = "https://example.com",
        target_countries: Optional[List[str]] = None,
        objective_type: str = "CONVERSIONS",
        operation_status: str = "DISABLE",
    ) -> Dict[str, Any]:
        """
        Builds a compliant TikTok Marketing API v2.0 hierarchy payload:
        Campaign -> AdGroup -> Ad, strictly enforcing operation_status='DISABLE'.
        """
        if not campaign_name or not str(campaign_name).strip():
            raise ValueError("campaign_name cannot be empty.")

        cmp_budget = _require_finite_float(daily_budget_usd, "daily_budget_usd")
        adg_budget = _require_finite_float(adgroup_budget_usd, "adgroup_budget_usd")
        if cmp_budget <= 0 or adg_budget <= 0:
            raise ValueError("TikTok campaign and adgroup budgets must be strictly positive.")

        enforced_status = "DISABLE"
        locations = target_countries if target_countries else ["KZ", "UZ"]

        campaign_payload = {
            "campaign_name": str(campaign_name).strip(),
            "objective_type": objective_type,
            "budget_mode": "BUDGET_MODE_DAY",
            "budget": round(cmp_budget, 2),
            "operation_status": enforced_status,
        }

        adgroup_payload = {
            "adgroup_name": f"{campaign_name}_Vertical_Video_AdGroup",
            "placement_type": "PLACEMENT_TYPE_NORMAL",
            "placements": ["PLACEMENT_TIKTOK"],
            "location_ids": locations,
            "budget_mode": "BUDGET_MODE_DAY",
            "budget": round(adg_budget, 2),
            "optimization_goal": "CONVERT",
            "billing_event": "oCPM",
            "operation_status": enforced_status,
        }

        ad_payload = {
            "ad_name": f"{campaign_name}_Video_Ad",
            "operation_status": enforced_status,
            "creatives": [
                {
                    "ad_name": f"{campaign_name}_Creative_A",
                    "landing_page_url": str(destination_url),
                    "call_to_action": "LEARN_MORE",
                    "operation_status": enforced_status,
                }
            ],
        }

        return {
            "campaign": campaign_payload,
            "adgroup": adgroup_payload,
            "ad": ad_payload,
        }

    def deploy_meta_sandbox(self, campaign_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Deploys a Meta campaign payload (or full hierarchy) to the offline Meta sandbox adapter."""
        if "campaign" in campaign_payload and isinstance(campaign_payload["campaign"], dict):
            cmp_res = self.meta_adapter.create_campaign(campaign_payload["campaign"])
            adset_data = dict(campaign_payload.get("adset", {"daily_budget": 1500, "status": "PAUSED"}))
            adset_data["campaign_id"] = cmp_res["id"]
            adset_res = self.meta_adapter.create_adset(adset_data)
            ad_data = dict(campaign_payload.get("ad", {"status": "PAUSED"}))
            ad_data["adset_id"] = adset_res["id"]
            ad_res = self.meta_adapter.create_ad(ad_data)
            return {
                "success": True,
                "id": cmp_res["id"],
                "campaign_id": cmp_res["id"],
                "adset_id": adset_res["id"],
                "ad_id": ad_res["id"],
                "status": "PAUSED",
            }
        else:
            return self.meta_adapter.create_campaign(campaign_payload)

    def deploy_tiktok_sandbox(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Deploys a TikTok campaign payload (or full hierarchy) to the offline TikTok sandbox adapter."""
        if "campaign" in payload and isinstance(payload["campaign"], dict):
            cmp_res = self.tiktok_adapter.create_campaign(payload["campaign"])
            cmp_id = cmp_res["data"]["campaign_id"]
            adg_data = dict(payload.get("adgroup", {"budget": 20.0, "operation_status": "DISABLE"}))
            adg_data["campaign_id"] = cmp_id
            adg_res = self.tiktok_adapter.create_adgroup(adg_data)
            ad_res = self.tiktok_adapter.create_ad(payload.get("ad", {"operation_status": "DISABLE", "creatives": []}))
            return {
                "success": True,
                "code": 0,
                "campaign_id": cmp_id,
                "adgroup_id": adg_res["data"]["adgroup_id"],
                "ad_ids": ad_res["data"]["ad_ids"],
                "operation_status": "DISABLE",
                "data": cmp_res["data"],
            }
        else:
            return self.tiktok_adapter.create_campaign(payload)

    def stage_campaigns(self, state: CampaignState) -> List[LiveDeploymentRecord]:
        """Stages Meta and TikTok allocations in CampaignState into PAUSED/DISABLE deployments."""
        records: List[LiveDeploymentRecord] = []
        if not state.media_plan or not state.media_plan.allocations:
            return records

        prod_name = state.client_brief.product_name if state.client_brief else "Campaign"
        countries = state.client_brief.target_geo if state.client_brief and state.client_brief.target_geo else ["KZ"]
        creatives_list = list(state.creatives) if state.creatives else []

        for alloc in state.media_plan.allocations:
            plat_str = str(getattr(alloc.platform, "value", alloc.platform)).lower()
            if "meta" in plat_str or "instagram" in plat_str:
                matching_cr = [
                    c for c in creatives_list
                    if "meta" in str(getattr(c.platform, "value", c.platform)).lower()
                ]
                cr_id = matching_cr[0].creative_id if matching_cr else "cr_meta_01"
                dest_url = matching_cr[0].utm_tagged_url if matching_cr else "https://example.com"
                payload = self.build_meta_payload(
                    campaign_name=f"{prod_name}_Meta",
                    daily_budget_usd=alloc.daily_budget,
                    creative_id=cr_id,
                    destination_url=dest_url,
                    target_countries=countries,
                )
                res = self.deploy_meta_sandbox(payload)
                rec = LiveDeploymentRecord(
                    platform=PlatformEnum.META_INSTAGRAM,
                    external_campaign_id=res["id"],
                    external_adset_id=res.get("adset_id"),
                    external_ad_id=res.get("ad_id"),
                    status="PAUSED",
                    raw_payload=payload,
                    adapter_mode=self.mode,
                )
                records.append(rec)

            elif "tiktok" in plat_str:
                matching_cr = [
                    c for c in creatives_list
                    if "tiktok" in str(getattr(c.platform, "value", c.platform)).lower()
                ]
                dest_url = matching_cr[0].utm_tagged_url if matching_cr else "https://example.com"
                payload = self.build_tiktok_payload(
                    campaign_name=f"{prod_name}_TikTok",
                    daily_budget_usd=max(50.0, alloc.allocated_budget),
                    adgroup_budget_usd=max(20.0, alloc.daily_budget),
                    destination_url=dest_url,
                    target_countries=countries,
                )
                res = self.deploy_tiktok_sandbox(payload)
                rec = LiveDeploymentRecord(
                    platform=PlatformEnum.TIKTOK,
                    external_campaign_id=res["campaign_id"],
                    external_adset_id=res.get("adgroup_id"),
                    external_ad_id=(res.get("ad_ids") or [None])[0],
                    status="DISABLE",
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
            agent="MetaTikTokExecutor",
            action="STAGE_CAMPAIGNS",
            details={"staged_count": len(records)},
        )
        return records
