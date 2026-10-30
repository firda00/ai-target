"""
tests/conftest.py - Offline Test Harness & Socket Blocking Configuration.
Ensures hermetic, zero-network test execution across all test tiers.
"""

import os
import sys
import json
import socket
from pathlib import Path

# 1. Path Setup: Ensure src/ is importable
TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 2. Fixture Directory
FIXTURES_DIR = TESTS_DIR / "fixtures"


def load_fixture(fixture_name: str) -> dict:
    """Load JSON fixture file by name (with or without .json extension)."""
    if not fixture_name.endswith(".json"):
        fixture_name = f"{fixture_name}.json"
    fixture_path = FIXTURES_DIR / fixture_name
    if not fixture_path.exists():
        raise FileNotFoundError(f"Fixture not found: {fixture_path}")
    with open(fixture_path, "r", encoding="utf-8") as f:
        return json.load(f)


# 3. Socket Blocking Implementation
_ORIGINAL_SOCKET_CONNECT = socket.socket.connect
_ORIGINAL_CREATE_CONNECTION = socket.create_connection


class BlockedNetworkError(RuntimeError):
    """Raised when any test attempts outbound network access."""
    pass


def guarded_socket_connect(self, *args, **kwargs):
    raise BlockedNetworkError(
        f"Network access disabled during offline tests! Socket connect attempted: {args} {kwargs}"
    )


def guarded_create_connection(*args, **kwargs):
    raise BlockedNetworkError(
        f"Network access disabled during offline tests! Connection attempted: {args} {kwargs}"
    )


def enable_socket_blocking():
    """Globally block external socket calls."""
    socket.socket.connect = guarded_socket_connect
    socket.create_connection = guarded_create_connection


def disable_socket_blocking():
    """Restore original socket methods (for teardown if needed)."""
    socket.socket.connect = _ORIGINAL_SOCKET_CONNECT
    socket.create_connection = _ORIGINAL_CREATE_CONNECTION


# Enable socket blocking immediately upon importing conftest
enable_socket_blocking()

# 4. Pytest Fixture Hooks (Active when running under pytest)
try:
    import pytest

    @pytest.fixture(autouse=True)
    def block_external_network():
        """Autouse pytest fixture guaranteeing zero outbound network calls."""
        enable_socket_blocking()
        yield
        # Maintain blocking across entire test run

    @pytest.fixture
    def meta_responses():
        return load_fixture("meta_responses.json")

    @pytest.fixture
    def tiktok_responses():
        return load_fixture("tiktok_responses.json")

    @pytest.fixture
    def adsly_responses():
        return load_fixture("adsly_responses.json")

    @pytest.fixture
    def adsgram_responses():
        return load_fixture("adsgram_responses.json")

    @pytest.fixture
    def billing_responses():
        return load_fixture("billing_responses.json")

except ImportError:
    # Running outside pytest (e.g. pure standard unittest runner)
    pass
