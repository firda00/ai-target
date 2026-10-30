"""
ai_target.adapters.adsgram_adapter
Mock/sandbox adapter for AdsGram Telegram Mini Apps ad network.
Enforces daily_budget_usdt >= 10.0 USDT and initial status 'PAUSED'.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any, Dict

from ai_target.adapters.base import BaseSandboxAdapter, SandboxAdapterError, validate_finite_float


ADSGRAM_MIN_DAILY_BUDGET_USDT: float = 10.00


class AdsGramAdapter(BaseSandboxAdapter):
    """Sandbox adapter for AdsGram Telegram Mini Apps ad platform."""

    def __init__(self, mode: str = "sandbox") -> None:
        super().__init__(mode=mode, fixture_name="adsgram_responses.json")

    def create_campaign(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Simulates POST /api/v1/campaigns/create enforcing daily_budget_usdt >= 10.0 USDT and PAUSED status."""
        daily_budget = validate_finite_float(payload.get("daily_budget_usdt", 0.0), "daily_budget_usdt")
        if daily_budget < ADSGRAM_MIN_DAILY_BUDGET_USDT:
            raise SandboxAdapterError(
                f"AdsGram daily_budget_usdt must be >= {ADSGRAM_MIN_DAILY_BUDGET_USDT} USDT (got {daily_budget})."
            )

        status = str(payload.get("status", "PAUSED")).upper()
        if status != "PAUSED":
            raise SandboxAdapterError(
                f"AdsGram campaign creation strictly enforces 'PAUSED' status, got '{status}'."
            )

        base_resp = copy.deepcopy(self.fixtures.get("campaign_create", {}))
        cmp_id = f"ag_camp_{uuid.uuid4().hex[:8]}"
        cpm_val = validate_finite_float(payload.get("cpm_usdt", base_resp.get("cpm_usdt", 1.20)), "cpm_usdt")
        response = {
            **base_resp,
            "campaign_id": cmp_id,
            "campaign_name": payload.get("campaign_name", "MiniApp_Rewarded_Ad"),
            "format": payload.get("format", "REWARDED_VIDEO"),
            "daily_budget_usdt": round(daily_budget, 2),
            "cpm_usdt": cpm_val,
            "destination_url": payload.get("destination_url", base_resp.get("destination_url", "")),
            "status": "PAUSED",
            "success": True,
        }
        self.ledger[cmp_id] = response
        self._record_call("POST /api/v1/adsgram/campaigns", payload, response)
        return response

    def update_status(self, campaign_id: str, new_status: str = "PAUSED") -> Dict[str, Any]:
        """Updates AdsGram campaign status."""
        status_norm = str(new_status).upper()
        if campaign_id in self.ledger:
            self.ledger[campaign_id]["status"] = status_norm
        response = {
            "status": "success",
            "campaign_id": campaign_id,
            "new_status": status_norm,
            "success": True,
        }
        self._record_call("POST /api/v1/adsgram/status", {"campaign_id": campaign_id, "new_status": status_norm}, response)
        return response
