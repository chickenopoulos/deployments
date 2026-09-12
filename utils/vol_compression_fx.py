"""G7 Yahoo FX overnight squeeze books for STF (id23–id29).

Frozen FXI reconstruction (not re-tuned):
  BB(20, 2) width at a 20-day low AND IBS < 0.15.
  Buy the Yahoo daily close, sell the next Yahoo daily open.

This incubates the yfinance close-to-next-open bounce, which Dukascopy did not
reproduce. Separate STF ids, not a basket. Lab run: vol_compression_cross_asset.

Phases (set G7_VC_PHASE, else inferred from as_of UTC hour):
  close — signal on the last Yahoo daily bar; target 1.0 if squeezed else 0.0.
  open  — flatten so the prior close entry is exited at the next open quote.
  Cron close is Tue–Sat 00:10 UTC so the 23:00 Yahoo stamp has actually rolled.
"""

from __future__ import annotations

import json
import os
from typing import Any

import numpy as np
import pandas as pd

from deployments.data_loader import load_yfinance_ohlcv
from deployments.paths import STATE_DIR
from deployments.strategy_types import StrategyContext, StrategyResult

LAB_RUN = "vol_compression_cross_asset"
BB_PERIOD = 20
BB_K = 2.0
BB_LLV = 20
IBS_THRESH = 0.15
REBALANCING_STYLE = "on_sign_change"
RUN_FREQUENCY = "1d"
STATE_FILE = STATE_DIR / "g7_vol_compression.json"

PAIRS: list[dict[str, str]] = [
    {"strategy_id": "id23", "symbol": "EURUSD", "yahoo": "EURUSD=X"},
    {"strategy_id": "id24", "symbol": "GBPUSD", "yahoo": "GBPUSD=X"},
    {"strategy_id": "id25", "symbol": "USDJPY", "yahoo": "USDJPY=X"},
    {"strategy_id": "id26", "symbol": "USDCHF", "yahoo": "USDCHF=X"},
    {"strategy_id": "id27", "symbol": "AUDUSD", "yahoo": "AUDUSD=X"},
    {"strategy_id": "id28", "symbol": "USDCAD", "yahoo": "USDCAD=X"},
    {"strategy_id": "id29", "symbol": "NZDUSD", "yahoo": "NZDUSD=X"},
]

BY_STRATEGY = {p["strategy_id"]: p for p in PAIRS}
YAHOO_TICKERS = [p["yahoo"] for p in PAIRS]


def _as_utc(ts: pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def phase_for(as_of: pd.Timestamp, override: str | None = None) -> str:
    raw = (override or os.environ.get("G7_VC_PHASE") or "").strip().lower()
    if raw in {"open", "close"}:
        return raw
    hour = int(_as_utc(as_of).hour)
    return "open" if hour < 12 else "close"


def _ibs(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    rng = (high - low).replace(0.0, np.nan)
    return ((close - low) / rng).fillna(0.5)


def setup_mask(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    ibs = _ibs(high, low, close)
    mid = close.rolling(BB_PERIOD).mean()
    sd = close.rolling(BB_PERIOD).std()
    bbw = (2.0 * BB_K * sd) / mid.replace(0.0, np.nan)
    squeeze = bbw <= bbw.rolling(BB_LLV).min()
    return (squeeze & (ibs < IBS_THRESH)).fillna(False).astype(bool)


def load_pair_ohlcv(yahoo: str, ohlcv: pd.DataFrame | None = None) -> pd.DataFrame:
    df = ohlcv if ohlcv is not None else load_yfinance_ohlcv("1d")
    pair = df.loc[df["asset"].astype(str) == yahoo].copy()
    if pair.empty:
        raise ValueError(f"No {yahoo} rows in yfinance_ohlcv_1d.parquet")
    pair["open_time"] = pd.to_datetime(pair["open_time"], utc=True)
    return pair.set_index("open_time").sort_index()


def bars_as_of(ohlcv: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Keep bars whose open_time is <= as_of (Yahoo FX daily is a snapshot series)."""
    as_of_utc = _as_utc(as_of)
    idx = ohlcv.index
    if idx.tz is None:
        ohlcv = ohlcv.copy()
        ohlcv.index = pd.to_datetime(idx, utc=True)
        idx = ohlcv.index
    closed = ohlcv.loc[idx <= as_of_utc]
    if closed.empty:
        raise ValueError(f"No Yahoo FX daily bars as of {as_of_utc}")
    return closed


def latest_book(
    as_of: pd.Timestamp,
    spec: dict[str, str],
    *,
    phase: str | None = None,
    ohlcv: pd.DataFrame | None = None,
) -> tuple[dict[str, float], pd.Timestamp, dict[str, Any]]:
    resolved = phase_for(as_of, phase)
    symbol = spec["symbol"]
    yahoo = spec["yahoo"]
    frame = bars_as_of(load_pair_ohlcv(yahoo, ohlcv=ohlcv), as_of)
    bar_ts = pd.Timestamp(frame.index[-1])
    last = frame.iloc[-1]
    squeezed = False
    weight = 0.0
    if resolved == "close":
        squeezed = bool(setup_mask(frame["high"], frame["low"], frame["close"]).iloc[-1])
        weight = 1.0 if squeezed else 0.0
    targets = {symbol: float(weight)}
    meta = {
        "name": f"{symbol} vol-compression overnight (yfinance)",
        "lab_run": LAB_RUN,
        "symbol": symbol,
        "yahoo": yahoo,
        "phase": resolved,
        "purpose": "signal_efficacy",
        "role": "yfinance_artifact_watch",
        "bar_open": str(bar_ts),
        "close": float(last["close"]),
        "open": float(last["open"]),
        "high": float(last["high"]),
        "low": float(last["low"]),
        "squeezed": squeezed,
        "target": weight,
        "rules": f"BB({BB_PERIOD},{BB_K:g}) LLV{BB_LLV} IBS<{IBS_THRESH}; buy close, sell next open",
        "note": (
            "Yahoo FX daily close-to-next-open is the series under test. "
            "Dukascopy did not show this bounce. Watch Signal simulation."
        ),
    }
    return targets, bar_ts, meta


def persist_signal(spec: dict[str, str], meta: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {}
    if STATE_FILE.exists():
        payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    payload[spec["strategy_id"]] = meta
    payload["_updated_utc"] = pd.Timestamp.now(tz="UTC").isoformat()
    STATE_FILE.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def build_for(context: StrategyContext, strategy_id: str) -> StrategyResult:
    spec = BY_STRATEGY[strategy_id]
    targets, bar_ts, meta = latest_book(context.as_of, spec)
    persist_signal(spec, meta)
    signal_ts = bar_ts.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    print(
        f"{strategy_id} {spec['symbol']} phase={meta['phase']} "
        f"bar={meta['bar_open']} squeezed={meta['squeezed']} target={meta['target']}"
    )
    return StrategyResult(
        strategy_id=strategy_id,
        portfolio=None,
        current_exposure=targets,
        rebalancing_style=REBALANCING_STYLE,
        signal_timestamp=signal_ts,
        run_frequency=RUN_FREQUENCY,
        metadata=meta,
    )
