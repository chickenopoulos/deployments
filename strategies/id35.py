"""G7 Dukascopy inside-bar compression, equal-weight PSA representatives (STF id35).

Lab run: audjpy_inside_compress. Per-sleeve median-stable cells. Not canonical.
Cadence: daily after Dukascopy 1d bar completes via run_daily_g7_inside_compress.sh
"""

from __future__ import annotations

from deployments.strategy_types import StrategyContext, StrategyResult
from deployments.utils.inside_compress_fx import build_for

STRATEGY_ID = "id35"


def build(context: StrategyContext) -> StrategyResult:
    return build_for(context, STRATEGY_ID)
