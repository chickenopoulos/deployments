"""Mulvaney/Concretum canonical CTA (lab: mulvaney_concretum_replica).

126d Donchian, stop 0.3, pyramid 4, K=1, lag 1, loss-parity, long/short.
Cadence: daily after the last session (CME ~17:00 CT) via
deployments/scripts/run_daily_mulvaney_cta.sh
"""

from __future__ import annotations

from deployments.strategy_types import StrategyContext, StrategyResult
from deployments.utils.mulvaney_cta import PARAMS_CANONICAL, latest_book

STRATEGY_ID = "id21"
REBALANCING_STYLE = "freq_based"
RUN_FREQUENCY = "1d"
NAME = "Mulvaney replica canonical (Concretum defaults)"


def build(context: StrategyContext) -> StrategyResult:
    targets, meta = latest_book(context.as_of, PARAMS_CANONICAL)
    print(
        f"{STRATEGY_ID} canonical: live={meta['n_live']} "
        f"long={meta['n_long']} short={meta['n_short']} "
        f"gross={meta['gross_leverage']:.2f} net={meta['net_leverage']:.2f} "
        f"bar={meta['signal_timestamp']}"
    )
    return StrategyResult(
        strategy_id=STRATEGY_ID,
        portfolio=None,
        current_exposure=targets,
        rebalancing_style=REBALANCING_STYLE,
        signal_timestamp=str(meta["signal_timestamp"]),
        run_frequency=RUN_FREQUENCY,
        metadata={
            "name": NAME,
            "variant": "canonical",
            "purpose": "signal_efficacy",
            **meta,
        },
    )
