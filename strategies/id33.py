"""Textbook Connors %B on SPY (STF id33).

Lab run: thequantgpt-wrapper/runs/qs_spy_two_mr
Cadence: daily after US cash close via deployments/scripts/run_daily_spy_portfolio.sh

Public Connors recipe (BB 5/1σ, %B < 0.2 for 3 days, exit %B > 0.8, SMA200).
Not the teaser-fit fingerprint and not the PSA representative or peak.
"""

from __future__ import annotations

from deployments.strategy_types import StrategyContext, StrategyResult
from deployments.utils.connors_pctb import build as _build

STRATEGY_ID = "id33"


def build(context: StrategyContext) -> StrategyResult:
    return _build(context)
