"""
ai_target.adapters.meta_adapter
Mock/sandbox adapter for Meta Marketing API (Graph API v19.0+).
Simulates Campaign -> AdSet -> AdCreative -> Ad creation strictly in PAUSED status,
daily_budget integer cents validation (>= 1000 cents / $10.00), status updates, and insights.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any, Dict, List, Optional

from ai_target.adapters.base import BaseSandboxAdapter, SandboxAdapterError


class MetaMarketingAdapter(BaseSandboxAdapter):
    """Sandbox adapter for Meta Graph API campaign management."""

    def __init__(self, mode: str = "sandbox", account_id: str = "act_1002938472910") -> None:
        super().__init__(mode=mode, fixture_name="meta_responses.json")
        self.account_id = account_id

    def create_campaign(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Simulates POST /act_{account_id}/campaigns in PAUSED status."""
        if not payload or not str(payload.get("name", "")).strip():
            raise SandboxAdapterError("Meta campaign payload requires a non-empty 'name'.")

        status = str(payload.get("status", "PAUSED")).upper()
        if status != "PAUSED":
            raise SandboxAdapterError(
                f"Meta campaign creation strictly enforces 'PAUSED' initial status, got '{status}'."
            )

        base_resp = copy.deepcopy(self.fixtures.get("campaign_create", {}))
        cmp_id = f"cmp_meta_{uuid.uuid4().hex[:12]}"
        response = {
            **base_resp,
            "id": cmp_id,
            "name": payload["name"],
            "objective": payload.get("objective", base_resp.get("objective", "OUTCOME_LEADS")),
            "status": "PAUSED",
            "buying_type": payload.get("buying_type", "AUCTION"),
            "special_ad_categories": payload.get("special_ad_categories", ["NONE"]),
            "success": True,
        }
        self.ledger[cmp_id] = response
        self._record_call(f"POST /{self.account_id}/campaigns", payload, response)
        return response

    def create_adset(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Simulates POST /act_{account_id}/adsets with integer cents budget and PAUSED status."""
        status = str(payload.get("status", "PAUSED")).upper()
        if status != "PAUSED":
            raise SandboxAdapterError(
                f"Meta adset creation strictly enforces 'PAUSED' initial status, got '{status}'."
            )

        daily_budget = payload.get("daily_budget")
        if not isinstance(daily_budget, int) or isinstance(daily_budget, bool):
            raise SandboxAdapterError(
                f"Meta adset 'daily_budget' must be an integer in cents, got {type(daily_budget).__name__}."
            )
        if daily_budget < 1000:
            raise SandboxAdapterError(
                f"Meta adset 'daily_budget' must be >= 1000 cents ($10.00), got {daily_budget}."
            )

        base_resp = copy.deepcopy(self.fixtures.get("adset_create", {}))
        adset_id = f"adset_meta_{uuid.uuid4().hex[:12]}"
        response = {
            **base_resp,
            "id": adset_id,
            "name": payload.get("name", "Reels_Targeting_AdSet"),
            "campaign_id": payload.get("campaign_id", base_resp.get("campaign_id", "cmp_meta_default")),
            "daily_budget": daily_budget,
            "billing_event": payload.get("billing_event", "IMPRESSIONS"),
            "optimization_goal": payload.get("optimization_goal", "LEAD_GENERATION"),
            "targeting": payload.get("targeting", base_resp.get("targeting", {})),
            "status": "PAUSED",
            "success": True,
        }
        self.ledger[adset_id] = response
        self._record_call(f"POST /{self.account_id}/adsets", payload, response)
        return response

    def create_ad(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Simulates POST /act_{account_id}/ads in PAUSED status."""
        status = str(payload.get("status", "PAUSED")).upper()
        if status != "PAUSED":
            raise SandboxAdapterError(
                f"Meta ad creation strictly enforces 'PAUSED' initial status, got '{status}'."
            )

        base_resp = copy.deepcopy(self.fixtures.get("ad_create", {}))
        ad_id = f"ad_meta_{uuid.uuid4().hex[:12]}"
        response = {
            **base_resp,
            "id": ad_id,
            "name": payload.get("name", "Reels_Ad_V1"),
            "adset_id": payload.get("adset_id", base_resp.get("adset_id", "adset_meta_default")),
            "creative": payload.get("creative", base_resp.get("creative", {})),
            "status": "PAUSED",
            "success": True,
        }
        self.ledger[ad_id] = response
        self._record_call(f"POST /{self.account_id}/ads", payload, response)
        return response

    def update_status(self, entity_id: str, new_status: str = "PAUSED") -> Dict[str, Any]:
        """Updates status of a Meta campaign, adset, or ad."""
        status_norm = str(new_status).upper()
        if entity_id in self.ledger:
            self.ledger[entity_id]["status"] = status_norm
        response = {
            "id": entity_id,
            "success": True,
            "updated_status": status_norm,
        }
        self._record_call(f"POST /{entity_id}", {"status": status_norm}, response)
        return response

    def get_insights(self, entity_id: Optional[str] = None) -> Dict[str, Any]:
        """Returns simulated Meta Insights telemetry."""
        return copy.deepcopy(self.fixtures.get("insights", {"data": []}))
