from __future__ import annotations

import numpy as np
import pandas as pd

from deployments.utils.connors_pctb import (
    SYMBOL,
    entries_exits,
    latest_book,
    pctb,
)
from deployments.utils.turnaround_wednesday import overnight_after_close


def _ohlcv(closes: list[float], start: str = "2015-01-02") -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=len(closes), freq="C", tz="America/New_York").tz_convert(
        "UTC"
    )
    close = np.asarray(closes, dtype=float)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 1.0,
        },
        index=idx,
    )


def _uptrend(n: int = 250, start: float = 50.0, step: float = 0.5) -> list[float]:
    return [start + step * i for i in range(n)]


def _setup_entry(n_dump: int = 3, dump_ret: float = -0.07) -> pd.DataFrame:
    closes = _uptrend()
    last = closes[-1]
    for _ in range(n_dump):
        last = last * (1.0 + dump_ret)
        closes.append(last)
    return _ohlcv(closes)


def test_three_days_pctb_below_0p2_above_sma200_enters():
    frame = _setup_entry(n_dump=3)
    entries, exits, band = entries_exits(frame)
    overnight = overnight_after_close(entries, exits)
    assert float(band.iloc[-1]) < 0.2
    assert bool(entries.iloc[-1]) is True
    assert bool(exits.iloc[-1]) is False
    assert float(overnight.iloc[-1]) == 1.0
    assert int(entries.iloc[-3:].sum()) == 1


def test_two_consecutive_days_does_not_enter():
    frame = _setup_entry(n_dump=2)
    entries, _, band = entries_exits(frame)
    assert float(band.iloc[-1]) < 0.2
    assert float(band.iloc[-2]) < 0.2
    assert bool(entries.iloc[-1]) is False
    assert int(entries.sum()) == 0


def test_no_entry_below_sma200():
    closes = [200.0 - 0.5 * i for i in range(250)]
    last = closes[-1]
    for _ in range(3):
        last *= 0.93
        closes.append(last)
    frame = _ohlcv(closes)
    entries, _, _ = entries_exits(frame)
    sma = frame["close"].rolling(200).mean().iloc[-1]
    assert float(frame["close"].iloc[-1]) < float(sma)
    assert bool(entries.iloc[-1]) is False
    assert int(entries.sum()) == 0


def test_exit_when_pctb_above_0p8_flattens_overnight():
    closes = _uptrend()
    last = closes[-1]
    for _ in range(3):
        last *= 0.93
        closes.append(last)
    closes.append(closes[-4])  # snap back to pre-dump close
    frame = _ohlcv(closes)
    entries, exits, band = entries_exits(frame)
    overnight = overnight_after_close(entries, exits)
    assert float(band.iloc[-1]) > 0.8
    assert bool(entries.iloc[-2]) is True
    assert bool(exits.iloc[-1]) is True
    assert float(overnight.iloc[-2]) == 1.0
    assert float(overnight.iloc[-1]) == 0.0


def test_latest_book_uses_closed_cash_session():
    frame = _setup_entry(n_dump=3)
    last_open = pd.Timestamp(frame.index[-1])
    ny_date = last_open.tz_convert("America/New_York").date()
    before = pd.Timestamp(
        year=ny_date.year,
        month=ny_date.month,
        day=ny_date.day,
        hour=15,
        tz="America/New_York",
    )
    after = pd.Timestamp(
        year=ny_date.year,
        month=ny_date.month,
        day=ny_date.day,
        hour=16,
        minute=5,
        tz="America/New_York",
    )
    targets, _, meta = latest_book(before, ohlcv=frame)
    assert targets == {SYMBOL: 0.0}
    assert meta["in_position"] is False
    assert "entered" in meta
    prior_ny = pd.Timestamp(meta["bar_open"]).tz_convert("America/New_York").date()
    assert prior_ny < ny_date

    targets, _, meta = latest_book(after, ohlcv=frame)
    assert targets == {SYMBOL: 1.0}
    assert meta["in_position"] is True
    assert meta["entered"] is True
    assert meta["pctb"] is not None
    assert meta["pctb"] < 0.2


def test_pctb_uses_population_std():
    close = pd.Series([10.0, 12.0, 11.0, 13.0, 9.0])
    got = float(pctb(close, n=5, k=1.0).iloc[-1])
    ma = close.mean()
    sd = close.std(ddof=0)
    expected = (close.iloc[-1] - (ma - sd)) / (2.0 * sd)
    assert np.isclose(got, expected)
