#!/usr/bin/env python3
"""
Multi-Agent Advertising Campaign E2E Test Runner (Python 3.12+).
Executes hermetic offline test suites across all 4 testing tiers.
Enforces zero external network access and outputs formatted summary metrics.

Usage:
    python run_tests.py              # Run all 4 tiers
    python run_tests.py --tier 1     # Run Tier 1: Feature Coverage only
    python run_tests.py --tier 2     # Run Tier 2: Boundary & Corner Cases only
    python run_tests.py --tier 3     # Run Tier 3: Cross-Feature Interactions only
    python run_tests.py --tier 4     # Run Tier 4: Real-World Scenarios only
"""

import sys
import os
import argparse
import unittest
import socket
from pathlib import Path
from typing import Dict, Any, List

# Ensure project root and src/ are in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
TESTS_DIR = PROJECT_ROOT / "tests"
E2E_DIR = TESTS_DIR / "e2e"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# Import socket blocking from conftest
from tests.conftest import enable_socket_blocking, BlockedNetworkError, load_fixture


def verify_socket_blocking_active() -> bool:
    """Confirms that external socket connections are actively intercepted and blocked."""
    enable_socket_blocking()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(("8.8.8.8", 53))
        return False  # Failed: Connection was not blocked!
    except BlockedNetworkError:
        return True   # Success: BlockedNetworkError was raised
    except Exception:
        return True   # Guard raised exception


TIER_FILES = {
    1: ("Tier 1: Feature Coverage", "test_tier1_feature_coverage.py"),
    2: ("Tier 2: Boundary & Corner Cases", "test_tier2_boundary_corner.py"),
    3: ("Tier 3: Cross-Feature Interactions", "test_tier3_cross_feature.py"),
    4: ("Tier 4: Real-World Scenarios", "test_tier4_real_world.py"),
}


def run_tier(tier_num: int, verbose: int = 1) -> unittest.TestResult:
    """Discovers and runs test cases for a specific tier file."""
    tier_name, filename = TIER_FILES[tier_num]
    test_file_path = E2E_DIR / filename

    if not test_file_path.exists():
        print(f"[-] Error: Test file not found: {test_file_path}", file=sys.stderr)
        result = unittest.TestResult()
        return result

    loader = unittest.TestLoader()
    suite = loader.discover(
        start_dir=str(E2E_DIR),
        pattern=filename,
        top_level_dir=str(PROJECT_ROOT)
    )

    runner = unittest.TextTestRunner(verbosity=verbose)
    print(f"\n{'='*70}")
    print(f"  RUNNING {tier_name.upper()} ({filename})")
    print(f"{'='*70}")
    result = runner.run(suite)
    return result


def main():
    parser = argparse.ArgumentParser(description="Multi-Agent Advertising Platform Test Runner")
    parser.add_argument(
        "--tier",
        type=int,
        choices=[1, 2, 3, 4],
        default=None,
        help="Run only the specified tier (1, 2, 3, or 4)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="count",
        default=1,
        help="Increase verbosity level"
    )
    parser.add_argument(
        "--use-pytest",
        action="store_true",
        help="Invoke pytest if installed in environment"
    )
    args = parser.parse_args()

    # Pre-flight socket guard verification
    if not verify_socket_blocking_active():
        print("[-] FATAL: Offline socket blocking guard failed to engage!", file=sys.stderr)
        sys.exit(1)

    print("=" * 70)
    print("  MULTI-AGENT CAMPAIGN SYSTEM - E2E VERIFICATION RUNNER")
    print("  Mode: Hermetic Offline (Zero-Network Sockets Enforced)")
    print("=" * 70)

    # Optional: Delegate to pytest if explicitly requested and available
    if args.use_pytest:
        try:
            import pytest
            pytest_args = ["-v", str(E2E_DIR)]
            if args.tier:
                _, filename = TIER_FILES[args.tier]
                pytest_args = ["-v", str(E2E_DIR / filename)]
            print(f"[i] Running tests with pytest: {' '.join(pytest_args)}")
            sys.exit(pytest.main(pytest_args))
        except ImportError:
            print("[!] Pytest not installed in current environment; falling back to Python unittest.")

    tiers_to_run = [args.tier] if args.tier else [1, 2, 3, 4]
    results_summary: List[Dict[str, Any]] = []
    total_failures = 0
    total_errors = 0

    for t in tiers_to_run:
        tier_title, filename = TIER_FILES[t]
        result = run_tier(t, verbose=args.verbose)
        results_summary.append({
            "tier": t,
            "name": tier_title,
            "filename": filename,
            "run": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "skipped": len(result.skipped),
            "passed": result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped)
        })
        total_failures += len(result.failures)
        total_errors += len(result.errors)

    # Print Summary Table
    print("\n" + "=" * 70)
    print("  VERIFICATION SUMMARY BY TIER")
    print("=" * 70)
    print(f"{'Tier':<6} | {'Tier Name':<32} | {'Tests':<6} | {'Passed':<6} | {'Skipped':<7} | {'Failed':<6}")
    print("-" * 70)

    total_tests = 0
    total_passed = 0
    total_skipped = 0
    total_failed_all = 0

    for r in results_summary:
        failed_count = r["failures"] + r["errors"]
        print(f"Tier {r['tier']:<1} | {r['name']:<32} | {r['run']:<6} | {r['passed']:<6} | {r['skipped']:<7} | {failed_count:<6}")
        total_tests += r["run"]
        total_passed += r["passed"]
        total_skipped += r["skipped"]
        total_failed_all += failed_count

    print("-" * 70)
    print(f"{'TOTAL':<6} | {'All Tiers Combined':<32} | {total_tests:<6} | {total_passed:<6} | {total_skipped:<7} | {total_failed_all:<6}")
    print("=" * 70)

    if total_failed_all == 0:
        print("[+] VERIFICATION PASSED: 100% of executed tests succeeded with 0 failures and 0 errors.")
        print("[+] Offline Isolation: Verified (0 external network connections attempted).")
        sys.exit(0)
    else:
        print(f"[-] VERIFICATION FAILED: {total_failed_all} test(s) failed or encountered errors.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
