from __future__ import annotations

import pandas as pd

from deployments.utils.sp500_breakout_high10 import (
    HOLD_BARS,
    LOOKBACK,
    YAHOO,
    entries_exits,
    latest_book,
)
from deployments.utils.turnaround_wednesday import overnight_after_close, session_close_utc


def _frame(rows: list[tuple[str, float, float, float]]) -> pd.DataFrame:
    """rows: (YYYY-MM-DD, high, low, close) stamped like Yahoo ES=F (NY midnight)."""
    idx = pd.DatetimeIndex(
        [pd.Timestamp(d, tz="America/New_York").tz_convert("UTC") for d, *_ in rows]
    )
    high = [r[1] for r in rows]
    low = [r[2] for r in rows]
    close = [r[3] for r in rows]
    df = pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close},
        index=idx,
    )
    df["close_time"] = [session_close_utc(ts) for ts in df.index]
    return df


def _days(n: int, start: str = "2026-02-02") -> list[str]:
    return [d.strftime("%Y-%m-%d") for d in pd.bdate_range(start, periods=n, freq="C")]


def _warmup(n: int = LOOKBACK) -> list[tuple[str, float, float, float]]:
    """n flat sessions: high=100 so the next breakout is vs a 100 Donchian."""
    return [(d, 100.0, 99.0, 100.0) for d in _days(n)]


def _breakout_setup() -> pd.DataFrame:
    """Bar LOOKBACK breaks the prior 12-day high with IBS 0.10; fill is the next bar."""
    rows = _warmup(LOOKBACK)
    days = _days(LOOKBACK + 2)
    # Weak-close breakout (IBS = (92-90)/(110-90) = 0.10).
    rows.append((days[LOOKBACK], 110.0, 90.0, 92.0))
    # Fill bar: mid-range close, no IBS exit.
    rows.append((days[LOOKBACK + 1], 101.0, 99.0, 100.0))
    return _frame(rows)


def test_setup_does_not_fill_same_bar():
    frame = _breakout_setup().iloc[: LOOKBACK + 1]
    entries, exits, entry_raw = entries_exits(frame)
    overnight = overnight_after_close(entries, exits)
    assert bool(entry_raw.iloc[-1]) is True
    assert bool(entries.iloc[-1]) is False
    assert bool(exits.iloc[-1]) is False
    assert float(overnight.iloc[-1]) == 0.0


def test_lag1_fills_next_bar_and_holds_overnight():
    frame = _breakout_setup()
    entries, exits, entry_raw = entries_exits(frame)
    overnight = overnight_after_close(entries, exits)
    assert bool(entry_raw.iloc[-2]) is True
    assert bool(entry_raw.iloc[-1]) is False
    assert bool(entries.iloc[-1]) is True
    assert bool(exits.iloc[-1]) is False
    assert float(overnight.iloc[-1]) == 1.0
    assert float(overnight.iloc[-2]) == 0.0


def test_no_setup_when_ibs_not_weak():
    rows = _warmup(LOOKBACK)
    days = _days(LOOKBACK + 1)
    rows.append((days[LOOKBACK], 110.0, 90.0, 108.0))  # IBS = 0.90
    entries, _, entry_raw = entries_exits(_frame(rows))
    assert bool(entry_raw.iloc[-1]) is False
    assert bool(entries.iloc[-1]) is False


def test_no_setup_without_high12_break():
    rows = _warmup(LOOKBACK)
    days = _days(LOOKBACK + 1)
    rows.append((days[LOOKBACK], 100.0, 90.0, 91.0))  # high does not exceed 100
    _, _, entry_raw = entries_exits(_frame(rows))
    assert bool(entry_raw.iloc[-1]) is False


def test_ibs_exit_flattens_overnight():
    rows = _warmup(LOOKBACK)
    days = _days(LOOKBACK + 3)
    rows.append((days[LOOKBACK], 110.0, 90.0, 92.0))
    rows.append((days[LOOKBACK + 1], 101.0, 99.0, 100.0))  # fill
    rows.append((days[LOOKBACK + 2], 120.0, 100.0, 119.0))  # IBS = 0.95
    frame = _frame(rows)
    entries, exits, _ = entries_exits(frame)
    overnight = overnight_after_close(entries, exits)
    assert bool(exits.iloc[-1]) is True
    assert float(overnight.iloc[-1]) == 0.0
    assert float(overnight.iloc[-2]) == 1.0


def test_time_stop_five_bars_after_fill():
    rows = _warmup(LOOKBACK)
    days = _days(LOOKBACK + 2 + HOLD_BARS)
    rows.append((days[LOOKBACK], 110.0, 90.0, 92.0))
    for d in days[LOOKBACK + 1 :]:
        rows.append((d, 101.0, 99.0, 100.0))
    frame = _frame(rows)
    entries, exits, _ = entries_exits(frame)
    overnight = overnight_after_close(entries, exits)
    assert int(entries.sum()) == 1
    assert bool(exits.iloc[-1]) is True
    assert float(overnight.iloc[-1]) == 0.0
    assert float(overnight.iloc[-2]) == 1.0
    assert int(exits.sum()) == 1


def _ny_date(ts: pd.Timestamp) -> str:
    return pd.Timestamp(ts).tz_convert("America/New_York").strftime("%Y-%m-%d")


def test_latest_book_ignores_open_session_and_lags_fill():
    frame = _breakout_setup()
    setup_ny = _ny_date(frame.index[LOOKBACK])
    before_close = pd.Timestamp(f"{setup_ny} 16:00", tz="America/Chicago")
    after_close = pd.Timestamp(f"{setup_ny} 17:05", tz="America/Chicago")

    targets, _, meta = latest_book(before_close, ohlcv=frame)
    assert targets == {YAHOO: 0.0}
    assert meta["setup_today"] is False
    assert meta["in_position"] is False

    targets, _, meta = latest_book(after_close, ohlcv=frame)
    assert targets == {YAHOO: 0.0}
    assert meta["setup_today"] is True
    assert meta["entered"] is False
    assert meta["in_position"] is False

    fill_ny = _ny_date(frame.index[LOOKBACK + 1])
    fill_after = pd.Timestamp(f"{fill_ny} 17:05", tz="America/Chicago")
    targets, _, meta = latest_book(fill_after, ohlcv=frame)
    assert targets == {YAHOO: 1.0}
    assert meta["entered"] is True
    assert meta["in_position"] is True
    assert meta["execution_lag"] == 1
    assert meta["lookback"] == 12
    assert meta["ibs_entry"] == 0.25
