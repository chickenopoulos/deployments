"""G7 Dukascopy inside-bar compression, equal-weight locked fingerprint (STF id34).

Lab run: audjpy_inside_compress. Canonical params on every sleeve. Not id35.
Cadence: daily after Dukascopy 1d bar completes via run_daily_g7_inside_compress.sh
"""

from __future__ import annotations

from deployments.strategy_types import StrategyContext, StrategyResult
from deployments.utils.inside_compress_fx import build_for

STRATEGY_ID = "id34"


def build(context: StrategyContext) -> StrategyResult:
    return build_for(context, STRATEGY_ID)
