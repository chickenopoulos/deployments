"""ES Turnaround Wednesday, lag-0, for STF id30.

Frozen reconstruction (lab: es_turnaround_wednesday). Not newsletter EasyLanguage.
  Entry: Tuesday AND close < prior close AND IBS < 0.25 (same-bar / MOC).
  Exit:  first close > prior bar's high, else time stop after 5 bars.
  Long-only, fully funded 1.0 on Yahoo ES=F.

Yahoo ES=F is the same continuous proxy id21/id22 already scrape. This is not
TradeStation @ES.D. Purpose: signal efficacy (apply_funding: false).
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd

from deployments.data_loader import load_yfinance_ohlcv
from deployments.paths import STATE_DIR
from deployments.strategy_types import StrategyContext, StrategyResult
from deployments.utils.mulvaney_universe import bar_close_utc, canonical_yahoo
from deployments.utils.stf_targets import declared_weights

LAB_RUN = "es_turnaround_wednesday"
STRATEGY_ID = "id30"
YAHOO = "ES=F"
ENTRY_WEEKDAY = 1  # Tuesday (Mon=0)
IBS_THRESH = 0.25
HOLD_BARS = 5
REBALANCING_STYLE = "on_sign_change"
RUN_FREQUENCY = "1d"
NAME = "ES Turnaround Wednesday (lag 0)"
STATE_FILE = STATE_DIR / "turnaround_wednesday.json"


def _as_utc(ts: pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _as_utc_index(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    if index.tz is None:
        return index.tz_localize("UTC")
    return index.tz_convert("UTC")


def session_stamp(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Yahoo ES=F daily bars are session dates, usually NY midnight."""
    return _as_utc_index(index).tz_convert("America/New_York")


def session_close_utc(open_time: pd.Timestamp) -> pd.Timestamp:
    """CME day-session close (17:00 CT) on the Yahoo bar's NY calendar date."""
    return bar_close_utc(open_time, YAHOO)


def _ibs(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    rng = (high - low).replace(0.0, np.nan)
    return ((close - low) / rng).fillna(0.5)


def _qs_or_hold_exits(
    entries: pd.Series,
    close: pd.Series,
    high: pd.Series,
    hold_bars: int = HOLD_BARS,
) -> pd.Series:
    e = entries.fillna(False).astype(bool).to_numpy()
    qs = (close > high.shift(1)).fillna(False).astype(bool).to_numpy()
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
            if bool(qs[i]) or held >= hold_bars:
                x[i] = True
                in_pos = False
                held = 0
    return pd.Series(x, index=entries.index, dtype=bool)


def _in_bar_position(entries: pd.Series, exits: pd.Series) -> pd.Series:
    """Long through the close of the exit bar (lab / vectorbt from_signals)."""
    e = entries.fillna(False).astype(bool).to_numpy()
    x = exits.fillna(False).astype(bool).to_numpy()
    pos = np.zeros(len(e), dtype=float)
    p = 0.0
    for i in range(len(e)):
        if p == 0.0 and bool(e[i]):
            p = 1.0
        pos[i] = p
        if p == 1.0 and bool(x[i]):
            p = 0.0
    return pd.Series(pos, index=entries.index)


def overnight_after_close(entries: pd.Series, exits: pd.Series) -> pd.Series:
    """1.0 if still long after that bar's close (STF live book)."""
    in_bar = _in_bar_position(entries, exits)
    x = exits.fillna(False).astype(bool)
    return (in_bar.astype(bool) & ~x).astype(float)


def entries_exits(ohlcv: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    close = ohlcv["close"].astype(float)
    high = ohlcv["high"].astype(float)
    low = ohlcv["low"].astype(float)
    wd = session_stamp(close.index).weekday
    ibs = _ibs(high, low, close)
    down = close < close.shift(1)
    entries = ((wd == ENTRY_WEEKDAY) & (ibs < IBS_THRESH) & down).fillna(False).astype(bool)
    exits = _qs_or_hold_exits(entries, close, high)
    return entries, exits


def load_es_ohlcv() -> pd.DataFrame:
    df = load_yfinance_ohlcv("1d")
    es = df.loc[df["asset"].astype(str).map(canonical_yahoo) == YAHOO].copy()
    if es.empty:
        raise ValueError("No ES=F rows in yfinance_ohlcv_1d.parquet")
    es["open_time"] = pd.to_datetime(es["open_time"], utc=True)
    if "close_time" in es.columns:
        es["close_time"] = pd.to_datetime(es["close_time"], utc=True)
    indexed = es.set_index("open_time").sort_index()
    return indexed[~indexed.index.duplicated(keep="last")]


def closed_es(ohlcv: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    frame = ohlcv.copy()
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise TypeError("ohlcv index must be DatetimeIndex (open_time)")
    frame.index = _as_utc_index(frame.index)
    frame["close_time"] = [session_close_utc(ts) for ts in frame.index]
    closed = frame.loc[frame["close_time"] <= _as_utc(as_of)]
    if closed.empty:
        raise ValueError(f"No closed daily bars for {YAHOO} as of {_as_utc(as_of)}")
    return closed


def latest_book(
    as_of: pd.Timestamp,
    ohlcv: pd.DataFrame | None = None,
) -> tuple[dict[str, float], pd.Timestamp, dict[str, Any]]:
    raw = ohlcv if ohlcv is not None else load_es_ohlcv()
    closed = closed_es(raw, as_of)
    entries, exits = entries_exits(closed)
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
    prior_close = float(closed["close"].iloc[-2]) if len(closed) > 1 else float("nan")
    targets = declared_weights([YAHOO], {YAHOO: 1.0} if flag else {})
    meta = {
        "name": NAME,
        "lab_run": LAB_RUN,
        "symbol": YAHOO,
        "purpose": "signal_efficacy",
        "execution_lag": 0,
        "entry_weekday": ENTRY_WEEKDAY,
        "ibs_thresh": IBS_THRESH,
        "hold_bars": HOLD_BARS,
        "bar_open": str(bar_ts),
        "close_time": str(close_ts),
        "close": close,
        "high": high,
        "low": low,
        "prior_close": prior_close,
        "ibs": float(ibs),
        "weekday": int(session_stamp(pd.DatetimeIndex([bar_ts]))[0].weekday()),
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
        f"ibs={meta['ibs']:.3f} in_pos={meta['in_position']} target={targets}"
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
