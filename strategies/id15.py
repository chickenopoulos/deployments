"""SPY SMA(200) trend sleeve of the QS simple portfolio reconstruction."""

from __future__ import annotations

from deployments.strategy_types import StrategyContext, StrategyResult
from deployments.utils.spy_qs_portfolio import SYMBOL, latest_book

STRATEGY_ID = "id15"
REBALANCING_STYLE = "on_sign_change"
RUN_FREQUENCY = "1d"
NAME = "SPY SMA(200) trend sleeve"


def build(context: StrategyContext) -> StrategyResult:
    targets, bar_ts, meta = latest_book(context.as_of, sleeves=["sma200"])
    signal_ts = bar_ts.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    print(
        f"{STRATEGY_ID} sma200: bar={meta['bar_open']} close={meta['close']:.2f} "
        f"on={meta['sleeves_on']['sma200']} target={targets}"
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
            "sleeve": "sma200",
            "purpose": "signal_efficacy",
            **meta,
        },
    )
