"""Robot James macro ETF calendar (STF id31).

Lab run: thequantgpt-wrapper/runs/rj_macro_etf_calendar
Cadence: daily after US cash close via deployments/scripts/run_daily_spy_portfolio.sh
"""

from __future__ import annotations

from deployments.strategy_types import StrategyContext, StrategyResult
from deployments.utils.macro_etf_calendar import (
    NAME,
    REBALANCING_STYLE,
    RUN_FREQUENCY,
    STRATEGY_ID,
    build as _build,
)


def build(context: StrategyContext) -> StrategyResult:
    return _build(context)
