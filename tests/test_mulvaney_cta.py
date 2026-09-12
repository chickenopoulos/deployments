from __future__ import annotations

import numpy as np
import pandas as pd

from deployments.scrappers.yfinance_ohlcv import merge_asset_frames
from deployments.utils.mulvaney_cta import (
    PARAMS_BEST,
    PARAMS_CANONICAL,
    closed_symbol_ohlcv,
    net_weight,
    simulate_market,
)
from deployments.utils.mulvaney_universe import bar_close_utc, session_for_yahoo


def _channel_then_break(lookback: int = 20, n_after: int = 2) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n = lookback + n_after + 5
    high = np.full(n, 101.0)
    low = np.full(n, 99.0)
    close = np.full(n, 100.0)
    valid = np.ones(n, dtype=bool)
    high[-1] = 108.0
    low[-1] = 100.0
    close[-1] = 107.0
    return high, low, close, valid


def test_lag0_fills_on_breakout_bar_lag1_does_not():
    high, low, close, valid = _channel_then_break(lookback=20)
    params0 = dict(PARAMS_CANONICAL)
    params0.update(lookback_days=20, execution_lag=0, pyramid_cap=1, direction="long_only")
    params1 = dict(params0, execution_lag=1)
    _, units0 = simulate_market(high, low, close, valid, market="ES", n_markets=39, params=params0)
    _, units1 = simulate_market(high, low, close, valid, market="ES", n_markets=39, params=params1)
    assert net_weight(units0) > 0
    assert net_weight(units1) == 0.0


def test_long_only_ignores_breakdown():
    n = 30
    high = np.full(n, 101.0)
    low = np.full(n, 99.0)
    close = np.full(n, 100.0)
    valid = np.ones(n, dtype=bool)
    low[-1] = 90.0
    close[-1] = 91.0
    params = dict(PARAMS_BEST)
    params.update(lookback_days=20, execution_lag=0, pyramid_cap=1)
    _, units = simulate_market(high, low, close, valid, market="ES", n_markets=39, params=params)
    assert net_weight(units) == 0.0


def test_flatten_eod_clears_live_weight():
    high, low, close, valid = _channel_then_break(lookback=20)
    params = dict(PARAMS_CANONICAL)
    params.update(lookback_days=20, execution_lag=0, pyramid_cap=1)
    _, live = simulate_market(high, low, close, valid, market="ES", n_markets=39, params=params, flatten_eod=False)
    _, flat = simulate_market(high, low, close, valid, market="ES", n_markets=39, params=params, flatten_eod=True)
    assert net_weight(live) > 0
    assert net_weight(flat) == 0.0


def test_canonical_and_best_params_differ():
    assert PARAMS_CANONICAL["execution_lag"] == 1
    assert PARAMS_CANONICAL["direction"] == "long_short"
    assert PARAMS_BEST["execution_lag"] == 0
    assert PARAMS_BEST["direction"] == "long_only"
    assert PARAMS_BEST["lookback_days"] == 63


def test_cme_session_is_chicago_1700_not_ny_cash():
    tz, hhmm = session_for_yahoo("ES=F")
    assert tz == "America/Chicago"
    assert hhmm == "17:00"
    spy_tz, spy_hhmm = session_for_yahoo("SPY")
    assert spy_tz == "America/New_York"
    assert spy_hhmm == "16:00"


def test_cme_bar_close_uses_ny_session_date_not_chicago_evening():
    # Yahoo ES=F daily stamp is midnight America/New_York (04:00 UTC in EDT).
    open_ts = pd.Timestamp("2026-09-11 00:00", tz="America/New_York")
    close_ts = bar_close_utc(open_ts, "ES=F")
    expected = pd.Timestamp("2026-09-11 17:00", tz="America/Chicago").tz_convert("UTC")
    assert close_ts == expected
    assert close_ts > open_ts.tz_convert("UTC")


def test_exx5_wednesday_bar_is_stale_on_friday_night():
    last_open = pd.Timestamp("2026-09-08 22:00", tz="UTC")  # Wed session
    now = pd.Timestamp("2026-09-11 23:00", tz="UTC")
    from deployments.utils.mulvaney_universe import yahoo_symbol_is_stale

    assert yahoo_symbol_is_stale(last_open, now, "EXX5.DE") is True
    friday_open = pd.Timestamp("2026-09-10 22:00", tz="UTC")  # Fri session
    assert yahoo_symbol_is_stale(friday_open, now, "EXX5.DE") is False


def test_closed_ohlcv_drops_unclosed_cme_session():
    days = pd.date_range("2026-09-08", periods=3, freq="D", tz="America/Chicago")
    frame = pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
        index=days.tz_convert("UTC"),
    )
    frame["close_time"] = [bar_close_utc(ts, "ES=F") for ts in frame.index]
    # 16:00 CT — session close is 17:00 CT, so today is still open.
    as_of = pd.Timestamp("2026-09-10 16:00", tz="America/Chicago")
    closed = closed_symbol_ohlcv(frame, as_of, "ES=F")
    last = closed.index.tz_convert("America/Chicago").normalize()[-1]
    assert str(last.date()) == "2026-09-09"


def test_merge_asset_frames_replaces_only_refreshed_names():
    existing = pd.DataFrame(
        {
            "asset": ["SPY", "SPY", "ES=F"],
            "open_time": pd.to_datetime(
                ["2026-01-01", "2026-01-02", "2026-01-01"], utc=True
            ),
            "close": [1.0, 2.0, 9.0],
        }
    )
    new = pd.DataFrame(
        {
            "asset": ["ES=F"],
            "open_time": pd.to_datetime(["2026-01-03"], utc=True),
            "close": [10.0],
        }
    )
    merged = merge_asset_frames(existing, new)
    assert set(merged["asset"]) == {"SPY", "ES=F"}
    spy = merged.loc[merged["asset"] == "SPY"]
    assert len(spy) == 2
    es = merged.loc[merged["asset"] == "ES=F"]
    assert list(es["close"]) == [10.0]
