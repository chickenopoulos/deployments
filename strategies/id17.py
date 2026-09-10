"""SPY Monday two-down sleeve: enter Monday after two down closes; QS prior-high exit."""

from __future__ import annotations

from deployments.strategy_types import StrategyContext, StrategyResult
from deployments.utils.spy_qs_portfolio import SYMBOL, latest_book

STRATEGY_ID = "id17"
REBALANCING_STYLE = "on_sign_change"
RUN_FREQUENCY = "1d"
NAME = "SPY Monday 2-down QS-exit sleeve"


def build(context: StrategyContext) -> StrategyResult:
    targets, bar_ts, meta = latest_book(context.as_of, sleeves=["monday_2down"])
    signal_ts = bar_ts.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    print(
        f"{STRATEGY_ID} monday_2down: bar={meta['bar_open']} close={meta['close']:.2f} "
        f"on={meta['sleeves_on']['monday_2down']} target={targets}"
    )
    return StrategyResult(
        strategy_id=STRATEGY_ID,
        portfolio=None,
        current_exposure=targets,
        rebalancing_style=REBALANCING_STYLE,
        signal_timestamp=signal_ts,
        run_frequency=RUN_FREQUENCY,
        metadata={
            "name": NAME,
            "lab_run": "spy_simple_portfolio",
            "symbol": SYMBOL,
            "sleeve": "monday_2down",
            "purpose": "signal_efficacy",
            **meta,
        },
    )
