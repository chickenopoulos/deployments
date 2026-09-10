"""Quantified Strategies-style SPY overlay reconstruction (lab: spy_simple_portfolio).

Legs:
  - sma200: long while close > SMA(200)
  - ldom: enter 4th-last trading day; hold 6 sessions
  - monday_2down: Monday after two down closes; exit close > prior high

Overlay is long 100% if any sleeve is on. Signals use last *closed* US cash session.
"""

from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from deployments.data_loader import load_yfinance_ohlcv

SYMBOL = "SPY"
SMA_WINDOW = 200
LDOM_DFE = 3
LDOM_HOLD = 6
SESSION_TZ = "America/New_York"
CASH_CLOSE = pd.Timedelta(hours=16)
SLEEVES = ("sma200", "ldom", "monday_2down")


def _as_utc(ts: pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def load_spy_ohlcv() -> pd.DataFrame:
    df = load_yfinance_ohlcv("1d")
    spy = df.loc[df["asset"].astype(str).str.upper() == SYMBOL].copy()
    if spy.empty:
        raise ValueError("No SPY rows in yfinance_ohlcv_1d.parquet")
    spy["open_time"] = pd.to_datetime(spy["open_time"], utc=True)
    return spy.set_index("open_time").sort_index()


def closed_ohlcv(ohlcv: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Keep bars whose regular-session close (16:00 America/New_York) is <= as_of."""
    as_of_ny = _as_utc(as_of).tz_convert(SESSION_TZ)
    idx = ohlcv.index
    if idx.tz is None:
        ohlcv = ohlcv.copy()
        ohlcv.index = pd.to_datetime(idx, utc=True)
        idx = ohlcv.index
    session_ny = idx.tz_convert(SESSION_TZ)
    close_ts = session_ny.normalize() + CASH_CLOSE
    closed = ohlcv.loc[close_ts <= as_of_ny]
    if closed.empty:
        raise ValueError(f"No closed SPY daily bars as of {as_of_ny}")
    return closed


def _days_from_month_end(index: pd.DatetimeIndex) -> np.ndarray:
    """Session days remaining until that month's last trading day (0 = last day).

    Completed months use the last bar actually present. The current incomplete
    month uses the calendar last weekday so a mid-month live run does not treat
    the latest bar as month-end.
    """
    ny = index.tz_convert(SESSION_TZ)
    years = ny.year.to_numpy()
    months = ny.month.to_numpy()
    n = len(index)
    dfe = np.empty(n, dtype=np.int16)
    i = 0
    while i < n:
        y, m = int(years[i]), int(months[i])
        j = i
        while j < n and int(years[j]) == y and int(months[j]) == m:
            j += 1
        complete = j < n
        if complete:
            last = j - 1
            for pos in range(i, j):
                dfe[pos] = last - pos
        else:
            month_end = (pd.Timestamp(year=y, month=m, day=1) + pd.offsets.BMonthEnd(0)).date()
            for pos in range(i, j):
                ts_date = ny[pos].date()
                dfe[pos] = int(len(pd.bdate_range(ts_date, month_end, freq="B")) - 1)
        i = j
    return dfe


def _overnight_from_entry_exit(entry: np.ndarray, exit_: np.ndarray) -> np.ndarray:
    n = entry.shape[0]
    pos = np.zeros(n, dtype=bool)
    in_pos = False
    entry_i = -1
    for i in range(n):
        if in_pos and exit_[i] and i != entry_i:
            in_pos = False
        if (not in_pos) and entry[i]:
            in_pos = True
            entry_i = i
        pos[i] = in_pos
    return pos


def _hold_n_position(entry: np.ndarray, hold: int) -> np.ndarray:
    n = entry.shape[0]
    pos = np.zeros(n, dtype=bool)
    in_pos = False
    entry_i = -1
    for i in range(n):
        if in_pos and (i - entry_i) >= hold:
            in_pos = False
        if (not in_pos) and entry[i]:
            in_pos = True
            entry_i = i
        pos[i] = in_pos
    return pos


def sleeve_wants(ohlcv: pd.DataFrame) -> dict[str, pd.Series]:
    close = ohlcv["close"].astype(float)
    high = ohlcv["high"].astype(float)
    sma = close.rolling(SMA_WINDOW).mean()
    dfe = _days_from_month_end(close.index)
    wd = close.index.tz_convert(SESSION_TZ).weekday.to_numpy()
    ret1 = close.pct_change().to_numpy()
    two_down = (ret1 < 0) & (np.roll(ret1, 1) < 0)
    two_down[0] = False
    prior_high = high.shift(1).to_numpy()
    qs_exit = np.nan_to_num(close.to_numpy() > prior_high, nan=0.0).astype(bool)
    trend = (close > sma).fillna(False).to_numpy()
    ldom = _hold_n_position(dfe == LDOM_DFE, LDOM_HOLD)
    monday = _overnight_from_entry_exit((wd == 0) & two_down, qs_exit)
    idx = close.index
    return {
        "sma200": pd.Series(trend, index=idx),
        "ldom": pd.Series(ldom, index=idx),
        "monday_2down": pd.Series(monday, index=idx),
    }


def overlay_want(sleeves: dict[str, pd.Series]) -> pd.Series:
    want = sleeves["sma200"].astype(bool)
    return (want | sleeves["ldom"].astype(bool) | sleeves["monday_2down"].astype(bool)).fillna(False)


def _exposure_from_flag(on: bool) -> dict[str, float]:
    return {SYMBOL: 1.0} if on else {}


def latest_book(
    as_of: pd.Timestamp,
    sleeves: Iterable[str] | None = None,
    ohlcv: pd.DataFrame | None = None,
) -> tuple[dict[str, float], pd.Timestamp, dict]:
    """Return overlay or single-sleeve exposure on the last closed session."""
    raw = ohlcv if ohlcv is not None else load_spy_ohlcv()
    closed = closed_ohlcv(raw, as_of)
    wants = sleeve_wants(closed)
    names = list(sleeves) if sleeves is not None else list(SLEEVES)
    unknown = [name for name in names if name not in wants]
    if unknown:
        raise ValueError(f"Unknown sleeve(s): {unknown}")
    if set(names) == set(SLEEVES):
        flag = bool(overlay_want(wants).iloc[-1])
        kind = "overlay"
    elif len(names) == 1:
        flag = bool(wants[names[0]].iloc[-1])
        kind = names[0]
    else:
        flag = bool(pd.concat([wants[n] for n in names], axis=1).any(axis=1).iloc[-1])
        kind = "+".join(names)
    bar_ts = pd.Timestamp(closed.index[-1])
    meta = {
        "kind": kind,
        "bar_open": str(bar_ts),
        "close": float(closed["close"].iloc[-1]),
        "sleeves_on": {name: bool(wants[name].iloc[-1]) for name in SLEEVES},
        "n_bars": int(len(closed)),
    }
    return _exposure_from_flag(flag), bar_ts, meta
