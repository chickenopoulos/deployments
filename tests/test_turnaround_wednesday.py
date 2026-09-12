from __future__ import annotations

import numpy as np
import pandas as pd

from deployments.utils.turnaround_wednesday import (
    YAHOO,
    entries_exits,
    latest_book,
    overnight_after_close,
    session_close_utc,
)


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


def _setup_week() -> pd.DataFrame:
    # Mon 2026-08-03 … Tue 2026-08-11. Tuesday 08-04 is the entry:
    # down from 100, IBS = (92-90)/(110-90) = 0.10.
    return _frame(
        [
            ("2026-08-03", 101, 99, 100),  # Mon
            ("2026-08-04", 110, 90, 92),  # Tue entry
            ("2026-08-05", 95, 91, 94),  # Wed hold (94 < 110)
            ("2026-08-06", 96, 92, 95),  # Thu
            ("2026-08-07", 97, 93, 96),  # Fri
            ("2026-08-10", 98, 94, 97),  # Mon held=4
            ("2026-08-11", 99, 95, 98),  # Tue held=5 time stop
        ]
    )


def test_tuesday_down_weak_ibs_enters_same_bar():
    frame = _setup_week().iloc[:2]
    entries, exits = entries_exits(frame)
    overnight = overnight_after_close(entries, exits)
    assert bool(entries.iloc[-1]) is True
    assert bool(exits.iloc[-1]) is False
    assert float(overnight.iloc[-1]) == 1.0


def test_qs_exit_flattens_after_close_above_prior_high():
    frame = _frame(
        [
            ("2026-08-03", 101, 99, 100),
            ("2026-08-04", 110, 90, 92),
            ("2026-08-05", 112, 100, 111),  # 111 > 110
        ]
    )
    entries, exits = entries_exits(frame)
    overnight = overnight_after_close(entries, exits)
    assert bool(exits.iloc[-1]) is True
    assert float(overnight.iloc[-1]) == 0.0
    # Still long through the exit close (lab semantics), flat overnight.
    assert bool(entries.iloc[-2]) is True
    assert float(overnight.iloc[-2]) == 1.0


def test_time_stop_after_five_bars():
    frame = _setup_week()
    entries, exits = entries_exits(frame)
    overnight = overnight_after_close(entries, exits)
    assert bool(exits.iloc[-1]) is True
    assert float(overnight.iloc[-1]) == 0.0
    assert float(overnight.iloc[-2]) == 1.0
    assert int(exits.sum()) == 1
    assert int(entries.sum()) == 1


def test_no_entry_when_ibs_not_weak():
    frame = _frame(
        [
            ("2026-08-03", 101, 99, 100),
            ("2026-08-04", 110, 90, 108),  # IBS = 18/20 = 0.90
        ]
    )
    entries, _ = entries_exits(frame)
    assert bool(entries.iloc[-1]) is False


def test_no_entry_on_wednesday():
    frame = _frame(
        [
            ("2026-08-03", 101, 99, 100),
            ("2026-08-04", 102, 98, 101),
            ("2026-08-05", 110, 90, 92),  # Wed, same IBS/down
        ]
    )
    entries, _ = entries_exits(frame)
    assert bool(entries.iloc[-1]) is False


def test_latest_book_uses_closed_cme_session():
    frame = _setup_week()
    # Tuesday 2026-08-04 16:00 CT — Monday closed, Tuesday not.
    as_of = pd.Timestamp("2026-08-04 16:00", tz="America/Chicago")
    targets, _, meta = latest_book(as_of, ohlcv=frame)
    assert targets == {YAHOO: 0.0}
    assert meta["in_position"] is False
    assert "2026-08-03" in meta["bar_open"]

    after_close = pd.Timestamp("2026-08-04 17:05", tz="America/Chicago")
    targets, _, meta = latest_book(after_close, ohlcv=frame)
    assert targets == {YAHOO: 1.0}
    assert meta["in_position"] is True
    assert meta["entered"] is True
    assert np.isclose(meta["ibs"], 0.10)


def test_latest_book_flat_after_time_stop():
    frame = _setup_week()
    as_of = pd.Timestamp("2026-08-11 17:05", tz="America/Chicago")
    targets, _, meta = latest_book(as_of, ohlcv=frame)
    assert targets == {YAHOO: 0.0}
    assert meta["exited"] is True
    assert meta["in_position"] is False
