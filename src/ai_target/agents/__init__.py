"""
Multi-Agent Advertising Platform - Core Agent Modules.
"""

from ai_target.agents.analytics import (
    CREATIVE_FATIGUE_FREQUENCY_THRESHOLD,
    KILL_SWITCH_CPA_MULTIPLIER,
    MAX_TON_BID_CEILING,
    META_LEARNING_PHASE_EVENTS_THRESHOLD,
    MIN_TON_BID_FLOOR,
    AnalyticsGuardrailsAgent,
)
from ai_target.agents.copywriter import CreativeCopywriterAgent
from ai_target.agents.meta_tiktok import MetaTikTokExecutor
from ai_target.agents.strategist import (
    ADSLY_DEFAULT_CPM_TON,
    ADSLY_MIN_CPM_TON,
    ADSGRAM_MIN_DAILY_BUDGET_USDT,
    CLICKRU_DEFAULT_CASHBACK_RATE,
    CLICKRU_MAX_CASHBACK_RATE,
    CLICKRU_MIN_CASHBACK_RATE,
    DEFAULT_FLIGHT_DURATION_DAYS,
    ELAMA_DEFAULT_CASHBACK_RATE,
    ELAMA_MAX_CASHBACK_RATE,
    ELAMA_MIN_CASHBACK_RATE,
    InsufficientBudgetError,
    META_MIN_DAILY_BUDGET_USDT,
    SERVICE_COMMISSION_RATE,
    StrategistBillingAgent,
)
from ai_target.agents.supervisor import CliIntakeHandler, SupervisorAgent
from ai_target.agents.telegram_ecosystem import (
    CompetitorChannelInfo,
    TelegramEcosystemExecutor,
)

__all__ = [
    "SupervisorAgent",
    "CliIntakeHandler",
    "StrategistBillingAgent",
    "CreativeCopywriterAgent",
    "MetaTikTokExecutor",
    "TelegramEcosystemExecutor",
    "CompetitorChannelInfo",
    "AnalyticsGuardrailsAgent",
    "InsufficientBudgetError",
    "SERVICE_COMMISSION_RATE",
    "CLICKRU_DEFAULT_CASHBACK_RATE",
    "CLICKRU_MIN_CASHBACK_RATE",
    "CLICKRU_MAX_CASHBACK_RATE",
    "ELAMA_DEFAULT_CASHBACK_RATE",
    "ELAMA_MIN_CASHBACK_RATE",
    "ELAMA_MAX_CASHBACK_RATE",
    "META_MIN_DAILY_BUDGET_USDT",
    "ADSGRAM_MIN_DAILY_BUDGET_USDT",
    "ADSLY_MIN_CPM_TON",
    "ADSLY_DEFAULT_CPM_TON",
    "DEFAULT_FLIGHT_DURATION_DAYS",
    "KILL_SWITCH_CPA_MULTIPLIER",
    "CREATIVE_FATIGUE_FREQUENCY_THRESHOLD",
    "META_LEARNING_PHASE_EVENTS_THRESHOLD",
    "MIN_TON_BID_FLOOR",
    "MAX_TON_BID_CEILING",
]
