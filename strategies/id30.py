"""ES Turnaround Wednesday lag-0 (Yahoo ES=F).

Lab run: thequantgpt-wrapper/runs/es_turnaround_wednesday
Cadence: daily after CME close via deployments/scripts/run_daily_mulvaney_cta.sh
"""

from __future__ import annotations

from deployments.strategy_types import StrategyContext, StrategyResult
from deployments.utils.turnaround_wednesday import build as _build

STRATEGY_ID = "id30"


def build(context: StrategyContext) -> StrategyResult:
    return _build(context)
