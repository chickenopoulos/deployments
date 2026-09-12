"""Mulvaney/Concretum PSA-best CTA (lab: mulvaney_concretum_replica).

IS grid peak after N=7201: 63d, stop 0.2, cap 1, K=0.5, lag 0,
hierarchical loss-parity, long-only. Not the lab canonical spec.
Cadence: daily via deployments/scripts/run_daily_mulvaney_cta.sh
"""

from __future__ import annotations

from deployments.strategy_types import StrategyContext, StrategyResult
from deployments.utils.mulvaney_cta import PARAMS_BEST, latest_book

STRATEGY_ID = "id22"
REBALANCING_STYLE = "freq_based"
RUN_FREQUENCY = "1d"
NAME = "Mulvaney replica PSA-best (IS peak, long-only, lag 0)"


def build(context: StrategyContext) -> StrategyResult:
    targets, meta = latest_book(context.as_of, PARAMS_BEST)
    print(
        f"{STRATEGY_ID} psa-best: live={meta['n_live']} "
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
            "variant": "psa_best",
            "purpose": "signal_efficacy",
            "selection_note": "IS PSA peak after 7200 cells; DSR applies to family N=7201",
            **meta,
        },
    )
