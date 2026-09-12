"""ES High10 PSA representative, lag-1 (Yahoo ES=F).

Lab run: thequantgpt-wrapper/runs/sp500_breakout_high10
Cadence: daily after CME close via deployments/scripts/run_daily_mulvaney_cta.sh

This is the lag-1 PSA representative (12 / 0.25 / 0.90 / 5), not canonical High10.
"""

from __future__ import annotations

from deployments.strategy_types import StrategyContext, StrategyResult
from deployments.utils.sp500_breakout_high10 import build as _build

STRATEGY_ID = "id32"


def build(context: StrategyContext) -> StrategyResult:
    return _build(context)
