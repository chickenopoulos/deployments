"""All-names EW overnight continuation of the Concretum daily vol-breakout analog.

Lab run: thequantgpt-wrapper/runs/etf_concretum_tf_rank
Mapping A, after US cash close. Primary incubator book (OOS analog held up).
"""

from __future__ import annotations

from deployments.strategy_types import StrategyContext, StrategyResult
from deployments.utils.etf_concretum_daily import latest_book

STRATEGY_ID = "id18"
REBALANCING_STYLE = "on_sign_change"
RUN_FREQUENCY = "1d"
NAME = "ETF49 Concretum analog overnight, all-names EW"
BOOK = "all_ew"


def build(context: StrategyContext) -> StrategyResult:
    targets, bar_ts, meta = latest_book(context.as_of, book=BOOK)
    signal_ts = bar_ts.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    print(
        f"{STRATEGY_ID} {BOOK}: bar={meta['bar_open']} "
        f"active={meta['n_active']} longs={meta['longs']} shorts={meta['shorts']}"
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
            "lab_run": meta["lab_run"],
            "book": BOOK,
            "purpose": "signal_efficacy",
            "role": "primary",
            **meta,
        },
    )
