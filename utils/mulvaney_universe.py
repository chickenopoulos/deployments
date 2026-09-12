"""Concretum 39-market map → Yahoo proxies used by id21/id22.

Same mapping as thequantgpt-wrapper/data/futures/mulvaney_universe_map.json.
These are cash/continuous Yahoo series, not listed futures with multipliers.
"""

from __future__ import annotations

from typing import Mapping

import pandas as pd

# (concretum_id, yahoo_ticker, sector)
MARKETS: list[tuple[str, str, str]] = [
    ("LEU", "ZQ=F", "Interest Rates"),
    ("YIR", "ZF=F", "Interest Rates"),
    ("LLG", "IGLT.L", "Interest Rates"),
    ("SJB", "2510.T", "Interest Rates"),
    ("FGBL", "EXX5.DE", "Interest Rates"),
    ("ZB", "ZB=F", "Interest Rates"),
    ("ZT", "ZT=F", "Interest Rates"),
    ("FDAX", "^GDAXI", "Stock Indices"),
    ("NQ", "NQ=F", "Stock Indices"),
    ("ES", "ES=F", "Stock Indices"),
    ("HTW", "^HSI", "Stock Indices"),
    ("LFT", "^FTSE", "Stock Indices"),
    ("SNK", "^N225", "Stock Indices"),
    ("6A", "6A=F", "Currency"),
    ("6B", "6B=F", "Currency"),
    ("6C", "6C=F", "Currency"),
    ("6E", "6E=F", "Currency"),
    ("6J", "6J=F", "Currency"),
    ("6M", "6M=F", "Currency"),
    ("6S", "6S=F", "Currency"),
    ("ZL", "ZL=F", "Grains"),
    ("ZC", "ZC=F", "Grains"),
    ("ZS", "ZS=F", "Grains"),
    ("ZM", "ZM=F", "Grains"),
    ("ZW", "ZW=F", "Grains"),
    ("CT", "CT=F", "Softs"),
    ("OJ", "OJ=F", "Softs"),
    ("KC", "KC=F", "Softs"),
    ("CC", "CC=F", "Softs"),
    ("SB", "SB=F", "Softs"),
    ("BRN", "BZ=F", "Energy"),
    ("CL", "CL=F", "Energy"),
    ("NG", "NG=F", "Energy"),
    ("GAS", "HO=F", "Energy"),
    ("GC", "GC=F", "Metals"),
    ("HG", "HG=F", "Metals"),
    ("SI", "SI=F", "Metals"),
    ("LE", "LE=F", "Livestock"),
    ("HE", "HE=F", "Livestock"),
]

SECTORS: dict[str, list[str]] = {}
for _cid, _yahoo, _sector in MARKETS:
    SECTORS.setdefault(_sector, []).append(_cid)

MARKET_SECTOR = {cid: sector for cid, _yahoo, sector in MARKETS}
YAHOO_BY_CONCRETUM = {cid: yahoo for cid, yahoo, _sector in MARKETS}
CONCRETUM_BY_YAHOO = {yahoo: cid for cid, yahoo, _sector in MARKETS}
YAHOO_TICKERS = [yahoo for _cid, yahoo, _sector in MARKETS]
N_MARKETS = len(MARKETS)

SECTOR_BUCKET = {
    "Interest Rates": "Rates",
    "Stock Indices": "Equity",
    "Currency": "FX",
    "Grains": "Commodities",
    "Softs": "Commodities",
    "Energy": "Commodities",
    "Metals": "Commodities",
    "Livestock": "Commodities",
}

_INDEX_SESSIONS: dict[str, tuple[str, str]] = {
    "^GDAXI": ("Europe/Berlin", "17:30"),
    "^HSI": ("Asia/Hong_Kong", "16:00"),
    "^FTSE": ("Europe/London", "16:30"),
    "^N225": ("Asia/Tokyo", "15:00"),
}

_DEFAULT_SESSION = ("America/New_York", "16:00")


def canonical_yahoo(symbol: str) -> str:
    """Case-insensitive map onto the universe ticker, else strip/upper-safe identity."""
    raw = str(symbol).strip()
    by_upper = {y.upper(): y for y in YAHOO_TICKERS}
    by_upper["SPY"] = "SPY"
    return by_upper.get(raw.upper(), raw)


def session_for_yahoo(symbol: str) -> tuple[str, str]:
    """Exchange timezone and local session close HH:MM for a Yahoo ticker."""
    s = canonical_yahoo(symbol)
    if s in _INDEX_SESSIONS:
        return _INDEX_SESSIONS[s]
    if s.endswith("=X"):
        return "UTC", "23:59"
    if s.endswith("=F"):
        return "America/Chicago", "17:00"
    if s.endswith(".L"):
        return "Europe/London", "16:30"
    if s.endswith(".DE"):
        return "Europe/Berlin", "17:30"
    if s.endswith(".T"):
        return "Asia/Tokyo", "15:00"
    return _DEFAULT_SESSION


def _as_utc(ts: pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def bar_close_utc(open_time: pd.Timestamp, yahoo_symbol: str) -> pd.Timestamp:
    """Daily bar close in UTC from the Yahoo session date + venue close.

    Yahoo US cash and CME ``=F`` daily bars are stamped at midnight
    America/New_York of the session date. That instant is still the previous
    evening in America/Chicago, so converting to Chicago *before* normalize()
    would close the prior Globex day. Use the NY calendar date for futures.
    """
    ts = pd.Timestamp(open_time)
    symbol = canonical_yahoo(yahoo_symbol)
    tz, hhmm = session_for_yahoo(symbol)
    hour, minute = (int(p) for p in hhmm.split(":"))
    if symbol.endswith("=F"):
        if ts.tzinfo is None:
            ny = ts.tz_localize("America/New_York", ambiguous="infer", nonexistent="shift_forward")
        else:
            ny = ts.tz_convert("America/New_York")
        session_date = ny.normalize()
        close_ct = pd.Timestamp(
            year=int(session_date.year),
            month=int(session_date.month),
            day=int(session_date.day),
            hour=hour,
            minute=minute,
            tz="America/Chicago",
        )
        return close_ct.tz_convert("UTC")
    if ts.tzinfo is None:
        local = ts.tz_localize(tz, ambiguous="infer", nonexistent="shift_forward")
    else:
        local = ts.tz_convert(tz)
    close_local = local.normalize() + pd.Timedelta(hours=hour, minutes=minute)
    return close_local.tz_convert("UTC")


def last_completed_session_close_utc(now: pd.Timestamp, yahoo_symbol: str) -> pd.Timestamp:
    """Venue close of the last *finished* daily session as of ``now``."""
    tz, hhmm = session_for_yahoo(yahoo_symbol)
    hour, minute = (int(p) for p in hhmm.split(":"))
    local = _as_utc(now).tz_convert(tz)
    close_today = local.normalize() + pd.Timedelta(hours=hour, minutes=minute)
    session_date = local.normalize() if local >= close_today else local.normalize() - pd.Timedelta(days=1)
    while int(session_date.weekday()) >= 5:
        session_date -= pd.Timedelta(days=1)
    close_local = session_date + pd.Timedelta(hours=hour, minutes=minute)
    return close_local.tz_convert("UTC")


def yahoo_symbol_is_stale(
    last_open: pd.Timestamp,
    now: pd.Timestamp,
    yahoo_symbol: str,
    *,
    slack: pd.Timedelta | None = None,
) -> bool:
    """True when the last stored bar is from before the last completed session."""
    grace = slack if slack is not None else pd.Timedelta(hours=6)
    last_close = bar_close_utc(last_open, yahoo_symbol)
    expected_close = last_completed_session_close_utc(now, yahoo_symbol)
    return pd.Timestamp(last_close) < expected_close - grace


def yfinance_symbol_payload() -> dict[str, dict]:
    """STF symbols.yaml entries for the Yahoo proxy universe."""
    payload: dict[str, dict] = {}
    for yahoo in YAHOO_TICKERS:
        payload[yahoo] = {
            "data_source": "yfinance",
            "yfinance_ticker": yahoo,
            "taker_fee_bps": 1.0,
            "maker_fee_bps": 0.0,
            "half_spread_floor_bps": 0.5,
            "bar_participation_cap": 0.01,
            "impact_coeff_bps": 5.0,
            "impact_exponent": 0.50,
        }
    return payload


def yahoo_set() -> set[str]:
    return set(YAHOO_TICKERS)


def as_mapping() -> Mapping[str, str]:
    return YAHOO_BY_CONCRETUM
