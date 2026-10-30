"""
ai_target.adapters.tiktok_adapter
Mock/sandbox adapter for TikTok Marketing API v2.0.
Enforces Campaign -> AdGroup -> Ad hierarchy with operation_status strictly 'DISABLE'.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any, Dict, Optional

from ai_target.adapters.base import BaseSandboxAdapter, SandboxAdapterError, validate_finite_float


class TikTokMarketingAdapter(BaseSandboxAdapter):
    """Sandbox adapter for TikTok Marketing API v2.0."""

    def __init__(self, mode: str = "sandbox", advertiser_id: str = "710293847561029") -> None:
        super().__init__(mode=mode, fixture_name="tiktok_responses.json")
        self.advertiser_id = advertiser_id

    def create_campaign(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Simulates POST /open_api/v1.3/campaign/create/ with operation_status: DISABLE."""
        op_status = str(payload.get("operation_status", "DISABLE")).upper()
        if op_status != "DISABLE":
            raise SandboxAdapterError(
                f"TikTok campaign creation strictly enforces operation_status='DISABLE', got '{op_status}'."
            )

        budget = validate_finite_float(payload.get("budget", 50.0), "budget")
        if budget <= 0:
            raise SandboxAdapterError(f"TikTok campaign budget must be > 0, got {budget}.")

        base_resp = copy.deepcopy(self.fixtures.get("campaign_create", {}))
        cmp_id = f"tt_cmp_{uuid.uuid4().hex[:12]}"
        data = {
            **base_resp.get("data", {}),
            "campaign_id": cmp_id,
            "campaign_name": payload.get("campaign_name", payload.get("name", "TikTok_Campaign")),
            "objective_type": payload.get("objective_type", "CONVERSIONS"),
            "budget_mode": payload.get("budget_mode", "BUDGET_MODE_DAY"),
            "budget": budget,
            "operation_status": "DISABLE",
        }
        response = {
            "code": 0,
            "message": "OK",
            "data": data,
            "success": True,
        }
        self.ledger[cmp_id] = data
        self._record_call("POST /open_api/v1.3/campaign/create/", payload, response)
        return response

    def create_adgroup(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Simulates POST /open_api/v1.3/adgroup/create/ with operation_status: DISABLE."""
        op_status = str(payload.get("operation_status", "DISABLE")).upper()
        if op_status != "DISABLE":
            raise SandboxAdapterError(
                f"TikTok adgroup creation strictly enforces operation_status='DISABLE', got '{op_status}'."
            )

        budget = validate_finite_float(payload.get("budget", 20.0), "budget")
        if budget <= 0:
            raise SandboxAdapterError(f"TikTok adgroup budget must be > 0, got {budget}.")

        base_resp = copy.deepcopy(self.fixtures.get("adgroup_create", {}))
        adg_id = f"tt_adg_{uuid.uuid4().hex[:12]}"
        data = {
            **base_resp.get("data", {}),
            "adgroup_id": adg_id,
            "adgroup_name": payload.get("adgroup_name", "TikTok_AdGroup"),
            "campaign_id": payload.get("campaign_id", "tt_cmp_default"),
            "budget_mode": payload.get("budget_mode", "BUDGET_MODE_DAY"),
            "budget": budget,
            "operation_status": "DISABLE",
        }
        response = {
            "code": 0,
            "message": "OK",
            "data": data,
            "success": True,
        }
        self.ledger[adg_id] = data
        self._record_call("POST /open_api/v1.3/adgroup/create/", payload, response)
        return response

    def create_ad(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Simulates POST /open_api/v1.3/ad/create/ with operation_status: DISABLE."""
        creatives = payload.get("creatives", [])
        for cr in creatives:
            if str(cr.get("operation_status", "DISABLE")).upper() != "DISABLE":
                raise SandboxAdapterError("TikTok ad creative must have operation_status='DISABLE'.")

        op_status = str(payload.get("operation_status", "DISABLE")).upper()
        if op_status != "DISABLE":
            raise SandboxAdapterError(
                f"TikTok ad creation strictly enforces operation_status='DISABLE', got '{op_status}'."
            )

        ad_id = f"tt_ad_{uuid.uuid4().hex[:12]}"
        data = {
            "ad_ids": [ad_id],
            "ad_name": payload.get("ad_name", "TikTok_Video_Creative_A"),
            "operation_status": "DISABLE",
        }
        response = {
            "code": 0,
            "message": "OK",
            "data": data,
            "success": True,
        }
        self.ledger[ad_id] = data
        self._record_call("POST /open_api/v1.3/ad/create/", payload, response)
        return response

    def update_status(self, ad_id: str, operation_status: str = "DISABLE") -> Dict[str, Any]:
        """Simulates TikTok ad/campaign status update."""
        status_norm = str(operation_status).upper()
        if ad_id in self.ledger:
            self.ledger[ad_id]["operation_status"] = status_norm
        response = {
            "code": 0,
            "message": "OK",
            "data": {
                "ad_ids": [ad_id],
                "operation_status": status_norm,
            },
            "success": True,
        }
        self._record_call("POST /open_api/v1.3/ad/status/update/", {"ad_id": ad_id, "operation_status": status_norm}, response)
        return response
