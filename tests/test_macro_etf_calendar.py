from __future__ import annotations

import pandas as pd

from deployments.utils.macro_etf_calendar import (
    closed_panel,
    days_from_month_end,
    latest_book,
    overnight_weights,
    pivot_close,
)


def _days(start: str, periods: int) -> pd.DatetimeIndex:
    return pd.bdate_range(start, periods=periods, freq="C", tz="America/New_York").tz_convert("UTC")


def _panel(days: pd.DatetimeIndex, spy: list[float], tlt: list[float], ief: list[float]) -> pd.DataFrame:
    rows = []
    for ts, s, t, b in zip(days, spy, tlt, ief):
        for asset, px in (("SPY", s), ("TLT", t), ("IEF", b)):
            rows.append(
                {
                    "open_time": ts,
                    "asset": asset,
                    "open": px,
                    "high": px,
                    "low": px,
                    "close": px,
                    "volume": 1.0,
                }
            )
    return pd.DataFrame(rows)


def test_incomplete_month_does_not_treat_latest_bar_as_month_end():
    days = _days("2026-08-03", 10)
    dfe = days_from_month_end(days)
    assert int(dfe[-1]) > 0
    assert int(dfe[0]) > int(dfe[-1])


def test_completed_july_marks_last_bar_as_month_end():
    days = pd.bdate_range("2026-07-01", "2026-08-14", freq="C", tz="America/New_York").tz_convert("UTC")
    dfe = days_from_month_end(days)
    ny = days.tz_convert("America/New_York")
    july = dfe[ny.month == 7]
    assert int(july[-1]) == 0
    assert int(july[-6]) == 5


def test_sixth_last_close_enters_eom_long_tlt():
    days = pd.bdate_range("2026-06-01", "2026-07-31", freq="C", tz="America/New_York").tz_convert("UTC")
    n = len(days)
    # Stocks outperform bonds into July so bond_trade > 0 → short SPY at EOM.
    spy = [100.0 + i * 0.4 for i in range(n)]
    tlt = [100.0 + i * 0.05 for i in range(n)]
    ief = [100.0 + i * 0.02 for i in range(n)]
    close = pd.DataFrame({"TLT": tlt, "SPY": spy, "IEF": ief}, index=days)
    w = overnight_weights(close)
    ny = days.tz_convert("America/New_York")
    july = ny.month == 7
    dfe = days_from_month_end(days)
    sixth = w.index[(july) & (dfe == 5)][-1]
    assert float(w.loc[sixth, "TLT"]) == 1.0
    assert float(w.loc[sixth, "SPY"]) == -1.0
    assert str(w.attrs["window"].loc[sixth]) == "eom"


def test_month_end_close_reverses_to_som():
    days = pd.bdate_range("2026-06-01", "2026-07-31", freq="C", tz="America/New_York").tz_convert("UTC")
    n = len(days)
    spy = [100.0 + i * 0.4 for i in range(n)]
    tlt = [100.0 + 0.05 * i for i in range(n)]
    ief = [100.0 + 0.02 * i for i in range(n)]
    close = pd.DataFrame({"TLT": tlt, "SPY": spy, "IEF": ief}, index=days)
    w = overnight_weights(close)
    ny = days.tz_convert("America/New_York")
    dfe = days_from_month_end(days)
    me = w.index[(ny.month == 7) & (dfe == 0)][-1]
    assert float(w.loc[me, "TLT"]) == -1.0
    assert float(w.loc[me, "SPY"]) == 1.0
    assert str(w.attrs["window"].loc[me]) == "som"


def test_fifth_session_flattens():
    days = pd.bdate_range("2026-06-01", "2026-08-10", freq="C", tz="America/New_York").tz_convert("UTC")
    n = len(days)
    spy = [100.0 + i * 0.4 for i in range(n)]
    tlt = [100.0 + 0.05 * i for i in range(n)]
    ief = [100.0 + 0.02 * i for i in range(n)]
    close = pd.DataFrame({"TLT": tlt, "SPY": spy, "IEF": ief}, index=days)
    w = overnight_weights(close)
    ny = days.tz_convert("America/New_York")
    august = w.index[ny.month == 8]
    fifth = august[4]
    assert float(w.loc[fifth, "TLT"]) == 0.0
    assert float(w.loc[fifth, "SPY"]) == 0.0
    assert str(w.attrs["window"].loc[fifth]) == "flat"
    fourth = august[3]
    assert float(w.loc[fourth, "TLT"]) == -1.0


def test_closed_panel_drops_unclosed_session():
    days = _days("2026-08-03", 3)
    panel = _panel(days, [100, 101, 102], [50, 51, 52], [90, 91, 92])
    as_of = pd.Timestamp("2026-08-04 15:00", tz="America/New_York")
    closed = closed_panel(panel, as_of)
    last = pd.to_datetime(closed["open_time"], utc=True).max().tz_convert("America/New_York")
    assert str(last.date()) == "2026-08-03"


def test_latest_book_after_cash_close():
    days = pd.bdate_range("2026-06-01", "2026-07-24", freq="C", tz="America/New_York").tz_convert("UTC")
    n = len(days)
    spy = [100.0 + i * 0.4 for i in range(n)]
    tlt = [100.0 + 0.05 * i for i in range(n)]
    ief = [100.0 + 0.02 * i for i in range(n)]
    panel = _panel(days, spy, tlt, ief)
    # 2026-07-24 is a Friday; use that as last closed bar.
    as_of = pd.Timestamp("2026-07-24 16:05", tz="America/New_York")
    targets, _, meta = latest_book(as_of, ohlcv=panel)
    assert meta["n_bars"] >= 11
    assert set(targets).issubset({"TLT", "SPY"})
    close = pivot_close(closed_panel(panel, as_of))
    row = overnight_weights(close).iloc[-1]
    expected = {k: float(v) for k, v in row.items()}
    assert targets == expected
    assert set(targets) == {"TLT", "SPY"}
