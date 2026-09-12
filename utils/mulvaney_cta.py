"""Donchian / loss-parity CTA book for STF id21 (canonical) and id22 (PSA best).

Replay of thequantgpt-wrapper/runs/mulvaney_concretum_replica/code/mulvaney_replica.py
on the last *closed* daily bars. Does not flatten at the final bar: remaining
tranches become signed Yahoo weights for STF.

Lab run: mulvaney_concretum_replica. id22 is the IS PSA peak, not a new canonical spec.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

import numpy as np
import pandas as pd

from deployments.data_loader import load_yfinance_ohlcv
from deployments.utils.mulvaney_universe import (
    MARKET_SECTOR,
    N_MARKETS,
    SECTORS,
    YAHOO_BY_CONCRETUM,
    bar_close_utc,
    canonical_yahoo,
)
from deployments.utils.stf_targets import declared_weights

START_DATE = "2000-09-01"
MIN_STOP_FRAC = 0.04
MAX_UNIT_NOTIONAL = 0.25

PARAMS_CANONICAL = {
    "lookback_days": 126,
    "fixed_stop_frac": 0.3,
    "pyramid_cap": 4,
    "pyramid_step_K": 1.0,
    "execution_lag": 1,
    "risk_allocation": "loss_parity",
    "loss_budget": 0.15,
    "direction": "long_short",
    "fee": 0.0,
    "slippage": 0.0,
}

# IS grid peak after N=7201. Same-bar fill (lag 0), long-only, no pyramid.
PARAMS_BEST = {
    "lookback_days": 63,
    "fixed_stop_frac": 0.2,
    "pyramid_cap": 1,
    "pyramid_step_K": 0.5,
    "execution_lag": 0,
    "risk_allocation": "hierarchical_loss_parity",
    "loss_budget": 0.15,
    "direction": "long_only",
    "fee": 0.0,
    "slippage": 0.0,
}


@dataclass
class Tranche:
    direction: int
    entry_i: int
    entry_px: float
    width: float
    aum_at_entry: float
    notional_frac: float
    initial_stop: float


def _as_utc(ts: pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _unit_risk(market: str, n_markets: int, params: Mapping[str, object]) -> float:
    budget = float(params["loss_budget"])
    alloc = str(params["risk_allocation"])
    if alloc == "hierarchical_loss_parity":
        sector = MARKET_SECTOR.get(market, "Other")
        n_sectors = len(SECTORS)
        names = SECTORS.get(sector, [market])
        return budget / n_sectors / max(len(names), 1)
    return budget / max(n_markets, 1)


def simulate_market(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    valid: np.ndarray,
    *,
    market: str,
    n_markets: int,
    params: Mapping[str, object],
    flatten_eod: bool = False,
) -> tuple[np.ndarray, list[Tranche]]:
    """Path-dependent Donchian book. Live callers keep flatten_eod=False."""
    n = len(close)
    lookback = int(params["lookback_days"])
    sf = float(params["fixed_stop_frac"])
    cap = int(params["pyramid_cap"])
    k_step = float(params["pyramid_step_K"])
    lag = int(params["execution_lag"])
    direction_mode = str(params["direction"])
    allow_long = direction_mode in {"long_short", "long_only"}
    allow_short = direction_mode in {"long_short", "short_only"}
    fee = float(params.get("fee", 0.0))
    slip = float(params.get("slippage", 0.0))
    cost_rate = fee + slip

    pnl = np.zeros(n, dtype=float)
    units: list[Tranche] = []
    pending_dir = 0
    pending_width = np.nan
    pending_from = -1

    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    for i in range(n):
        if i + 1 < lookback:
            continue
        sl = slice(i + 1 - lookback, i + 1)
        if not np.all(valid[sl]):
            continue
        upper[i] = float(np.max(high[sl]))
        lower[i] = float(np.min(low[sl]))
    mid = 0.5 * (upper + lower)

    def flatten(i: int, px: float) -> None:
        nonlocal units
        if not units:
            return
        for u in units:
            move = u.direction * (px / u.entry_px - 1.0)
            prev_aum = aum[i - 1] if i else u.aum_at_entry
            pnl[i] += u.notional_frac * (u.aum_at_entry / max(prev_aum, 1e-12)) * move
            pnl[i] -= u.notional_frac * cost_rate
        units = []

    aum = np.ones(n, dtype=float)
    risk = _unit_risk(market, n_markets, params)

    for i in range(n):
        if i == 0 or not valid[i] or not valid[i - 1]:
            continue
        px = float(close[i])
        px_prev = float(close[i - 1])
        if not np.isfinite(px) or not np.isfinite(px_prev) or px_prev <= 0 or px <= 0:
            continue

        if units:
            for u in units:
                move = u.direction * (px / px_prev - 1.0)
                pnl[i] += u.notional_frac * move

        if units:
            d0 = units[0].direction
            init_stop = units[0].initial_stop
            mid_prev = mid[i - 1]
            if d0 > 0:
                trail = init_stop if not np.isfinite(mid_prev) else max(init_stop, float(mid_prev))
                hit = float(low[i]) <= trail
            else:
                trail = init_stop if not np.isfinite(mid_prev) else min(init_stop, float(mid_prev))
                hit = float(high[i]) >= trail
            if hit:
                for u in units:
                    move_cc = u.direction * (px / px_prev - 1.0)
                    pnl[i] -= u.notional_frac * move_cc
                if d0 > 0:
                    fill = min(px_prev, trail)
                    if px < trail:
                        fill = px
                else:
                    fill = max(px_prev, trail)
                    if px > trail:
                        fill = px
                flatten(i, float(fill))
                pending_dir = 0
                continue

        if pending_dir != 0 and i - pending_from >= lag and not units:
            w = pending_width
            if np.isfinite(w) and w > 0 and px > 0:
                stop_dist = max(sf * w, MIN_STOP_FRAC * px)
                notion = min(risk * px / stop_dist, MAX_UNIT_NOTIONAL)
                init_stop = px - pending_dir * stop_dist
                step = k_step * stop_dist
                n_units = 1
                if step > 0 and np.isfinite(upper[i - 1]) and np.isfinite(lower[i - 1]):
                    brk = float(upper[i - 1] if pending_dir > 0 else lower[i - 1])
                    extra = int(np.floor(abs(px - brk) / step))
                    n_units = min(cap, max(1, 1 + extra))
                for _ in range(n_units):
                    units.append(
                        Tranche(
                            direction=pending_dir,
                            entry_i=i,
                            entry_px=px,
                            width=w,
                            aum_at_entry=1.0,
                            notional_frac=notion,
                            initial_stop=init_stop,
                        )
                    )
                    pnl[i] -= notion * cost_rate
            pending_dir = 0

        if units and len(units) < cap:
            u0 = units[0]
            step = k_step * sf * u0.width
            last_px = units[-1].entry_px
            target = last_px + u0.direction * step
            reached = float(high[i]) >= target if u0.direction > 0 else float(low[i]) <= target
            if reached and i - units[-1].entry_i >= lag and step > 0:
                stop_dist = max(sf * u0.width, MIN_STOP_FRAC * px)
                notion = min(risk * px / stop_dist, MAX_UNIT_NOTIONAL)
                init_stop = px - u0.direction * stop_dist
                units.append(
                    Tranche(
                        direction=u0.direction,
                        entry_i=i,
                        entry_px=px,
                        width=u0.width,
                        aum_at_entry=1.0,
                        notional_frac=notion,
                        initial_stop=init_stop,
                    )
                )
                pnl[i] -= notion * cost_rate

        if units or pending_dir != 0:
            continue
        if i < lookback + lag:
            continue
        up_prev = upper[i - 1]
        dn_prev = lower[i - 1]
        w_prev = (upper[i - 1] - lower[i - 1]) if np.isfinite(up_prev) and np.isfinite(dn_prev) else np.nan
        if not (np.isfinite(up_prev) and np.isfinite(dn_prev) and np.isfinite(w_prev) and w_prev > 0):
            continue
        long_sig = allow_long and float(high[i]) >= float(up_prev)
        short_sig = allow_short and float(low[i]) <= float(dn_prev)
        if long_sig and short_sig:
            continue
        if long_sig or short_sig:
            pending_dir = 1 if long_sig else -1
            pending_width = float(w_prev)
            pending_from = i
            # PSA / Concretum lag=0: fill this bar's close (one unit; no warm-start).
            if lag == 0 and not units:
                w = pending_width
                if np.isfinite(w) and w > 0 and px > 0:
                    stop_dist = max(sf * w, MIN_STOP_FRAC * px)
                    notion = min(risk * px / stop_dist, MAX_UNIT_NOTIONAL)
                    init_stop = px - pending_dir * stop_dist
                    units.append(
                        Tranche(
                            direction=pending_dir,
                            entry_i=i,
                            entry_px=px,
                            width=w,
                            aum_at_entry=1.0,
                            notional_frac=notion,
                            initial_stop=init_stop,
                        )
                    )
                    pnl[i] -= notion * cost_rate
                pending_dir = 0

    if flatten_eod and units:
        last_px = float(close[n - 1]) if n else 0.0
        flatten(n - 1, last_px)
    return pnl, units


def net_weight(units: Iterable[Tranche]) -> float:
    return float(sum(u.direction * u.notional_frac for u in units))


def _ensure_close_time(frame: pd.DataFrame, yahoo: str) -> pd.DataFrame:
    out = frame.copy()
    out["close_time"] = [bar_close_utc(ts, yahoo) for ts in out.index]
    return out


def closed_symbol_ohlcv(ohlcv: pd.DataFrame, as_of: pd.Timestamp, yahoo: str) -> pd.DataFrame:
    """Keep daily bars whose venue close is <= as_of."""
    as_of_utc = _as_utc(as_of)
    frame = ohlcv.copy()
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise TypeError("ohlcv index must be DatetimeIndex (open_time)")
    idx = frame.index
    if idx.tz is None:
        frame = frame.copy()
        frame.index = pd.to_datetime(idx, utc=True)
    else:
        frame.index = idx.tz_convert("UTC")
    frame = _ensure_close_time(frame, yahoo)
    closed = frame.loc[frame["close_time"] <= as_of_utc]
    if closed.empty:
        raise ValueError(f"No closed daily bars for {yahoo} as of {as_of_utc}")
    return closed


def load_yahoo_frames() -> dict[str, pd.DataFrame]:
    df = load_yfinance_ohlcv("1d")
    if df.empty:
        raise ValueError("yfinance_ohlcv_1d.parquet is empty")
    df = df.copy()
    df["asset"] = df["asset"].astype(str).map(canonical_yahoo)
    df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
    if "close_time" in df.columns:
        df["close_time"] = pd.to_datetime(df["close_time"], utc=True)
    frames: dict[str, pd.DataFrame] = {}
    for yahoo in YAHOO_BY_CONCRETUM.values():
        sub = df.loc[df["asset"] == yahoo]
        if sub.empty:
            continue
        indexed = sub.set_index("open_time").sort_index()
        indexed = indexed[~indexed.index.duplicated(keep="last")]
        frames[yahoo] = indexed
    if len(frames) < 5:
        raise ValueError(f"Mulvaney universe too small in yfinance parquet: {sorted(frames)}")
    return frames


def _closed_frames(
    frames: dict[str, pd.DataFrame],
    as_of: pd.Timestamp,
) -> tuple[dict[str, pd.DataFrame], pd.Timestamp]:
    """Per-name session calendars (do not union across venues)."""
    closed: dict[str, pd.DataFrame] = {}
    close_times: list[pd.Timestamp] = []
    start = pd.Timestamp(START_DATE, tz="UTC")
    for yahoo, raw in frames.items():
        try:
            frame = closed_symbol_ohlcv(raw, as_of, yahoo)
        except ValueError:
            continue
        frame = frame.loc[frame.index >= start]
        if frame.empty:
            continue
        # Native session calendar only. A cross-venue union punches holes in the
        # Donchian window (np.all(valid[lookback]) fails) and the book stays flat.
        cols = [c for c in ("open", "high", "low", "close", "close_time") if c in frame.columns]
        closed[yahoo] = frame[cols]
        close_times.append(pd.Timestamp(frame["close_time"].iloc[-1]))
    if len(closed) < 5:
        raise ValueError("Fewer than 5 Mulvaney names have closed bars as of as_of")
    return closed, _as_utc(max(close_times))


def replay_book(
    params: Mapping[str, object],
    as_of: pd.Timestamp,
    frames: dict[str, pd.DataFrame] | None = None,
) -> tuple[dict[str, float], dict[str, object]]:
    """Replay each market; return Yahoo ticker → signed notional weight."""
    loaded = frames if frames is not None else load_yahoo_frames()
    aligned, signal_ts = _closed_frames(loaded, as_of)
    n_markets = N_MARKETS
    targets = declared_weights(YAHOO_BY_CONCRETUM.values())
    n_units = 0
    n_long = 0
    n_short = 0
    skipped: list[str] = []

    for cid, yahoo in YAHOO_BY_CONCRETUM.items():
        piece = aligned.get(yahoo)
        if piece is None:
            skipped.append(yahoo)
            continue
        high = piece["high"].to_numpy(dtype=float)
        low = piece["low"].to_numpy(dtype=float)
        close = piece["close"].to_numpy(dtype=float)
        valid = (
            np.isfinite(high)
            & np.isfinite(low)
            & np.isfinite(close)
            & (close > 0)
        )
        if int(valid.sum()) < int(params["lookback_days"]) + int(params["execution_lag"]) + 2:
            skipped.append(yahoo)
            continue
        _pnl, units = simulate_market(
            high,
            low,
            close,
            valid,
            market=cid,
            n_markets=n_markets,
            params=params,
            flatten_eod=False,
        )
        weight = net_weight(units)
        n_units += len(units)
        if weight > 0:
            n_long += 1
        elif weight < 0:
            n_short += 1
        targets[yahoo] = weight

    gross = float(sum(abs(v) for v in targets.values()))
    net = float(sum(targets.values()))
    meta = {
        "signal_timestamp": signal_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n_markets": n_markets,
        "n_loaded": n_markets - len(skipped),
        "n_live": n_long + n_short,
        "n_long": n_long,
        "n_short": n_short,
        "n_units": n_units,
        "gross_leverage": gross,
        "net_leverage": net,
        "skipped": skipped,
        "params": dict(params),
        "start_date": START_DATE,
        "min_stop_frac": MIN_STOP_FRAC,
        "max_unit_notional": MAX_UNIT_NOTIONAL,
        "lab_run": "mulvaney_concretum_replica",
    }
    return targets, meta


def latest_book(
    as_of: pd.Timestamp,
    params: Mapping[str, object],
    frames: dict[str, pd.DataFrame] | None = None,
) -> tuple[dict[str, float], dict[str, object]]:
    return replay_book(params, as_of, frames=frames)
