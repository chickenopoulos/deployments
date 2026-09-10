"""SPY overlay: SMA(200) OR LDOM hold-6 OR Monday 2-down (QS reconstruction).

Lab run: thequantgpt-wrapper/runs/spy_simple_portfolio
Cadence: daily after US cash close via deployments/scripts/run_daily_spy_portfolio.sh
"""

from __future__ import annotations

from deployments.strategy_types import StrategyContext, StrategyResult
from deployments.utils.spy_qs_portfolio import SYMBOL, latest_book

STRATEGY_ID = "id14"
REBALANCING_STYLE = "on_sign_change"
RUN_FREQUENCY = "1d"
NAME = "SPY QS overlay (SMA200 + LDOM + Monday 2-down)"


def build(context: StrategyContext) -> StrategyResult:
    targets, bar_ts, meta = latest_book(context.as_of)
    signal_ts = bar_ts.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    print(
        f"{STRATEGY_ID} overlay: bar={meta['bar_open']} close={meta['close']:.2f} "
        f"sleeves={meta['sleeves_on']} target={targets}"
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
            "purpose": "signal_efficacy",
            **meta,
        },
    )
