"""
ai_target.cli
Interactive CLI & Simulated Telegram Bot Entrypoint for the 6-Role Multi-Agent Advertising Platform.
Can be run via `python -m ai_target` or `python -m ai_target.cli`.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Dict, Optional

from ai_target.agents.supervisor import CliIntakeHandler, SupervisorAgent
from ai_target.state.models import (
    CampaignState,
    PerformanceMetrics,
    ReelCreativeMetrics,
)


def run_demo_simulation(
    product_name: str = "AI Crypto Trading Bot",
    target_geo: str = "KZ, UZ",
    goal: str = "LEADS",
    budget: float = 1500.0,
) -> CampaignState:
    """Runs a complete deterministic end-to-end simulation of all 6 agent roles + per-Reel CRM diagnostics."""
    handler = CliIntakeHandler(
        simulated_inputs={
            "product_name": product_name,
            "target_geo": [g.strip() for g in target_geo.split(",") if g.strip()],
            "goal": goal,
            "budget": budget,
        }
    )
    brief = handler.collect_brief()
    supervisor = SupervisorAgent(mode="sandbox")

    state = supervisor.create_campaign(brief)
    state = supervisor.run_planning_and_staging_pipeline(state)
    state = supervisor.confirm_payment_and_launch(state, transaction_hash="tx_demo_verified_999")

    # Simulate per-Reel telemetry: Reel A converts strongly, Reel B has low conversion and gets auto-paused
    state.reel_metrics.extend(
        [
            ReelCreativeMetrics(
                creative_id="cr_reel_winner_a",
                creative_name="Reel A: Fast UI Demo",
                spend=35.0,
                impressions=8000,
                reach=4000,
                three_sec_views=2800,
                avg_watch_time_sec=6.5,
                clicks=260,
                messages_received=24,
                sales_count=6,
                conversions=24,
                revenue=600.0,
                target_cpa=15.0,
            ),
            ReelCreativeMetrics(
                creative_id="cr_reel_weak_b",
                creative_name="Reel B: Generic Intro",
                spend=25.0,
                impressions=4000,
                reach=2000,
                three_sec_views=400,
                avg_watch_time_sec=1.8,
                clicks=15,
                messages_received=0,
                sales_count=0,
                conversions=0,
                revenue=0.0,
                target_cpa=15.0,
            ),
        ]
    )

    # Simulate 2-hour campaign-level telemetry check
    metrics = PerformanceMetrics(
        spend=60.0,
        impressions=12000,
        reach=6000,
        three_sec_views=3200,
        clicks=275,
        conversions=24,
        messages_received=24,
        sales_count=6,
        revenue=600.0,
        target_cpa=15.0,
        frequency=2.0,
    )
    state.performance_metrics.append(metrics)
    state = supervisor.analytics.apply_guardrails(state)
    return state


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="AI Target 6-Role Multi-Agent Ad Campaign CLI")
    parser.add_argument("--product", default="AI Crypto Trading Bot", help="Product or service name")
    parser.add_argument("--geo", default="KZ, UZ", help="Comma-separated target GEOs")
    parser.add_argument("--goal", default="LEADS", help="Campaign goal (LEADS, SALES, APP_INSTALLS, TRAFFIC)")
    parser.add_argument("--budget", type=float, default=1500.0, help="Gross budget in USDT")
    args = parser.parse_args(argv)

    state = run_demo_simulation(
        product_name=args.product,
        target_geo=args.geo,
        goal=args.goal,
        budget=args.budget,
    )
    supervisor = SupervisorAgent(mode="sandbox")
    report = supervisor.get_marketing_team_dashboard(state)
    print(f"[+] Campaign {state.campaign_id} Status: {state.status.value}")
    print(f"[+] Gross Budget: {state.financials.gross_budget} USDT | Net Spend: {state.financials.net_ad_spend} USDT")
    print(f"[+] Allocated Channels: {len(state.media_plan.allocations)} | Creatives: {len(state.creatives)} | Deployments: {len(state.live_deployments)}")
    print(
        f"[+] CRM Funnel: Messaged: {report['messages_received']} | "
        f"Sold: {report['sales_count']} | Paused Reels: {len(report['paused_reels'])} | "
        f"Pending Decisions: {len(report['pending_recommendations'])}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

