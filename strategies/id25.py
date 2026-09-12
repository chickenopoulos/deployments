"""USDJPY Yahoo FX overnight squeeze (STF id25)."""

from __future__ import annotations

from deployments.strategy_types import StrategyContext, StrategyResult
from deployments.utils.vol_compression_fx import build_for

STRATEGY_ID = "id25"


def build(context: StrategyContext) -> StrategyResult:
    return build_for(context, STRATEGY_ID)
