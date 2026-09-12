"""Textbook Connors %B on SPY cash, lag-0 MOC, for STF id33.

Frozen public recipe (lab: qs_spy_two_mr). Not the teaser-fit fingerprint
(%B < -0.1 / exit > 1.0) and not the PSA representative or grid peak.

  Entry: close > SMA(200) AND %B of BB(5, 1σ, ddof=0) < 0.2 for 3 consecutive days.
  Exit:  %B > 0.8 (not on the entry bar).
  Long-only, fully funded 1.0 on Yahoo SPY.

Overnight STF book after the last *closed* US cash session (16:00 America/New_York).
Same lag-0 MOC semantics as id30/id32: long through the exit close in the lab,
flat overnight after that close. Purpose: signal efficacy (apply_funding: false).
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd

from deployments.paths import STATE_DIR
from deployments.strategy_types import StrategyContext, StrategyResult
from deployments.utils.spy_qs_portfolio import closed_ohlcv, load_spy_ohlcv
from deployments.utils.stf_targets import declared_weights
from deployments.utils.turnaround_wednesday import overnight_after_close

LAB_RUN = "qs_spy_two_mr"
STRATEGY_ID = "id33"
SYMBOL = "SPY"
BB_N = 5
BB_K = 1.0
PCTB_ENTRY = 0.2
CONSEC = 3
PCTB_EXIT = 0.8
SMA = 200
SESSION_TZ = "America/New_York"
CASH_CLOSE = pd.Timedelta(hours=16)
REBALANCING_STYLE = "on_sign_change"
RUN_FREQUENCY = "1d"
NAME = "Connors %B textbook (lag 0)"
STATE_FILE = STATE_DIR / "connors_pctb.json"


def _as_utc(ts: pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def cash_close_utc(open_time: pd.Timestamp) -> pd.Timestamp:
    ny = _as_utc(open_time).tz_convert(SESSION_TZ)
    return (ny.normalize() + CASH_CLOSE).tz_convert("UTC")


def pctb(close: pd.Series, n: int = BB_N, k: float = BB_K) -> pd.Series:
    ma = close.rolling(int(n), min_periods=int(n)).mean()
    sd = close.rolling(int(n), min_periods=int(n)).std(ddof=0)
    width = (2.0 * float(k) * sd).replace(0.0, np.nan)
    return (close - (ma - float(k) * sd)) / width


def _consec(mask: pd.Series, n: int) -> pd.Series:
    flag = mask.fillna(False).astype(bool)
    out = flag.copy()
    for lag in range(1, n):
        out = out & flag.shift(lag).eq(True)
    return out


def _exits_from_entries(entries: pd.Series, exit_raw: pd.Series) -> pd.Series:
    e = entries.fillna(False).astype(bool).to_numpy()
    xraw = exit_raw.fillna(False).astype(bool).to_numpy()
    x = np.zeros(len(e), dtype=bool)
    in_pos = False
    entry_i = 0
    for i in range(len(e)):
        if not in_pos:
            if bool(e[i]):
                in_pos = True
                entry_i = i
        elif bool(xraw[i]) and i > entry_i:
            x[i] = True
            in_pos = False
    return pd.Series(x, index=entries.index, dtype=bool)


def entries_exits(ohlcv: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    close = ohlcv["close"].astype(float)
    band = pctb(close, BB_N, BB_K)
    sma = close.rolling(SMA, min_periods=SMA).mean()
    oversold = _consec(band < PCTB_ENTRY, CONSEC)
    entry_raw = (oversold & (close > sma)).fillna(False).astype(bool)
    exit_raw = (band > PCTB_EXIT).fillna(False).astype(bool)
    exits = _exits_from_entries(entry_raw, exit_raw)
    return entry_raw, exits, band


def latest_book(
    as_of: pd.Timestamp,
    ohlcv: pd.DataFrame | None = None,
) -> tuple[dict[str, float], pd.Timestamp, dict[str, Any]]:
    raw = ohlcv if ohlcv is not None else load_spy_ohlcv()
    closed = closed_ohlcv(raw, as_of)
    entries, exits, band = entries_exits(closed)
    overnight = overnight_after_close(entries, exits)
    last = closed.iloc[-1]
    flag = bool(overnight.iloc[-1] > 0)
    bar_ts = pd.Timestamp(closed.index[-1])
    close_ts = cash_close_utc(bar_ts)
    close = float(last["close"])
    sma = float(closed["close"].astype(float).rolling(SMA, min_periods=SMA).mean().iloc[-1])
    targets = declared_weights([SYMBOL], {SYMBOL: 1.0} if flag else {})
    meta = {
        "name": NAME,
        "lab_run": LAB_RUN,
        "symbol": SYMBOL,
        "purpose": "signal_efficacy",
        "variant": "textbook_connors",
        "not_teaser_fit": True,
        "execution_lag": 0,
        "bb_n": BB_N,
        "bb_k": BB_K,
        "pctb_entry": PCTB_ENTRY,
        "consec": CONSEC,
        "pctb_exit": PCTB_EXIT,
        "sma": SMA,
        "bar_open": str(bar_ts),
        "close_time": str(close_ts),
        "close": close,
        "sma200": sma,
        "pctb": float(band.iloc[-1]) if pd.notna(band.iloc[-1]) else None,
        "above_sma200": bool(close > sma) if pd.notna(sma) else False,
        "entered": bool(entries.iloc[-1]),
        "exited": bool(exits.iloc[-1]),
        "in_position": flag,
        "target": 1.0 if flag else 0.0,
        "n_bars": int(len(closed)),
    }
    return targets, close_ts, meta


def persist_signal(meta: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {}
    if STATE_FILE.exists():
        payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    payload[STRATEGY_ID] = meta
    payload["_updated_utc"] = pd.Timestamp.now(tz="UTC").isoformat()
    STATE_FILE.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def build(context: StrategyContext) -> StrategyResult:
    targets, bar_ts, meta = latest_book(context.as_of)
    persist_signal(meta)
    signal_ts = _as_utc(bar_ts).strftime("%Y-%m-%dT%H:%M:%SZ")
    pctb_s = "nan" if meta["pctb"] is None else f"{meta['pctb']:.3f}"
    print(
        f"{STRATEGY_ID} {SYMBOL} bar={meta['bar_open']} close={meta['close']:.2f} "
        f"pctb={pctb_s} entered={meta['entered']} "
        f"in_pos={meta['in_position']} target={targets}"
    )
    return StrategyResult(
        strategy_id=STRATEGY_ID,
        portfolio=None,
        current_exposure=targets,
        rebalancing_style=REBALANCING_STYLE,
        signal_timestamp=signal_ts,
        run_frequency=RUN_FREQUENCY,
        metadata=meta,
    )
