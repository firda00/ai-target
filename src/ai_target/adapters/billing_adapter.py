"""
ai_target.adapters.billing_adapter
Mock/sandbox adapter for Click.ru and eLama billing aggregators.
Simulates invoicing, payment confirmation webhooks, and agency cashback ledger reporting.
"""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from ai_target.adapters.base import BaseSandboxAdapter, SandboxAdapterError, validate_finite_float


class BillingAggregatorAdapter(BaseSandboxAdapter):
    """Sandbox adapter for Click.ru and eLama billing operations."""

    def __init__(self, mode: str = "sandbox", partner: str = "click_ru") -> None:
        super().__init__(mode=mode, fixture_name="billing_responses.json")
        self.partner = partner

    def create_invoice(self, gross_budget: float, partner: Optional[str] = None, currency: str = "USDT") -> Dict[str, Any]:
        """Simulates POST /api/v1/invoice/create."""
        budget_val = validate_finite_float(gross_budget, "gross_budget")
        if budget_val <= 0:
            raise SandboxAdapterError(f"Invoice gross_budget must be > 0, got {budget_val}.")

        partner_name = partner or self.partner
        commission = round(budget_val * 0.12, 2)
        net_spend = round(budget_val - commission, 2)
        inv_id = f"inv_{partner_name}_{uuid.uuid4().hex[:8]}"

        response = {
            "invoice_id": inv_id,
            "partner": partner_name,
            "account_id": "agency_master_48291",
            "gross_budget": round(budget_val, 2),
            "currency": currency,
            "commission_rate": 0.12,
            "commission_amount": commission,
            "net_media_spend": net_spend,
            "status": "PENDING",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.ledger[inv_id] = response
        self._record_call("POST /api/v1/invoice/create", {"gross_budget": budget_val, "partner": partner_name}, response)
        return response

    def simulate_payment_webhook(self, invoice_id: Optional[str] = None, amount_paid: float = 1000.0) -> Dict[str, Any]:
        """Simulates incoming PAYMENT_CONFIRMED webhook from billing aggregator."""
        paid_val = validate_finite_float(amount_paid, "amount_paid")
        if paid_val <= 0:
            raise SandboxAdapterError(f"Webhook amount_paid must be > 0, got {paid_val}.")

        base_webhook = copy.deepcopy(self.fixtures.get("webhook_simulate", {}))
        inv_id = invoice_id or base_webhook.get("invoice_id", f"inv_clickru_{uuid.uuid4().hex[:8]}")
        tx_hash = base_webhook.get("transaction_hash", f"tx_ton_0x{uuid.uuid4().hex[:12]}")

        if inv_id in self.ledger:
            self.ledger[inv_id]["status"] = "PAID"

        response = {
            **base_webhook,
            "event": "PAYMENT_CONFIRMED",
            "invoice_id": inv_id,
            "transaction_hash": tx_hash,
            "amount_paid": paid_val,
            "currency": "USDT",
            "payment_verified": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._record_call("WEBHOOK /api/v1/payment/confirm", {"invoice_id": inv_id}, response)
        return response
