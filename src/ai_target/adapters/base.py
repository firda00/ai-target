"""
ai_target.adapters.base
Base sandbox adapter interface and offline JSON fixture loader.
All external ad platform and billing adapters inherit from BaseSandboxAdapter
and operate strictly offline using deterministic mock responses.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional


def get_fixtures_dir() -> Path:
    """Resolves the path to tests/fixtures/ relative to the project root."""
    # File is at src/ai_target/adapters/base.py -> parent(adapters)->parent(ai_target)->parent(src)->parent(root)
    root = Path(__file__).resolve().parent.parent.parent.parent
    fixtures_dir = root / "tests" / "fixtures"
    return fixtures_dir


def load_adapter_fixture(fixture_name: str, fallback: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Loads a static JSON fixture from tests/fixtures/ without any network calls."""
    if not fixture_name.endswith(".json"):
        fixture_name = f"{fixture_name}.json"
    path = get_fixtures_dir() / fixture_name
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return fallback if fallback is not None else {}


class SandboxAdapterError(ValueError):
    """Raised when a sandbox adapter validation or payload constraint check fails."""
    pass


def validate_finite_float(value: Any, field_name: str = "value") -> float:
    """Validates that a numeric value is not a boolean and is finite (not NaN or Inf)."""
    if isinstance(value, bool) or value is None:
        raise SandboxAdapterError(f"Invalid {field_name}: boolean or None is not a valid number.")
    try:
        num = float(value)
    except (TypeError, ValueError) as exc:
        raise SandboxAdapterError(f"Invalid {field_name}: '{value}' cannot be converted to float.") from exc
    if not math.isfinite(num):
        raise SandboxAdapterError(f"Invalid {field_name}: must be a finite number (got {value}).")
    return num


class BaseSandboxAdapter:
    """
    Base class for offline sandbox/mock API adapters.
    Maintains an in-memory deployment ledger and operation history.
    """

    def __init__(self, mode: str = "sandbox", fixture_name: Optional[str] = None) -> None:
        if mode not in ("sandbox", "mock", "live"):
            raise ValueError(f"Invalid adapter mode: {mode}")
        self.mode = mode
        self.fixture_name = fixture_name
        self.fixtures: Dict[str, Any] = (
            load_adapter_fixture(fixture_name) if fixture_name else {}
        )
        self.ledger: Dict[str, Dict[str, Any]] = {}
        self.call_history: List[Dict[str, Any]] = []

    def _record_call(self, endpoint: str, payload: Dict[str, Any], response: Dict[str, Any]) -> None:
        self.call_history.append({
            "endpoint": endpoint,
            "payload": payload,
            "response": response,
        })
