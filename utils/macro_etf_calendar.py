"""Robot James macro-ETF calendar for STF id31.

Lab run: thequantgpt-wrapper/runs/rj_macro_etf_calendar
Public reconstruction (Colab paywalled):
  Always-on TLT turn-of-month (long last 5 trading days, short first 5).
  SPY overlay signed by 60/40 SPY/IEF implied bond_trade from prior month-end
  close to the sixth-last close. IEF is signal-only.

Overnight STF book after the last *closed* US cash session (16:00 America/New_York):
  after sixth-last close through 2nd-last close → EOM book
  after month-end close through 4th session of next month → SOM reverse
  after 5th session close → flat
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from deployments.data_loader import load_yfinance_ohlcv
from deployments.strategy_types import StrategyContext, StrategyResult
from deployments.utils.stf_targets import declared_weights

LAB_RUN = "rj_macro_etf_calendar"
STRATEGY_ID = "id31"
NAME = "Macro ETF calendar (TLT ToM + SPY 60/40 overlay)"
TRADE = ("TLT", "SPY")
SIGNAL = "IEF"
WINDOW = 5
W_STOCK = 0.60
W_BOND = 0.40
SESSION_TZ = "America/New_York"
CASH_CLOSE = pd.Timedelta(hours=16)
REBALANCING_STYLE = "on_sign_change"
RUN_FREQUENCY = "1d"


def implied_rebalance_trades(
    stock_return: float,
    bond_return: float,
    target_stock_weight: float = W_STOCK,
    target_bond_weight: float = W_BOND,
) -> tuple[float, float]:
    stock_value = target_stock_weight * (1.0 + stock_return)
    bond_value = target_bond_weight * (1.0 + bond_return)
    portfolio_value = stock_value + bond_value
    current_stock = stock_value / portfolio_value
    current_bond = bond_value / portfolio_value
    return float(target_stock_weight - current_stock), float(target_bond_weight - current_bond)


def _as_utc(ts: pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _as_utc_index(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    if index.tz is None:
        return index.tz_localize("UTC")
    return index.tz_convert("UTC")


def cash_close_utc(open_time: pd.Timestamp) -> pd.Timestamp:
    ny = _as_utc(open_time).tz_convert(SESSION_TZ)
    return (ny.normalize() + CASH_CLOSE).tz_convert("UTC")


def load_macro_ohlcv() -> pd.DataFrame:
    df = load_yfinance_ohlcv("1d")
    out = df.copy()
    out["asset"] = out["asset"].astype(str).str.upper()
    keep = set(TRADE) | {SIGNAL}
    out = out.loc[out["asset"].isin(keep)].copy()
    if out.empty:
        raise ValueError("No SPY/TLT/IEF rows in yfinance_ohlcv_1d.parquet")
    out["open_time"] = pd.to_datetime(out["open_time"], utc=True)
    return out.sort_values(["asset", "open_time"])


def closed_panel(ohlcv: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    as_of_ny = _as_utc(as_of).tz_convert(SESSION_TZ)
    idx = pd.to_datetime(ohlcv["open_time"], utc=True)
    session_ny = idx.dt.tz_convert(SESSION_TZ)
    close_ts = session_ny.dt.normalize() + CASH_CLOSE
    closed = ohlcv.loc[close_ts <= as_of_ny].copy()
    if closed.empty:
        raise ValueError(f"No closed SPY/TLT/IEF daily bars as of {as_of_ny}")
    return closed


def pivot_close(ohlcv: pd.DataFrame) -> pd.DataFrame:
    frame = ohlcv.copy()
    frame["open_time"] = pd.to_datetime(frame["open_time"], utc=True)
    frame["asset"] = frame["asset"].astype(str).str.upper()
    close = (
        frame.pivot_table(index="open_time", columns="asset", values="close", aggfunc="last")
        .sort_index()
        .astype(float)
    )
    missing = [c for c in (*TRADE, SIGNAL) if c not in close.columns]
    if missing:
        raise ValueError(f"Missing assets in yfinance panel: {missing}")
    return close[list((*TRADE, SIGNAL))].dropna()


def days_from_month_end(index: pd.DatetimeIndex) -> np.ndarray:
    """Session days remaining until that month's last trading day (0 = last day).

    Completed months use the last bar actually present. The current incomplete
    month uses the calendar last weekday so a mid-month live run does not treat
    the latest bar as month-end. Same rule as spy_qs_portfolio.
    """
    ny = _as_utc_index(index).tz_convert(SESSION_TZ)
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


def day_of_month(index: pd.DatetimeIndex) -> np.ndarray:
    ny = _as_utc_index(index).tz_convert(SESSION_TZ)
    years = ny.year.to_numpy()
    months = ny.month.to_numpy()
    n = len(index)
    dom = np.empty(n, dtype=np.int16)
    i = 0
    while i < n:
        y, m = int(years[i]), int(months[i])
        j = i
        while j < n and int(years[j]) == y and int(months[j]) == m:
            j += 1
        for k, pos in enumerate(range(i, j)):
            dom[pos] = k + 1
        i = j
    return dom


def _month_key(ts: pd.Timestamp) -> tuple[int, int]:
    ny = _as_utc(ts).tz_convert(SESSION_TZ)
    return int(ny.year), int(ny.month)


def _prev_month_key(key: tuple[int, int]) -> tuple[int, int]:
    y, m = key
    if m == 1:
        return y - 1, 12
    return y, m - 1


def bond_trade_by_month(close: pd.DataFrame, dfe: np.ndarray) -> dict[tuple[int, int], float]:
    idx = close.index
    month_end_loc: dict[tuple[int, int], int] = {}
    sixth_loc: dict[tuple[int, int], int] = {}
    for i, ts in enumerate(idx):
        key = _month_key(ts)
        if int(dfe[i]) == 0:
            month_end_loc[key] = i
        if int(dfe[i]) == WINDOW:
            sixth_loc[key] = i
    out: dict[tuple[int, int], float] = {}
    for key, sixth_i in sixth_loc.items():
        prev = _prev_month_key(key)
        prev_i = month_end_loc.get(prev)
        if prev_i is None:
            continue
        spy_p = float(close["SPY"].iloc[sixth_i] / close["SPY"].iloc[prev_i] - 1.0)
        ief_p = float(close["IEF"].iloc[sixth_i] / close["IEF"].iloc[prev_i] - 1.0)
        _stock, bond = implied_rebalance_trades(spy_p, ief_p)
        out[key] = float(bond)
    return out


def overnight_weights(close: pd.DataFrame) -> pd.DataFrame:
    """Target after each bar's cash close (STF live book)."""
    idx = close.index
    dfe = days_from_month_end(idx)
    dom = day_of_month(idx)
    pressure = bond_trade_by_month(close, dfe)
    tlt = np.zeros(len(idx), dtype=float)
    spy = np.zeros(len(idx), dtype=float)
    windows = np.array(["flat"] * len(idx), dtype=object)
    for i, ts in enumerate(idx):
        key = _month_key(ts)
        d = int(dfe[i])
        n = int(dom[i])
        if d == WINDOW or 1 <= d <= (WINDOW - 1):
            windows[i] = "eom"
            bond = pressure.get(key, 0.0)
            tlt[i] = 1.0
            spy[i] = -float(np.sign(bond)) if bond != 0.0 else 0.0
        elif d == 0 or 1 <= n <= (WINDOW - 1):
            windows[i] = "som"
            src = key if d == 0 else _prev_month_key(key)
            bond = pressure.get(src, 0.0)
            tlt[i] = -1.0
            spy[i] = float(np.sign(bond)) if bond != 0.0 else 0.0
        else:
            windows[i] = "flat"
    out = pd.DataFrame({"TLT": tlt, "SPY": spy}, index=idx)
    out.attrs["window"] = pd.Series(windows, index=idx)
    out.attrs["dfe"] = pd.Series(dfe, index=idx)
    out.attrs["dom"] = pd.Series(dom, index=idx)
    out.attrs["bond_trade"] = pressure
    return out


def _targets_from_row(row: pd.Series) -> dict[str, float]:
    return declared_weights(TRADE, {str(k): float(v) for k, v in row.items()})


def latest_book(
    as_of: pd.Timestamp,
    ohlcv: pd.DataFrame | None = None,
) -> tuple[dict[str, float], pd.Timestamp, dict[str, Any]]:
    raw = ohlcv if ohlcv is not None else load_macro_ohlcv()
    closed = closed_panel(raw, as_of)
    close = pivot_close(closed)
    weights = overnight_weights(close)
    last_ts = pd.Timestamp(close.index[-1])
    row = weights.iloc[-1]
    targets = _targets_from_row(row)
    window = str(weights.attrs["window"].iloc[-1])
    dfe = int(weights.attrs["dfe"].iloc[-1])
    dom = int(weights.attrs["dom"].iloc[-1])
    key = _month_key(last_ts)
    src = key if window == "eom" or (window == "som" and dfe == 0) else _prev_month_key(key)
    bond = float(weights.attrs["bond_trade"].get(src, 0.0)) if window != "flat" else 0.0
    close_ts = cash_close_utc(last_ts)
    meta = {
        "name": NAME,
        "lab_run": LAB_RUN,
        "purpose": "signal_efficacy",
        "window": window,
        "dfe": dfe,
        "dom": dom,
        "bond_trade": bond,
        "tlt": float(row["TLT"]),
        "spy": float(row["SPY"]),
        "bar_open": str(last_ts),
        "close_time": str(close_ts),
        "n_bars": int(len(close)),
        "tlt_close": float(close["TLT"].iloc[-1]),
        "spy_close": float(close["SPY"].iloc[-1]),
        "ief_close": float(close["IEF"].iloc[-1]),
    }
    return targets, last_ts, meta


def build(context: StrategyContext) -> StrategyResult:
    targets, bar_ts, meta = latest_book(context.as_of)
    signal_ts = cash_close_utc(bar_ts).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(
        f"{STRATEGY_ID} calendar: window={meta['window']} "
        f"TLT={meta['tlt']:+.0f} SPY={meta['spy']:+.0f} "
        f"dfe={meta['dfe']} dom={meta['dom']} "
        f"bond_trade={meta['bond_trade']:+.4f} bar={meta['bar_open']}"
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
