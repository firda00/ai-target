"""
ai_target.adapters.adsly_adapter
Mock/sandbox adapter for Adsly.Pro REST API (TON-based Telegram Ads cabinet).
Simulates competitor channel search, TON ad creation (CPM >= 0.10 TON, <= 160 chars, PAUSED status),
dynamic TON bid adjustments, and campaign pause.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any, Dict, List, Optional

from ai_target.adapters.base import BaseSandboxAdapter, SandboxAdapterError, validate_finite_float
from ai_target.utils.moderation import validate_telegram_ads_copy


ADSLY_MIN_CPM_TON: float = 0.10
ADSLY_MAX_CPM_TON: float = 50.0


class AdslyProAdapter(BaseSandboxAdapter):
    """Sandbox adapter for Adsly.Pro Telegram Ads REST API."""

    def __init__(self, mode: str = "sandbox") -> None:
        super().__init__(mode=mode, fixture_name="adsly_responses.json")

    def search_channels(self, keywords: Optional[List[str]] = None, limit: int = 5) -> Dict[str, Any]:
        """Simulates GET /api/v1/channels/search returning competitor channel metrics."""
        base_resp = copy.deepcopy(self.fixtures.get("channels_search", {"status": "success", "code": 200, "data": []}))
        channels = base_resp.get("data", [])
        if limit and limit > 0:
            channels = channels[:limit]
        response = {
            "status": "success",
            "code": 200,
            "channels_found": len(channels),
            "data": channels,
        }
        self._record_call("GET /api/v1/channels/search", {"keywords": keywords, "limit": limit}, response)
        return response

    def create_ad(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Simulates POST /api/v1/ads/create enforcing cpm_ton >= 0.10 TON, text <= 160 chars, and PAUSED status."""
        cpm_ton = validate_finite_float(payload.get("cpm_ton", 0.0), "cpm_ton")
        if cpm_ton < ADSLY_MIN_CPM_TON:
            raise SandboxAdapterError(
                f"Adsly.Pro minimum CPM floor violation: cpm_ton must be >= {ADSLY_MIN_CPM_TON} TON (got {cpm_ton})."
            )

        budget_ton = validate_finite_float(payload.get("budget_ton", 10.0), "budget_ton")
        if budget_ton <= 0:
            raise SandboxAdapterError(f"Adsly.Pro budget_ton must be > 0 (got {budget_ton}).")

        text = str(payload.get("text", "")).strip()
        if not text:
            raise SandboxAdapterError("Adsly.Pro ad text cannot be empty.")
        # Validate Telegram Ads moderation rules (<= 160 chars, no raw external links)
        validate_telegram_ads_copy(text)

        ad_status = str(payload.get("ad_status", payload.get("status", "PAUSED"))).upper()
        if ad_status != "PAUSED":
            raise SandboxAdapterError(f"Adsly.Pro initial ad_status must be 'PAUSED', got '{ad_status}'.")

        ad_id = f"adsly_ton_{uuid.uuid4().hex[:8]}"
        data = {
            "ad_id": ad_id,
            "title": payload.get("title", "Telegram TON Ad"),
            "text": text,
            "promoted_entity": payload.get("promoted_entity", "@official_bot"),
            "cpm_ton": round(cpm_ton, 4),
            "budget_ton": round(budget_ton, 2),
            "target_channel_count": len(payload.get("target_channels", payload.get("channels", []))) or 2,
            "ad_status": "PAUSED",
            "moderation_status": "APPROVED",
        }
        response = {
            "status": "success",
            "code": 200,
            "data": data,
            "success": True,
        }
        self.ledger[ad_id] = data
        self._record_call("POST /api/v1/ads/create", payload, response)
        return response

    def update_bid(self, ad_id: str, new_cpm_ton: float) -> Dict[str, Any]:
        """Simulates POST /api/v1/ads/bid updating CPM in TON."""
        cpm_val = validate_finite_float(new_cpm_ton, "new_cpm_ton")
        if cpm_val < ADSLY_MIN_CPM_TON:
            raise SandboxAdapterError(
                f"Cannot update bid below minimum floor of {ADSLY_MIN_CPM_TON} TON (got {cpm_val})."
            )
        old_cpm = self.ledger.get(ad_id, {}).get("cpm_ton", 0.15)
        if ad_id in self.ledger:
            self.ledger[ad_id]["cpm_ton"] = round(cpm_val, 4)
        response = {
            "status": "success",
            "code": 200,
            "data": {
                "ad_id": ad_id,
                "old_cpm_ton": old_cpm,
                "new_cpm_ton": round(new_cpm_ton, 4),
                "status": "UPDATED",
            },
            "success": True,
        }
        self._record_call("POST /api/v1/ads/bid", {"ad_id": ad_id, "new_cpm_ton": new_cpm_ton}, response)
        return response

    def pause_ad(self, ad_id: str) -> Dict[str, Any]:
        """Simulates POST /api/v1/ads/pause."""
        if ad_id in self.ledger:
            self.ledger[ad_id]["ad_status"] = "PAUSED"
        response = {
            "status": "success",
            "code": 200,
            "data": {
                "ad_id": ad_id,
                "ad_status": "PAUSED",
            },
            "success": True,
        }
        self._record_call("POST /api/v1/ads/pause", {"ad_id": ad_id}, response)
        return response
