from __future__ import annotations

import pandas as pd

from deployments.utils.spy_qs_portfolio import (
    _days_from_month_end,
    closed_ohlcv,
    overlay_want,
    sleeve_wants,
)


def _frame() -> pd.DataFrame:
    # 10 NY sessions starting Monday 2026-08-03.
    days = pd.date_range("2026-08-03", periods=10, freq="B", tz="America/New_York")
    close = [100, 99, 98, 101, 102, 103, 104, 90, 89, 95]
    high = [c + 1 for c in close]
    low = [c - 1 for c in close]
    return pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close, "volume": 1.0},
        index=days.tz_convert("UTC"),
    )


def test_closed_ohlcv_drops_unclosed_session():
    ohlcv = _frame()
    # Tuesday 2026-08-04 15:00 NY — Monday is closed, Tuesday is not.
    as_of = pd.Timestamp("2026-08-04 15:00", tz="America/New_York")
    closed = closed_ohlcv(ohlcv, as_of)
    last_ny = closed.index.tz_convert("America/New_York").normalize()[-1]
    assert str(last_ny.date()) == "2026-08-03"


def test_incomplete_month_does_not_treat_latest_bar_as_month_end():
    ohlcv = _frame()
    wants = sleeve_wants(ohlcv)
    # Sample ends 2026-08-14, well before August month-end, so LDOM must be off.
    assert bool(wants["ldom"].iloc[-1]) is False
    assert bool(overlay_want(wants).iloc[-1]) is False


def test_completed_month_marks_last_bar_as_month_end():
    idx = pd.bdate_range("2026-07-01", "2026-08-14", freq="C", tz="America/New_York").tz_convert("UTC")
    dfe = _days_from_month_end(idx)
    ny = idx.tz_convert("America/New_York")
    july = dfe[ny.month == 7]
    august = dfe[ny.month == 8]
    assert int(july[-1]) == 0
    assert 3 in {int(v) for v in july}
    assert int(august[-1]) > 0
