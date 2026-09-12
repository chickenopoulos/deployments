from __future__ import annotations

import numpy as np
import pandas as pd

from deployments.utils.mulvaney_universe import session_for_yahoo
from deployments.utils.vol_compression_fx import latest_book, phase_for, setup_mask


def _squeeze_frame() -> pd.DataFrame:
    n = 50
    idx = pd.date_range("2026-01-02", periods=n, freq="B", tz="UTC")
    close = np.full(n, 1.10)
    close[:30] = 1.10 + 0.04 * np.sin(np.arange(30) / 2.0)
    high = close + 0.005
    low = close - 0.005
    high[30:] = 1.1004
    low[30:] = 1.0996
    close[30:] = 1.10
    high[-1] = 1.1002
    low[-1] = 1.09995
    close[-1] = 1.09996
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close}, index=idx)


def test_setup_fires_on_compression_and_weak_close():
    frame = _squeeze_frame()
    mask = setup_mask(frame["high"], frame["low"], frame["close"])
    assert bool(mask.iloc[-1]) is True
    assert bool(mask.iloc[-2]) is False


def test_close_phase_goes_long_open_phase_flattens():
    frame = _squeeze_frame().reset_index().rename(columns={"index": "open_time"})
    frame["asset"] = "EURUSD=X"
    spec = {"strategy_id": "id23", "symbol": "EURUSD", "yahoo": "EURUSD=X"}
    as_of = pd.Timestamp(frame["open_time"].max()) + pd.Timedelta(days=1)
    long_tgt, _, long_meta = latest_book(as_of, spec, phase="close", ohlcv=frame)
    flat_tgt, _, flat_meta = latest_book(as_of, spec, phase="open", ohlcv=frame)
    assert long_tgt == {"EURUSD": 1.0}
    assert long_meta["squeezed"] is True
    assert flat_tgt == {"EURUSD": 0.0}
    assert flat_meta["phase"] == "open"
    assert flat_meta["target"] == 0.0


def test_phase_from_clock_and_override():
    morning = pd.Timestamp("2026-09-10 00:20:00Z")
    evening = pd.Timestamp("2026-09-10 23:50:00Z")
    assert phase_for(morning) == "open"
    assert phase_for(evening) == "close"
    assert phase_for(morning, override="close") == "close"


def test_fx_yahoo_session_is_utc_end_of_day():
    tz, hhmm = session_for_yahoo("EURUSD=X")
    assert tz == "UTC"
    assert hhmm == "23:59"
