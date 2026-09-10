from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from deployments.dashboard.config import DEFAULT_PARQUET_ROOT
from deployments.dashboard.data_loader import (
    _dataset_path,
    _read_parquet,
    list_allocations,
    load_equity,
    load_fills,
    load_positions,
)


def load_rebalance(strategy_id: str, allocation: float, root: Path = DEFAULT_PARQUET_ROOT) -> pd.DataFrame:
    return _read_parquet(_dataset_path(root, "rebalance", strategy_id, allocation))


def reference_allocation(strategy_id: str, root: Path = DEFAULT_PARQUET_ROOT) -> float:
    allocations = list_allocations(strategy_id, root)
    if not allocations:
        return 0.0
    return max(allocations, key=lambda allocation: len(load_equity(strategy_id, allocation, root)))


def _infer_fee_bps(fills: pd.DataFrame) -> float:
    if fills.empty:
        return 4.0
    filled = fills[fills["filled_qty"].astype(float) > 0]
    if filled.empty:
        return 4.0
    notional = filled["filled_qty"].astype(float) * filled["fill_price"].astype(float)
    fee_bps = filled["fee"].astype(float) / notional * 1e4
    return float(fee_bps.median())


def _index_positions(positions: pd.DataFrame) -> tuple[dict[int, dict[str, float]], dict[int, dict[str, float]]]:
    marks_by_ts: dict[int, dict[str, float]] = {}
    targets_by_ts: dict[int, dict[str, float]] = {}
    for ts, grp in positions.groupby("execution_timestamp_ms"):
        ts_key = int(ts)
        marks_by_ts[ts_key] = {row["symbol"]: float(row["mark_price"]) for _, row in grp.iterrows()}
        targets_by_ts[ts_key] = {row["symbol"]: float(row["target_weight"]) for _, row in grp.iterrows()}
    return marks_by_ts, targets_by_ts


def compute_unit_signal_equity(strategy_id: str, root: Path = DEFAULT_PARQUET_ROOT) -> pd.DataFrame:
    ref_alloc = reference_allocation(strategy_id, root)
    if ref_alloc <= 0:
        return pd.DataFrame()

    equity_ref = load_equity(strategy_id, ref_alloc, root).sort_values("execution_timestamp_ms")
    positions_ref = load_positions(strategy_id, ref_alloc, root)
    rebalance_ref = load_rebalance(strategy_id, ref_alloc, root).set_index("execution_timestamp_ms")
    fee_bps = _infer_fee_bps(load_fills(strategy_id, ref_alloc, root))

    if equity_ref.empty:
        return pd.DataFrame()

    marks_by_ts, targets_by_ts = _index_positions(positions_ref)

    unit_equity = 1.0
    weights: dict[str, float] = {}
    prev_marks: dict[str, float] = {}
    prev_equity_ref: float | None = None
    prev_net_ref = 0.0
    fees_cum = 0.0
    funding_cum = 0.0
    rows: list[dict] = []

    for _, row in equity_ref.iterrows():
        ts = int(row["execution_timestamp_ms"])
        marks = marks_by_ts.get(ts)
        targets = targets_by_ts.get(ts, {})
        if not marks:
            continue

        if ts in rebalance_ref.index:
            funding_cash = float(rebalance_ref.loc[ts, "funding_cash"])
        else:
            funding_cash = 0.0

        if prev_marks:
            price_return = 0.0
            for symbol, mark in marks.items():
                weight = weights.get(symbol, 0.0)
                previous_mark = prev_marks.get(symbol)
                if weight != 0.0 and previous_mark and previous_mark > 0:
                    price_return += weight * (mark / previous_mark - 1.0)
            unit_equity *= 1.0 + price_return

        if funding_cash != 0.0 and prev_equity_ref and prev_equity_ref > 0:
            funding_return = funding_cash / prev_equity_ref
            net_signal = sum(weights.values())
            if abs(prev_net_ref) > 1e-12:
                unit_equity *= 1.0 + funding_return * (net_signal / prev_net_ref)
            elif abs(net_signal) < 1e-12:
                pass
            else:
                unit_equity *= 1.0 + funding_return
            funding_cum += unit_equity * funding_return * (
                net_signal / prev_net_ref if abs(prev_net_ref) > 1e-12 else 1.0
            )

        if bool(row["rebalance"]):
            symbols = set(weights) | set(targets)
            turnover = sum(abs(targets.get(symbol, 0.0) - weights.get(symbol, 0.0)) for symbol in symbols)
            if turnover > 0:
                fee = unit_equity * turnover * fee_bps / 1e4
                unit_equity -= fee
                fees_cum += fee
            weights = dict(targets)

        gross = sum(abs(weight) for weight in weights.values())
        net = sum(weights.values())
        rows.append(
            {
                "strategy_id": strategy_id,
                "allocation": ref_alloc,
                "signal_timestamp": row["signal_timestamp"],
                "execution_timestamp_ms": ts,
                "rebalance": bool(row["rebalance"]),
                "unit_equity": unit_equity,
                "gross_exposure": gross,
                "net_exposure": net,
                "fees_cum": fees_cum,
                "funding_cum": funding_cum,
            }
        )

        prev_marks = marks
        prev_equity_ref = float(row["equity"])
        prev_net_ref = float(row["net_exposure"])

    out = pd.DataFrame(rows)
    if out.empty:
        return out

    out["timestamp"] = pd.to_datetime(out["execution_timestamp_ms"], unit="ms", utc=True)
    out["signal_timestamp"] = pd.to_datetime(out["signal_timestamp"], utc=True, errors="coerce")
    return out


def _build_signal_fills(
    strategy_id: str,
    allocation: float,
    unit_equity_df: pd.DataFrame,
    positions_ref: pd.DataFrame,
    fee_bps: float,
) -> pd.DataFrame:
    if unit_equity_df.empty:
        return pd.DataFrame()

    marks_by_ts, targets_by_ts = _index_positions(positions_ref)
    weights: dict[str, float] = {}
    rows: list[dict] = []

    for _, row in unit_equity_df.iterrows():
        if not bool(row["rebalance"]):
            continue

        ts = int(row["execution_timestamp_ms"])
        marks = marks_by_ts.get(ts, {})
        targets = targets_by_ts.get(ts, {})
        equity = float(row["unit_equity"]) * allocation
        if not marks or not targets:
            continue

        for symbol in sorted(set(weights) | set(targets)):
            old_weight = weights.get(symbol, 0.0)
            new_weight = targets.get(symbol, 0.0)
            if abs(new_weight - old_weight) < 1e-12:
                continue

            mark = marks[symbol]
            if mark <= 0:
                continue

            old_qty = old_weight * equity / mark
            new_qty = new_weight * equity / mark
            order_qty = abs(new_qty - old_qty)
            side = "BUY" if new_qty > old_qty else "SELL"
            fee = order_qty * mark * fee_bps / 1e4

            rows.append(
                {
                    "strategy_id": strategy_id,
                    "allocation": allocation,
                    "symbol": symbol,
                    "side": side,
                    "requested_qty": order_qty,
                    "filled_qty": order_qty,
                    "fill_price": mark,
                    "fee": fee,
                    "slippage_bps": 0.0,
                    "execution_style": "taker",
                    "signal_timestamp": row["signal_timestamp"],
                    "execution_timestamp_ms": ts,
                    "bid_price": mark,
                    "ask_price": mark,
                    "bid_qty": 0.0,
                    "ask_qty": 0.0,
                    "max_bar_notional": 0.0,
                    "fill_ratio": 1.0,
                }
            )

        weights = dict(targets)

    if not rows:
        return pd.DataFrame()

    fills = pd.DataFrame(rows)
    fills["timestamp"] = pd.to_datetime(fills["execution_timestamp_ms"], unit="ms", utc=True)
    fills["signal_timestamp"] = pd.to_datetime(fills["signal_timestamp"], utc=True, errors="coerce")
    return fills.sort_values("execution_timestamp_ms").reset_index(drop=True)


def _build_signal_positions(
    strategy_id: str,
    allocation: float,
    unit_equity_df: pd.DataFrame,
    positions_ref: pd.DataFrame,
) -> pd.DataFrame:
    if unit_equity_df.empty:
        return pd.DataFrame()

    marks_by_ts, targets_by_ts = _index_positions(positions_ref)
    rows: list[dict] = []

    for _, row in unit_equity_df.iterrows():
        ts = int(row["execution_timestamp_ms"])
        marks = marks_by_ts.get(ts, {})
        targets = targets_by_ts.get(ts, {})
        equity = float(row["unit_equity"]) * allocation
        if not marks:
            continue

        for symbol, target_weight in targets.items():
            mark = marks.get(symbol)
            if mark is None or mark <= 0 or abs(target_weight) < 1e-12:
                continue
            qty = target_weight * equity / mark
            rows.append(
                {
                    "strategy_id": strategy_id,
                    "allocation": allocation,
                    "signal_timestamp": row["signal_timestamp"],
                    "execution_timestamp_ms": ts,
                    "rebalance": bool(row["rebalance"]),
                    "symbol": symbol,
                    "qty": qty,
                    "avg_entry_price": mark,
                    "mark_price": mark,
                    "position_value": qty * mark,
                    "actual_weight": target_weight,
                    "target_weight": target_weight,
                }
            )

    if not rows:
        return pd.DataFrame()

    positions = pd.DataFrame(rows)
    positions["timestamp"] = pd.to_datetime(positions["execution_timestamp_ms"], unit="ms", utc=True)
    positions["signal_timestamp"] = pd.to_datetime(positions["signal_timestamp"], utc=True, errors="coerce")
    return positions


def replay_signal_simulation(
    strategy_id: str,
    allocation: float,
    root: Path = DEFAULT_PARQUET_ROOT,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    unit_equity_df = compute_unit_signal_equity(strategy_id, root)
    if unit_equity_df.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    ref_alloc = reference_allocation(strategy_id, root)
    positions_ref = load_positions(strategy_id, ref_alloc, root)
    fee_bps = _infer_fee_bps(load_fills(strategy_id, ref_alloc, root))

    equity = unit_equity_df.copy()
    equity["equity"] = equity["unit_equity"] * allocation
    equity["allocation"] = allocation
    equity["cash"] = np.nan
    equity["realized_pnl"] = equity["equity"] - allocation

    fills = _build_signal_fills(strategy_id, allocation, unit_equity_df, positions_ref, fee_bps)
    positions = _build_signal_positions(strategy_id, allocation, unit_equity_df, positions_ref)
    return equity, fills, positions


def current_signal_positions(positions: pd.DataFrame) -> pd.DataFrame:
    if positions.empty:
        return pd.DataFrame(
            columns=[
                "symbol",
                "side",
                "qty",
                "avg_entry_price",
                "mark_price",
                "position_value",
                "actual_weight",
                "target_weight",
                "as_of",
            ]
        )

    latest_ts = positions["timestamp"].max()
    snap = positions[positions["timestamp"] == latest_ts].copy()
    snap = snap[snap["qty"].abs() > 1e-12]
    if snap.empty:
        return pd.DataFrame(
            columns=[
                "symbol",
                "side",
                "qty",
                "avg_entry_price",
                "mark_price",
                "position_value",
                "actual_weight",
                "target_weight",
                "as_of",
            ]
        )

    snap["side"] = np.where(snap["qty"] > 0, "long", "short")
    snap["as_of"] = latest_ts
    cols = [
        "symbol",
        "side",
        "qty",
        "avg_entry_price",
        "mark_price",
        "position_value",
        "actual_weight",
        "target_weight",
        "as_of",
    ]
    return snap[cols].sort_values("symbol").reset_index(drop=True)
