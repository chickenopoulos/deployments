"""Correlation-regime spread-weighted market-neutral portfolio (always-in)."""

from __future__ import annotations

import vectorbt as vbt

from deployments.strategy_types import StrategyContext, StrategyResult
from deployments.utils.corr_regime import FEE, SLIPPAGE, compute_signal_frame, latest_exposure, load_close_panel

STRATEGY_ID = "id12"
REBALANCING_STYLE = "freq_based"
RUN_FREQUENCY = "1d"


def get_pf():
    close = load_close_panel()
    weights, _ = compute_signal_frame(close)
    return vbt.Portfolio.from_orders(
        close=close,
        size=weights,
        size_type="targetpercent",
        init_cash=100,
        cash_sharing=True,
        group_by=True,
        call_seq="auto",
        fees=FEE + SLIPPAGE,
    )


def get_curr_exp(pf) -> dict[str, float]:
    del pf  # exposure comes from signal weights, not vbt asset signs
    weights, _ = compute_signal_frame()
    return latest_exposure(weights)


def build(context: StrategyContext) -> StrategyResult:
    pf = get_pf()
    return StrategyResult(
        strategy_id=STRATEGY_ID,
        portfolio=pf,
        current_exposure=get_curr_exp(pf),
        rebalancing_style=REBALANCING_STYLE,
        signal_timestamp=context.as_of.normalize().isoformat().replace("+00:00", "Z"),
        run_frequency=RUN_FREQUENCY,
    )
