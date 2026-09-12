"""G7 Dukascopy inside-bar compression EW books for STF id34/id35.

Lab: thequantgpt-wrapper/runs/audjpy_inside_compress

Locked fingerprint (id34, every sleeve):
  strict inside bar, close still lower, mother close < open,
  inside/mother range <= 0.70, mother range >= 0.8 ATR(14).
  Buy next open. Stop at the inside-bar low, not live on the fill bar.
  Profit-exit when close recovers the mother high, else 6-bar time stop.

id35 uses each sleeve's IS median-stable representative. Not a new canonical.

Overnight target is 1/7 of NAV per pair still long after that daily close.
Saturdays dropped. Forming (incomplete) daily bars are excluded.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd

from deployments.data_loader import load_dukascopy_fx
from deployments.paths import STATE_DIR
from deployments.strategy_types import StrategyContext, StrategyResult
from deployments.utils.turnaround_wednesday import overnight_after_close

LAB_RUN = "audjpy_inside_compress"
G7 = ("EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD")
WEIGHT = 1.0 / 7.0
ATR_N = 14
FEE = 0.0
SLIPPAGE = 0.0001
REBALANCING_STYLE = "on_sign_change"
RUN_FREQUENCY = "1d"
STATE_FILE = STATE_DIR / "inside_compress_fx.json"

LOCKED = {
    "max_inside_mother_range_ratio": 0.70,
    "min_mother_atr": 0.80,
    "max_hold": 6,
}

# Per-sleeve median-stable cells from the existing IS PSA grid. Not adopted as canonical.
REPRESENTATIVES: dict[str, dict[str, float]] = {
    "EURUSD": {"max_inside_mother_range_ratio": 0.90, "min_mother_atr": 0.00, "max_hold": 6},
    "GBPUSD": {"max_inside_mother_range_ratio": 0.80, "min_mother_atr": 0.80, "max_hold": 5},
    "USDJPY": {"max_inside_mother_range_ratio": 0.70, "min_mother_atr": 1.00, "max_hold": 10},
    "USDCHF": {"max_inside_mother_range_ratio": 0.60, "min_mother_atr": 0.50, "max_hold": 6},
    "AUDUSD": {"max_inside_mother_range_ratio": 0.90, "min_mother_atr": 0.50, "max_hold": 8},
    "USDCAD": {"max_inside_mother_range_ratio": 0.90, "min_mother_atr": 0.80, "max_hold": 5},
    "NZDUSD": {"max_inside_mother_range_ratio": 0.60, "min_mother_atr": 0.00, "max_hold": 5},
}

BOOKS = {
    "id34": {
        "name": "G7 inside-compress EW (locked fingerprint)",
        "variant": "locked_fingerprint",
        "params_by_pair": {pair: dict(LOCKED) for pair in G7},
        "not_canonical": False,
    },
    "id35": {
        "name": "G7 inside-compress EW (per-sleeve PSA representatives)",
        "variant": "psa_representatives",
        "params_by_pair": {pair: dict(REPRESENTATIVES[pair]) for pair in G7},
        "not_canonical": True,
    },
}


def stf_symbol(pair: str) -> str:
    return f"{pair}.DK"


def _as_utc(ts: pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int = ATR_N) -> np.ndarray:
    prev = np.roll(close, 1)
    prev[0] = close[0]
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    out = np.full_like(tr, np.nan, dtype=float)
    if len(tr) < n:
        return out
    out[n - 1] = tr[:n].mean()
    alpha = 1.0 / n
    for i in range(n, len(tr)):
        out[i] = out[i - 1] * (1.0 - alpha) + tr[i] * alpha
    return out


def signal_mask(ohlcv: pd.DataFrame, params: dict) -> np.ndarray:
    o = ohlcv["open"].astype(np.float64).to_numpy()
    h = ohlcv["high"].astype(np.float64).to_numpy()
    l = ohlcv["low"].astype(np.float64).to_numpy()
    c = ohlcv["close"].astype(np.float64).to_numpy()
    atr = _atr(h, l, c, ATR_N)
    inside = (h < np.roll(h, 1)) & (l > np.roll(l, 1))
    inside[0] = False
    close_lower = c < np.roll(c, 1)
    close_lower[0] = False
    mother_down = np.roll(c, 1) < np.roll(o, 1)
    mother_down[0] = False
    mother_rng = np.roll(h, 1) - np.roll(l, 1)
    ratio = (h - l) / np.where(mother_rng > 0, mother_rng, np.nan)
    mother_atr = np.roll(atr, 1)
    min_atr = float(params["min_mother_atr"])
    wide = np.isfinite(mother_atr) & (mother_rng >= min_atr * mother_atr)
    return inside & close_lower & mother_down & np.isfinite(ratio) & (
        ratio <= float(params["max_inside_mother_range_ratio"])
    ) & wide


def entries_exits(ohlcv: pd.DataFrame, params: dict) -> tuple[pd.Series, pd.Series, np.ndarray]:
    """Next-open entry; stop not live on the fill bar; TP / time-stop after that."""
    o = ohlcv["open"].astype(np.float64).to_numpy()
    h = ohlcv["high"].astype(np.float64).to_numpy()
    l = ohlcv["low"].astype(np.float64).to_numpy()
    c = ohlcv["close"].astype(np.float64).to_numpy()
    sig = signal_mask(ohlcv, params)
    n = len(c)
    entries = np.zeros(n, dtype=bool)
    exits = np.zeros(n, dtype=bool)
    max_hold = int(params["max_hold"])
    in_pos = False
    entry_i = -1
    sl_px = np.nan
    tp_ref = np.nan
    i = 0
    while i < n:
        if not in_pos:
            if bool(sig[i]) and i + 1 < n and np.isfinite(o[i + 1]):
                entry_i = i + 1
                entries[entry_i] = True
                sl_px = float(l[i])
                tp_ref = float(h[i - 1]) if i > 0 else float(h[i])
                in_pos = True
                i = entry_i + 1
                continue
            i += 1
            continue
        held = i - entry_i
        hit_sl = i > entry_i and l[i] <= sl_px
        hit_tp = c[i] >= tp_ref
        if hit_sl or hit_tp or held >= max_hold:
            exits[i] = True
            in_pos = False
        i += 1
    idx = ohlcv.index
    return pd.Series(entries, index=idx), pd.Series(exits, index=idx), sig


def drop_saturday(ohlcv: pd.DataFrame) -> pd.DataFrame:
    return ohlcv.loc[ohlcv.index.dayofweek != 5].copy()


def completed_bars(ohlcv: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Keep bars whose 24h window has finished (stamp T is complete at T+1d)."""
    as_of_utc = _as_utc(as_of)
    done = ohlcv.index + pd.Timedelta(days=1) <= as_of_utc
    closed = ohlcv.loc[done]
    if closed.empty:
        raise ValueError(f"No completed Dukascopy daily bars as of {as_of_utc}")
    return closed


def load_pair_ohlcv(pair: str, ohlcv: pd.DataFrame | None = None) -> pd.DataFrame:
    df = ohlcv if ohlcv is not None else load_dukascopy_fx("1d")
    rows = df.loc[df["asset"].astype(str).str.upper() == pair.upper()].copy()
    if rows.empty:
        raise ValueError(f"No Dukascopy rows for {pair}")
    time_col = "open_time" if "open_time" in rows.columns else "time"
    rows[time_col] = pd.to_datetime(rows[time_col], utc=True)
    out = rows.set_index(time_col).sort_index()
    return drop_saturday(out)


def pair_overnight(
    pair: str,
    params: dict,
    as_of: pd.Timestamp,
    ohlcv: pd.DataFrame | None = None,
) -> tuple[float, dict[str, Any]]:
    raw = load_pair_ohlcv(pair, ohlcv=ohlcv)
    closed = completed_bars(raw, as_of)
    entries, exits, sig = entries_exits(closed, params)
    overnight = overnight_after_close(entries, exits)
    last = closed.iloc[-1]
    flag = float(overnight.iloc[-1]) > 0
    meta = {
        "pair": pair,
        "stf_symbol": stf_symbol(pair),
        "bar_open": str(closed.index[-1]),
        "close": float(last["close"]),
        "open": float(last["open"]),
        "high": float(last["high"]),
        "low": float(last["low"]),
        "setup_today": bool(sig[-1]),
        "entered": bool(entries.iloc[-1]),
        "exited": bool(exits.iloc[-1]),
        "in_position": flag,
        "params": {k: params[k] for k in ("max_inside_mother_range_ratio", "min_mother_atr", "max_hold")},
        "n_bars": int(len(closed)),
    }
    return (WEIGHT if flag else 0.0), meta


def latest_book(
    as_of: pd.Timestamp,
    strategy_id: str,
    *,
    ohlcv: pd.DataFrame | None = None,
) -> tuple[dict[str, float], pd.Timestamp, dict[str, Any]]:
    spec = BOOKS[strategy_id]
    targets: dict[str, float] = {}
    sleeves: dict[str, Any] = {}
    last_ts: pd.Timestamp | None = None
    for pair in G7:
        weight, meta = pair_overnight(pair, spec["params_by_pair"][pair], as_of, ohlcv=ohlcv)
        sleeves[pair] = meta
        bar_ts = pd.Timestamp(meta["bar_open"])
        last_ts = bar_ts if last_ts is None else max(last_ts, bar_ts)
        # Always declare the sleeve so STF can mark equity on fully-flat days.
        targets[stf_symbol(pair)] = float(weight)
    n_long = sum(1 for m in sleeves.values() if m["in_position"])
    payload = {
        "name": spec["name"],
        "lab_run": LAB_RUN,
        "variant": spec["variant"],
        "not_canonical": spec["not_canonical"],
        "purpose": "signal_efficacy",
        "data_source": "dukascopy",
        "weight_per_sleeve": WEIGHT,
        "n_long": n_long,
        "gross_weight": float(n_long * WEIGHT),
        "sleeves": sleeves,
        "target": dict(targets),
        "rules": (
            "strict inside + close lower + mother down; next-open; "
            "inside-low stop not live on fill bar; mother-high close or time stop"
        ),
    }
    if last_ts is None:
        raise ValueError("No Dukascopy bars for G7 inside-compress")
    return targets, last_ts, payload


def persist_signal(strategy_id: str, meta: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {}
    if STATE_FILE.exists():
        payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    payload[strategy_id] = {
        k: v for k, v in meta.items() if k != "sleeves"
    }
    payload[strategy_id]["sleeves"] = {
        pair: {kk: vv for kk, vv in sm.items() if kk != "params"} | {"params": sm["params"]}
        for pair, sm in meta.get("sleeves", {}).items()
    }
    payload["_updated_utc"] = pd.Timestamp.now(tz="UTC").isoformat()
    STATE_FILE.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def build_for(context: StrategyContext, strategy_id: str) -> StrategyResult:
    targets, bar_ts, meta = latest_book(context.as_of, strategy_id)
    persist_signal(strategy_id, meta)
    signal_ts = _as_utc(bar_ts).strftime("%Y-%m-%dT%H:%M:%SZ")
    longs = [p for p, s in meta["sleeves"].items() if s["in_position"]]
    print(
        f"{strategy_id} {meta['variant']} n_long={meta['n_long']} "
        f"gross={meta['gross_weight']:.3f} longs={longs} bar={meta['sleeves'][G7[0]]['bar_open']}"
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
