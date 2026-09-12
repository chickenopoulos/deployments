"""ES High10 lag-1 PSA representative for STF id32.

Frozen lab representative (not canonical High10, not the newsletter):
  lookback=12, IBS entry=0.25, IBS exit=0.90, hold=5, lag=1.
  Entry: session high > prior 12-day high AND IBS < 0.25, filled next bar.
  Exit:  IBS > 0.90, else time stop 5 bars after the lagged fill.

Canonical High10 (10 / 0.20 / 0.90 / 5) stays in the lab run. This book is
the in-sample PSA median-stable cell at lag 1. Yahoo ES=F is the same proxy
id21/id22/id30 already scrape. Purpose: signal efficacy (apply_funding: false).

Lab run: thequantgpt-wrapper/runs/sp500_breakout_high10
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd

from deployments.paths import STATE_DIR
from deployments.strategy_types import StrategyContext, StrategyResult
from deployments.utils.stf_targets import declared_weights
from deployments.utils.turnaround_wednesday import (
    closed_es,
    load_es_ohlcv,
    overnight_after_close,
    session_stamp,
)

LAB_RUN = "sp500_breakout_high10"
STRATEGY_ID = "id32"
YAHOO = "ES=F"
LOOKBACK = 12
IBS_ENTRY = 0.25
IBS_EXIT = 0.90
HOLD_BARS = 5
LAG = 1
REBALANCING_STYLE = "on_sign_change"
RUN_FREQUENCY = "1d"
NAME = "ES High10 PSA representative (lag 1)"
STATE_FILE = STATE_DIR / "sp500_breakout_high10.json"


def _as_utc(ts: pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _ibs(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    rng = (high - low).replace(0.0, np.nan)
    return ((close - low) / rng).fillna(0.5)


def _ibs_or_hold_exits(
    entries: pd.Series,
    ibs: pd.Series,
    hold_bars: int = HOLD_BARS,
    ibs_exit: float = IBS_EXIT,
) -> pd.Series:
    e = entries.fillna(False).astype(bool).to_numpy()
    strong = (ibs > ibs_exit).fillna(False).astype(bool).to_numpy()
    x = np.zeros(len(e), dtype=bool)
    in_pos = False
    held = 0
    for i in range(len(e)):
        if not in_pos:
            if bool(e[i]):
                in_pos = True
                held = 0
        else:
            held += 1
            if bool(strong[i]) or held >= hold_bars:
                x[i] = True
                in_pos = False
                held = 0
    return pd.Series(x, index=entries.index, dtype=bool)


def entries_exits(ohlcv: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    high = ohlcv["high"].astype(float)
    low = ohlcv["low"].astype(float)
    close = ohlcv["close"].astype(float)
    ibs = _ibs(high, low, close)
    don = high.rolling(LOOKBACK).max().shift(1)
    entry_raw = ((high > don) & (ibs < IBS_ENTRY)).fillna(False).astype(bool)
    entries = (
        entry_raw.shift(LAG, fill_value=False).astype(bool) if LAG > 0 else entry_raw
    )
    exits = _ibs_or_hold_exits(entries, ibs)
    return entries, exits, entry_raw


def latest_book(
    as_of: pd.Timestamp,
    ohlcv: pd.DataFrame | None = None,
) -> tuple[dict[str, float], pd.Timestamp, dict[str, Any]]:
    raw = ohlcv if ohlcv is not None else load_es_ohlcv()
    closed = closed_es(raw, as_of)
    entries, exits, entry_raw = entries_exits(closed)
    overnight = overnight_after_close(entries, exits)
    last = closed.iloc[-1]
    flag = bool(overnight.iloc[-1] > 0)
    bar_ts = pd.Timestamp(closed.index[-1])
    close_ts = pd.Timestamp(last["close_time"]) if "close_time" in closed.columns else bar_ts
    high = float(last["high"])
    low = float(last["low"])
    close = float(last["close"])
    rng = high - low
    ibs = 0.5 if rng == 0 else (close - low) / rng
    prior_high = (
        float(closed["high"].iloc[-LOOKBACK - 1 : -1].max())
        if len(closed) > LOOKBACK
        else float("nan")
    )
    targets = declared_weights([YAHOO], {YAHOO: 1.0} if flag else {})
    meta = {
        "name": NAME,
        "lab_run": LAB_RUN,
        "symbol": YAHOO,
        "purpose": "signal_efficacy",
        "variant": "psa_representative_lag1",
        "not_canonical": True,
        "execution_lag": LAG,
        "lookback": LOOKBACK,
        "ibs_entry": IBS_ENTRY,
        "ibs_exit": IBS_EXIT,
        "hold_bars": HOLD_BARS,
        "bar_open": str(bar_ts),
        "close_time": str(close_ts),
        "close": close,
        "high": high,
        "low": low,
        "prior_12d_high": prior_high,
        "ibs": float(ibs),
        "weekday": int(session_stamp(pd.DatetimeIndex([bar_ts]))[0].weekday()),
        "setup_today": bool(entry_raw.iloc[-1]),
        "entered": bool(entries.iloc[-1]),
        "exited": bool(exits.iloc[-1]),
        "in_position": flag,
        "target": 1.0 if flag else 0.0,
        "n_bars": int(len(closed)),
    }
    return targets, close_ts, meta


def persist_signal(meta: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {}
    if STATE_FILE.exists():
        payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    payload[STRATEGY_ID] = meta
    payload["_updated_utc"] = pd.Timestamp.now(tz="UTC").isoformat()
    STATE_FILE.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def build(context: StrategyContext) -> StrategyResult:
    targets, bar_ts, meta = latest_book(context.as_of)
    persist_signal(meta)
    signal_ts = _as_utc(bar_ts).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(
        f"{STRATEGY_ID} {YAHOO} bar={meta['bar_open']} close={meta['close']:.2f} "
        f"ibs={meta['ibs']:.3f} setup={meta['setup_today']} "
        f"in_pos={meta['in_position']} target={targets}"
    )
    return StrategyResult(
        strategy_id=STRATEGY_ID,
        portfolio=None,
        current_exposure=targets,
        rebalancing_style=REBALANCING_STYLE,
        signal_timestamp=signal_ts,
        run_frequency=RUN_FREQUENCY,
        metadata=meta,
    )
