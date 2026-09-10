"""De Nicola 2h fade-the-move (k=0) — signal-efficacy incubation.

Canonical paper reconstruction: fade the last closed 2h close-to-close return
for the next 2h bar. Always-in. No jump gate.

Live cadence is even UTC hours via deployments/scripts/run_hourly_ohlcv_and_id13.sh
(after the 1h scrape). STF is run-once per invocation; it does not self-schedule.
Rebalance style is on_sign_change: same-sign rolls are mark-only, flips trade.

This id exists to monitor live signal efficacy on the incubator dashboard
(Signal simulation), not capacity / partial-fill performance.

Lab run: thequantgpt-wrapper/runs/btc_denicola_intraday_fade
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from deployments.data_loader import load_binance_ohlcv
from deployments.strategy_types import StrategyContext, StrategyResult

STRATEGY_ID = "id13"
SYMBOL = "BTCUSDT"
REBALANCING_STYLE = "on_sign_change"
RUN_FREQUENCY = "2h"
JUMP_K = 0.0


def _as_utc(ts: pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _load_btc_1h() -> pd.DataFrame:
    df = load_binance_ohlcv("1h")
    btc = df.loc[df["asset"] == SYMBOL].copy()
    if btc.empty:
        raise ValueError("No BTCUSDT rows in binance_futures_ohlcv_1h.parquet")
    btc["open_time"] = pd.to_datetime(btc["open_time"], utc=True)
    return btc.set_index("open_time").sort_index()


def _closed_1h(ohlcv: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    as_of = _as_utc(as_of)
    idx = ohlcv.index
    if idx.tz is None:
        ohlcv = ohlcv.copy()
        ohlcv.index = idx.tz_localize("UTC")
        idx = ohlcv.index
    return ohlcv.loc[idx + pd.Timedelta(hours=1) <= as_of]


def _to_2h(ohlcv_1h: pd.DataFrame) -> pd.DataFrame:
    return (
        ohlcv_1h.resample("2h")
        .agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        .dropna(subset=["open", "close"])
    )


def latest_fade_signal(ohlcv_1h: pd.DataFrame, as_of: pd.Timestamp) -> dict:
    """Last *closed* 2h fade: direction held from that close to the next 2h close."""
    closed = _closed_1h(ohlcv_1h, as_of)
    if len(closed) < 4:
        raise ValueError("Not enough closed 1h BTCUSDT bars for a 2h fade signal")

    last_1h_close = closed.index.max() + pd.Timedelta(hours=1)
    last_2h_end = last_1h_close.floor("2h")
    complete_1h = closed.loc[: last_2h_end - pd.Timedelta(hours=1)]
    bars_2h = _to_2h(complete_1h)
    if len(bars_2h) < 2:
        raise ValueError("Not enough complete 2h bars for a fade return")

    last_bar = bars_2h.iloc[-1]
    prev_close = float(bars_2h["close"].iloc[-2])
    last_close = float(last_bar["close"])
    if prev_close <= 0:
        raise ValueError("Non-positive previous 2h close")
    ret = last_close / prev_close - 1.0
    if not np.isfinite(ret) or ret == 0.0:
        direction = 0.0
    else:
        direction = float(-np.sign(ret))

    return {
        "direction": direction,
        "ret_2h": float(ret),
        "bar_open": bars_2h.index[-1],
        "bar_close": last_2h_end,
        "close": last_close,
        "prev_close": prev_close,
        "n_2h": int(len(bars_2h)),
    }


def current_exposure(as_of: pd.Timestamp) -> tuple[dict[str, float], dict]:
    signal = latest_fade_signal(_load_btc_1h(), as_of)
    direction = float(signal["direction"])
    targets = {SYMBOL: direction} if direction != 0.0 else {}
    return targets, signal


def build(context: StrategyContext) -> StrategyResult:
    targets, signal = current_exposure(context.as_of)
    signal_ts = _as_utc(signal["bar_close"]).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(
        f"{STRATEGY_ID} fade k=0: bar {signal['bar_open']} → {signal['bar_close']} "
        f"ret={signal['ret_2h']:.6f} direction={signal['direction']:+.0f} "
        f"close={signal['close']:.2f}"
    )
    return StrategyResult(
        strategy_id=STRATEGY_ID,
        portfolio=None,
        current_exposure=targets,
        rebalancing_style=REBALANCING_STYLE,
        signal_timestamp=signal_ts,
        run_frequency=RUN_FREQUENCY,
        metadata={
            "name": "BTCUSDT De Nicola 2h fade-the-move (k=0)",
            "lab_run": "btc_denicola_intraday_fade",
            "jump_k": JUMP_K,
            "purpose": "signal_efficacy",
            "ret_2h": signal["ret_2h"],
            "bar_open": str(signal["bar_open"]),
            "bar_close": str(signal["bar_close"]),
        },
    )
