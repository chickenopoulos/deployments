"""Overnight continuation of the lab Concretum daily vol-breakout analog.

Lab run: thequantgpt-wrapper/runs/etf_concretum_tf_rank
Mapping A: after the last closed US cash session, hold today's signed
breakout until the next after-close run. This is not flatten-at-close and
not 1-minute Concretum Bands.

Ranking (top/bottom) uses the lab strategy P&L (fill-at-band, same-day)
with a 60-day Sharpe lagged one bar. Canonical lookbacks stay 60 / 14.
"""

from __future__ import annotations

import math
from typing import Literal

import numpy as np
import pandas as pd

from deployments.data_loader import load_yfinance_ohlcv

Book = Literal["all_ew", "top", "bottom"]

UNIVERSE = [
    "DBA",
    "DBC",
    "DIA",
    "EEM",
    "EFA",
    "EWG",
    "EWJ",
    "EWZ",
    "FXI",
    "GDX",
    "GLD",
    "HYG",
    "IBB",
    "IEF",
    "IJH",
    "INDA",
    "ITA",
    "IWB",
    "IWM",
    "KRE",
    "LQD",
    "QQQ",
    "SHY",
    "SLV",
    "SMH",
    "SOXX",
    "SPY",
    "TIP",
    "TLT",
    "UNG",
    "USO",
    "UUP",
    "VNQ",
    "XBI",
    "XHB",
    "XLB",
    "XLC",
    "XLE",
    "XLF",
    "XLI",
    "XLK",
    "XLP",
    "XLRE",
    "XLU",
    "XLV",
    "XLY",
    "XME",
    "XOP",
    "XRT",
]
LOOKBACK_SIGMA = 14
VM = 1.0
RANK_LOOKBACK = 60
MIN_NAMES = 8
ANN = 252
SQRT_ANN = math.sqrt(ANN)
COST_PER_SHARE = 0.0035 + 0.001
SESSION_TZ = "America/New_York"
CASH_CLOSE = pd.Timedelta(hours=16)
LAB_RUN = "etf_concretum_tf_rank"
# A 49-name scrape can finish with only a handful of names on the newest
# session. Do not let that ragged tail become the live book.
MIN_COVERAGE_FRAC = 0.8


def _as_utc(ts: pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def cash_close_utc(open_time: pd.Timestamp) -> pd.Timestamp:
    ny = _as_utc(open_time).tz_convert(SESSION_TZ)
    return (ny.normalize() + CASH_CLOSE).tz_convert("UTC")


def last_covered_timestamp(close: pd.DataFrame, min_frac: float = MIN_COVERAGE_FRAC) -> pd.Timestamp:
    """Last session whose close panel is wide enough to represent the universe."""
    if close.empty:
        raise ValueError("Empty ETF close panel")
    n_names = int(close.shape[1])
    min_names = max(1, int(math.ceil(float(min_frac) * n_names))) if n_names else 1
    counts = close.notna().sum(axis=1)
    ok = counts[counts >= min_names]
    if ok.empty:
        raise ValueError(
            f"No ETF session with at least {min_names} names "
            f"(panel width={n_names}, last counts={int(counts.iloc[-1]) if len(counts) else 0})"
        )
    return pd.Timestamp(ok.index[-1])


def load_etf_ohlcv() -> pd.DataFrame:
    df = load_yfinance_ohlcv("1d")
    out = df.copy()
    out["asset"] = out["asset"].astype(str).str.upper()
    out = out.loc[out["asset"].isin(UNIVERSE)].copy()
    if out.empty:
        raise ValueError("No reconstructed ETF universe rows in yfinance_ohlcv_1d.parquet")
    out["open_time"] = pd.to_datetime(out["open_time"], utc=True)
    return out.sort_values(["asset", "open_time"])


def closed_panel(ohlcv: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Keep bars whose regular-session close (16:00 America/New_York) is <= as_of."""
    as_of_ny = _as_utc(as_of).tz_convert(SESSION_TZ)
    idx = pd.to_datetime(ohlcv["open_time"], utc=True)
    session_ny = idx.dt.tz_convert(SESSION_TZ)
    close_ts = session_ny.dt.normalize() + CASH_CLOSE
    closed = ohlcv.loc[close_ts <= as_of_ny].copy()
    if closed.empty:
        raise ValueError(f"No closed ETF daily bars as of {as_of_ny}")
    return closed


def pivot_fields(ohlcv: pd.DataFrame) -> dict[str, pd.DataFrame]:
    frame = ohlcv.copy()
    frame["open_time"] = pd.to_datetime(frame["open_time"], utc=True)
    frame["asset"] = frame["asset"].astype(str).str.upper()
    fields = {}
    for col in ("open", "high", "low", "close"):
        fields[col] = (
            frame.pivot_table(index="open_time", columns="asset", values=col, aggfunc="last")
            .sort_index()
            .astype(float)
        )
    return fields


def strategy_returns(fields: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Lab same-day analog returns and today's signed breakout (+1 / -1 / 0)."""
    o = fields["open"].astype(float)
    h = fields["high"].astype(float)
    l_ = fields["low"].astype(float)
    c = fields["close"].astype(float)
    oc = (c / o - 1.0).abs()
    sigma = oc.shift(1).rolling(LOOKBACK_SIGMA, min_periods=LOOKBACK_SIGMA).mean()
    prev_c = c.shift(1)
    ub = np.maximum(o, prev_c) * (1.0 + VM * sigma)
    lb = np.minimum(o, prev_c) * (1.0 - VM * sigma)
    long_hit = h > ub
    short_hit = l_ < lb
    both = long_hit & short_hit
    valid = sigma.notna() & ub.notna() & lb.notna() & (ub > lb)
    long_ok = valid & long_hit & ~both
    short_ok = valid & short_hit & ~both
    long_pnl = c / ub - 1.0
    short_pnl = 1.0 - c / lb
    long_cost = 2.0 * COST_PER_SHARE / ub
    short_cost = 2.0 * COST_PER_SHARE / lb
    r = pd.DataFrame(0.0, index=c.index, columns=c.columns)
    r = r.where(c.notna(), np.nan)
    r = r.mask(long_ok, long_pnl - long_cost)
    r = r.mask(short_ok, short_pnl - short_cost)
    r = r.mask(~valid, np.nan)
    sign = pd.DataFrame(0.0, index=c.index, columns=c.columns)
    sign = sign.where(c.notna(), np.nan)
    sign = sign.mask(long_ok, 1.0)
    sign = sign.mask(short_ok, -1.0)
    sign = sign.mask(~valid, np.nan)
    return r, sign


def rolling_sharpe(r: pd.DataFrame, window: int) -> pd.DataFrame:
    mu = r.rolling(window, min_periods=window).mean()
    sd = r.rolling(window, min_periods=window).std(ddof=1)
    return (mu / sd) * SQRT_ANN


def _selected_mask(lagged_score: pd.Series, book: Book) -> pd.Series:
    avail = lagged_score.dropna()
    n_avail = int(avail.shape[0])
    if book == "all_ew":
        return lagged_score.notna() if n_avail else lagged_score.notna() * False
    if n_avail < MIN_NAMES:
        return pd.Series(False, index=lagged_score.index)
    n_take = max(1, int(round(n_avail * 0.2)))
    top = book == "top"
    ranks = lagged_score.rank(ascending=not top, method="first")
    return ranks.le(n_take) & lagged_score.notna()


def _equal_weight_targets(sign_row: pd.Series, selected: pd.Series) -> dict[str, float]:
    active = sign_row.where(selected.reindex(sign_row.index).fillna(False)).dropna()
    active = active[active != 0.0]
    if active.empty:
        return {}
    weight = 1.0 / float(len(active))
    return {str(sym): float(np.sign(val) * weight) for sym, val in active.items()}


def latest_book(
    as_of: pd.Timestamp,
    book: Book,
    ohlcv: pd.DataFrame | None = None,
) -> tuple[dict[str, float], pd.Timestamp, dict]:
    if book not in {"all_ew", "top", "bottom"}:
        raise ValueError(f"Unknown book: {book}")
    raw = ohlcv if ohlcv is not None else load_etf_ohlcv()
    closed = closed_panel(raw, as_of)
    fields = pivot_fields(closed)
    last_ts = last_covered_timestamp(fields["close"])
    fields = {name: frame.loc[:last_ts] for name, frame in fields.items()}
    strat, sign = strategy_returns(fields)
    score = rolling_sharpe(strat, RANK_LOOKBACK)
    lagged = score.shift(1)
    sign_row = sign.iloc[-1]
    if book == "all_ew":
        selected = sign_row.notna()
    else:
        selected = _selected_mask(lagged.iloc[-1], book)
    targets = _equal_weight_targets(sign_row, selected)
    n_selected = int(selected.fillna(False).sum())
    n_scored = int(lagged.iloc[-1].notna().sum()) if book != "all_ew" else int(sign_row.notna().sum())
    signal_ts = cash_close_utc(last_ts)
    meta = {
        "kind": book,
        "mapping": "A",
        "lab_run": LAB_RUN,
        "bar_open": str(last_ts),
        "close_time": str(signal_ts),
        "n_bars": int(len(sign.index)),
        "n_names_panel": int(sign.shape[1]),
        "n_names_last": int(fields["close"].iloc[-1].notna().sum()),
        "n_scored": n_scored,
        "n_selected": n_selected,
        "n_active": int(len(targets)),
        "lookback_sigma": LOOKBACK_SIGMA,
        "rank_lookback": RANK_LOOKBACK,
        "gross_exposure": float(sum(abs(v) for v in targets.values())),
        "longs": sorted(k for k, v in targets.items() if v > 0),
        "shorts": sorted(k for k, v in targets.items() if v < 0),
        "note": (
            "Overnight continuation of the daily analog after the last cash close. "
            "Not flatten-at-close; not 1-minute Concretum Bands."
        ),
    }
    return targets, signal_ts, meta
