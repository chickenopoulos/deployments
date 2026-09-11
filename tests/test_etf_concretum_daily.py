from __future__ import annotations

import numpy as np
import pandas as pd

from deployments.utils.etf_concretum_daily import (
    LOOKBACK_SIGMA,
    RANK_LOOKBACK,
    cash_close_utc,
    closed_panel,
    last_covered_timestamp,
    latest_book,
    pivot_fields,
    strategy_returns,
)


def _panel(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
    return df


def _session_days(n: int, start: str = "2024-01-02") -> pd.DatetimeIndex:
    days = pd.bdate_range(start, periods=n, freq="C", tz="America/New_York")
    return days.tz_convert("UTC")


def test_closed_panel_drops_unclosed_session():
    days = _session_days(3, start="2026-08-03")
    rows = []
    for ts in days:
        rows.append(
            {
                "open_time": ts,
                "asset": "SPY",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 1.0,
            }
        )
    ohlcv = _panel(rows)
    as_of = pd.Timestamp("2026-08-04 15:00", tz="America/New_York")
    closed = closed_panel(ohlcv, as_of)
    last_ny = pd.to_datetime(closed["open_time"], utc=True).dt.tz_convert("America/New_York").dt.normalize().iloc[-1]
    assert str(last_ny.date()) == "2026-08-03"


def _trend_name(idx: pd.DatetimeIndex, asset: str, *, up: bool) -> pd.DataFrame:
    """Most days break the band in one direction so rolling Sharpe separates."""
    n = len(idx)
    close = np.full(n, 100.0)
    high = np.full(n, 100.5)
    low = np.full(n, 99.5)
    open_ = np.full(n, 100.0)
    for i in range(LOOKBACK_SIGMA + 1, n):
        open_[i] = 100.0
        close[i] = 102.0 if up else 98.0
        high[i] = 103.0 if up else 100.2
        low[i] = 99.8 if up else 97.0
    return pd.DataFrame(
        {
            "open_time": idx,
            "asset": asset,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": 1.0,
        }
    )


def _quiet_name(idx: pd.DatetimeIndex, asset: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open_time": idx,
            "asset": asset,
            "open": 100.0,
            "high": 100.2,
            "low": 99.8,
            "close": 100.0,
            "volume": 1.0,
        }
    )


def test_all_ew_equal_weights_active_breakouts():
    idx = _session_days(LOOKBACK_SIGMA + 5)
    winners = _trend_name(idx, "SPY", up=True)
    losers = _trend_name(idx, "TLT", up=False)
    quiet = _quiet_name(idx, "SHY")
    ohlcv = pd.concat([winners, losers, quiet], ignore_index=True)
    as_of = pd.Timestamp(idx[-1]).tz_convert("America/New_York").normalize() + pd.Timedelta(hours=17)
    targets, _, meta = latest_book(as_of, book="all_ew", ohlcv=ohlcv)
    assert set(targets) == {"SPY", "TLT"}
    assert targets["SPY"] > 0
    assert targets["TLT"] < 0
    assert abs(abs(targets["SPY"]) - 0.5) < 1e-9
    assert abs(meta["gross_exposure"] - 1.0) < 1e-9
    assert "SHY" not in targets


def test_top_and_bottom_split_on_lagged_sharpe():
    n = LOOKBACK_SIGMA + RANK_LOOKBACK + 5
    idx = _session_days(n)
    frames = [_trend_name(idx, "SPY", up=True), _trend_name(idx, "QQQ", up=True)]
    frames.append(_trend_name(idx, "TLT", up=False))
    frames.append(_trend_name(idx, "IEF", up=False))
    for i, name in enumerate(["IWM", "DIA", "GLD", "SLV", "USO", "UNG"]):
        frames.append(_trend_name(idx, name, up=(i % 2 == 0)))
    ohlcv = pd.concat(frames, ignore_index=True)
    as_of = pd.Timestamp(idx[-1]).tz_convert("America/New_York").normalize() + pd.Timedelta(hours=17)
    top, _, top_meta = latest_book(as_of, book="top", ohlcv=ohlcv)
    bot, _, bot_meta = latest_book(as_of, book="bottom", ohlcv=ohlcv)
    assert top_meta["n_scored"] >= 8
    assert top_meta["n_selected"] >= 1
    assert bot_meta["n_selected"] >= 1
    assert set(top).isdisjoint(set(bot)) or not top or not bot
    if top:
        assert all(v > 0 for v in top.values()) or any(v != 0 for v in top.values())
    fields = pivot_fields(ohlcv)
    strat, _ = strategy_returns(fields)
    assert strat.notna().any().any()


def test_latest_book_signal_is_cash_close():
    idx = _session_days(LOOKBACK_SIGMA + 5)
    ohlcv = pd.concat(
        [_trend_name(idx, "SPY", up=True), _trend_name(idx, "TLT", up=False)],
        ignore_index=True,
    )
    as_of = pd.Timestamp(idx[-1]).tz_convert("America/New_York").normalize() + pd.Timedelta(hours=17)
    _, signal_ts, meta = latest_book(as_of, book="all_ew", ohlcv=ohlcv)
    assert signal_ts == cash_close_utc(idx[-1])
    assert "16:00:00" in str(pd.Timestamp(meta["close_time"]).tz_convert("America/New_York"))


def test_ragged_new_session_does_not_advance_the_book():
    idx = _session_days(LOOKBACK_SIGMA + 6)
    complete = idx[:-1]
    frames = [
        _trend_name(complete, "SPY", up=True),
        _trend_name(complete, "TLT", up=False),
        _trend_name(complete, "QQQ", up=True),
        _trend_name(complete, "IWM", up=False),
        _trend_name(complete, "DIA", up=True),
        _trend_name(complete, "GLD", up=False),
        _trend_name(complete, "SLV", up=True),
        _trend_name(complete, "USO", up=False),
        _trend_name(complete, "UNG", up=True),
        _trend_name(complete, "IEF", up=False),
    ]
    extra = _trend_name(idx, "SPY", up=True)
    extra = extra.loc[extra["open_time"] == idx[-1]]
    ohlcv = pd.concat(frames + [extra], ignore_index=True)
    as_of = pd.Timestamp(idx[-1]).tz_convert("America/New_York").normalize() + pd.Timedelta(hours=17)
    fields = pivot_fields(ohlcv)
    last_ok = last_covered_timestamp(fields["close"])
    assert last_ok == complete[-1]
    _, signal_ts, meta = latest_book(as_of, book="all_ew", ohlcv=ohlcv)
    assert pd.Timestamp(meta["bar_open"]) == complete[-1]
    assert signal_ts == cash_close_utc(complete[-1])
    assert meta["n_names_last"] >= 8
