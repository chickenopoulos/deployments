from __future__ import annotations

import numpy as np
import pandas as pd

from deployments.utils.inside_compress_fx import (
    LOCKED,
    WEIGHT,
    completed_bars,
    drop_saturday,
    entries_exits,
    latest_book,
    signal_mask,
    stf_symbol,
)
from deployments.utils.turnaround_wednesday import overnight_after_close


def _flat(n: int, start: str = "2024-01-01") -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=n, tz="UTC")
    close = np.full(n, 100.0)
    return pd.DataFrame(
        {"open": close, "high": close + 1.0, "low": close - 1.0, "close": close},
        index=idx,
    )


def _setup_frame() -> pd.DataFrame:
    """Mother down-bar then inside compress; fill bar trades through the inside low."""
    df = _flat(20)
    # Mother (index 17): down and wide.
    df.iloc[17, df.columns.get_loc("open")] = 100.0
    df.iloc[17, df.columns.get_loc("high")] = 102.0
    df.iloc[17, df.columns.get_loc("low")] = 98.0
    df.iloc[17, df.columns.get_loc("close")] = 98.0
    # Inside (index 18): inside mother, still closes lower, ratio 0.70.
    df.iloc[18, df.columns.get_loc("open")] = 99.0
    df.iloc[18, df.columns.get_loc("high")] = 101.0
    df.iloc[18, df.columns.get_loc("low")] = 98.2
    df.iloc[18, df.columns.get_loc("close")] = 97.5
    # Fill bar (index 19): trades through the inside low — must NOT stop.
    df.iloc[19, df.columns.get_loc("open")] = 97.6
    df.iloc[19, df.columns.get_loc("high")] = 99.0
    df.iloc[19, df.columns.get_loc("low")] = 97.0
    df.iloc[19, df.columns.get_loc("close")] = 98.4
    return df


def test_signal_fires_on_inside_after_weakness():
    frame = _setup_frame()
    sig = signal_mask(frame, LOCKED)
    assert bool(sig[18]) is True
    assert bool(sig[17]) is False
    assert bool(sig[19]) is False


def test_entry_is_next_open_not_signal_bar():
    frame = _setup_frame()
    entries, exits, sig = entries_exits(frame, LOCKED)
    overnight = overnight_after_close(entries, exits)
    assert bool(sig[18]) is True
    assert bool(entries.iloc[18]) is False
    assert float(overnight.iloc[18]) == 0.0
    assert bool(entries.iloc[19]) is True
    assert bool(exits.iloc[19]) is False
    assert float(overnight.iloc[19]) == 1.0


def test_stop_not_live_on_fill_bar():
    frame = _setup_frame()
    entries, exits, _ = entries_exits(frame, LOCKED)
    overnight = overnight_after_close(entries, exits)
    assert float(frame["low"].iloc[19]) < float(frame["low"].iloc[18])
    assert bool(exits.iloc[19]) is False
    assert float(overnight.iloc[19]) == 1.0


def test_stop_after_fill_bar_flattens_overnight():
    frame = _setup_frame()
    extra = pd.DataFrame(
        {
            "open": [98.4],
            "high": [98.5],
            "low": [97.0],
            "close": [97.2],
        },
        index=frame.index[-1:] + pd.Timedelta(days=1),
    )
    frame = pd.concat([frame, extra])
    entries, exits, _ = entries_exits(frame, LOCKED)
    overnight = overnight_after_close(entries, exits)
    assert bool(exits.iloc[-1]) is True
    assert float(overnight.iloc[-1]) == 0.0
    assert float(overnight.iloc[-2]) == 1.0


def test_drop_saturday_keeps_sunday():
    idx = pd.DatetimeIndex(
        [
            pd.Timestamp("2026-09-04", tz="UTC"),  # Friday
            pd.Timestamp("2026-09-05", tz="UTC"),  # Saturday
            pd.Timestamp("2026-09-06", tz="UTC"),  # Sunday
        ]
    )
    df = pd.DataFrame({"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0}, index=idx)
    out = drop_saturday(df)
    assert list(out.index.dayofweek) == [4, 6]


def test_completed_bars_drops_forming_session():
    frame = _flat(5)
    as_of = frame.index[-1] + pd.Timedelta(hours=12)
    closed = completed_bars(frame, as_of)
    assert closed.index[-1] == frame.index[-2]


def test_ew_locked_book_weights_one_seventh(monkeypatch):
    frame = _setup_frame()
    panel_rows = []
    for pair in ("EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD"):
        part = frame.reset_index().rename(columns={"index": "open_time"})
        part["asset"] = pair
        panel_rows.append(part)
    panel = pd.concat(panel_rows, ignore_index=True)
    as_of = frame.index[-1] + pd.Timedelta(days=1, hours=1)
    targets, _, meta = latest_book(as_of, "id34", ohlcv=panel)
    assert meta["n_long"] == 7
    expected = {stf_symbol(p): WEIGHT for p in (
        "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD"
    )}
    assert targets == expected
    assert abs(sum(targets.values()) - 1.0) < 1e-12


def test_ew_flat_book_still_declares_universe(monkeypatch):
    frame = _flat(20)
    panel_rows = []
    for pair in ("EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD"):
        part = frame.reset_index().rename(columns={"index": "open_time"})
        part["asset"] = pair
        panel_rows.append(part)
    panel = pd.concat(panel_rows, ignore_index=True)
    as_of = frame.index[-1] + pd.Timedelta(days=1, hours=1)
    targets, _, meta = latest_book(as_of, "id34", ohlcv=panel)
    assert meta["n_long"] == 0
    assert set(targets) == {stf_symbol(p) for p in (
        "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD"
    )}
    assert all(v == 0.0 for v in targets.values())
