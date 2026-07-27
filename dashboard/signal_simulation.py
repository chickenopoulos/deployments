from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from shadow_capacity_sim.engine.accounting import apply_fill, mark_equity
from shadow_capacity_sim.engine.portfolio import actual_weights
from shadow_capacity_sim.models.types import Book, FillResult

from deployments.dashboard.config import DEFAULT_PARQUET_ROOT
from deployments.dashboard.data_loader import (
    _dataset_path,
    _read_parquet,
    load_equity,
    load_fills,
    load_positions,
)


def load_rebalance(strategy_id: str, allocation: float, root: Path = DEFAULT_PARQUET_ROOT) -> pd.DataFrame:
    return _read_parquet(_dataset_path(root, "rebalance", strategy_id, allocation))


def to_signal_fills(fills: pd.DataFrame) -> pd.DataFrame:
    if fills.empty:
        return fills.copy()

    out = fills.copy()
    filled = out["filled_qty"].astype(float)
    requested = out["requested_qty"].astype(float)
    fee = out.get("fee", 0.0).fillna(0.0).astype(float)
    price = out["fill_price"].astype(float)

    scaled_fee = fee * (requested / filled)
    fallback_fee = requested * price * 0.0004
    out["fee"] = scaled_fee.where(filled > 0, fallback_fee)
    out["filled_qty"] = requested
    out["fill_ratio"] = 1.0
    return out


def _signal_fee(row: pd.Series) -> float:
    requested = float(row["requested_qty"])
    filled = float(row["filled_qty"])
    fee = float(row.get("fee", 0.0) or 0.0)
    price = float(row["fill_price"])
    if requested <= 0:
        return 0.0
    if filled > 0:
        return fee * (requested / filled)
    return requested * price * 0.0004


def _row_to_signal_fill(row: pd.Series) -> FillResult:
    return FillResult(
        strategy_id=row["strategy_id"],
        allocation=float(row["allocation"]),
        symbol=row["symbol"],
        side=row["side"],
        requested_qty=float(row["requested_qty"]),
        filled_qty=float(row["requested_qty"]),
        fill_price=float(row["fill_price"]),
        fee=_signal_fee(row),
        slippage_bps=float(row.get("slippage_bps", 0.0) or 0.0),
        execution_style=row.get("execution_style", "taker"),
        signal_timestamp=row["signal_timestamp"],
        execution_timestamp_ms=int(row["execution_timestamp_ms"]),
        bid_price=float(row["bid_price"]),
        ask_price=float(row["ask_price"]),
        bid_qty=float(row["bid_qty"]),
        ask_qty=float(row["ask_qty"]),
        max_bar_notional=float(row["max_bar_notional"]),
        fill_ratio=1.0,
    )


def _signed_exposure(positions: dict[str, float], marks: dict[str, float]) -> float:
    return sum(float(qty) * float(marks.get(symbol, 0.0)) for symbol, qty in positions.items())


def replay_signal_simulation(
    strategy_id: str,
    allocation: float,
    root: Path = DEFAULT_PARQUET_ROOT,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    equity = load_equity(strategy_id, allocation, root)
    fills = load_fills(strategy_id, allocation, root)
    positions = load_positions(strategy_id, allocation, root)
    rebalance = load_rebalance(strategy_id, allocation, root)

    if equity.empty:
        return equity.copy(), to_signal_fills(fills), pd.DataFrame()

    marks_by_ts = {
        int(ts): {row["symbol"]: float(row["mark_price"]) for _, row in grp.iterrows()}
        for ts, grp in positions.groupby("execution_timestamp_ms")
    }
    target_by_ts = {
        int(ts): {row["symbol"]: float(row["target_weight"]) for _, row in grp.iterrows()}
        for ts, grp in positions.groupby("execution_timestamp_ms")
    }
    trade_pos_by_ts = {
        int(ts): {row["symbol"]: float(row["qty"]) for _, row in grp.iterrows()}
        for ts, grp in positions.groupby("execution_timestamp_ms")
    }
    fills_by_ts = {int(ts): grp for ts, grp in fills.groupby("execution_timestamp_ms")}
    funding_by_ts = {
        int(row["execution_timestamp_ms"]): float(row.get("funding_cash", 0.0) or 0.0)
        for _, row in rebalance.iterrows()
    }

    book = Book(strategy_id=strategy_id, allocation=float(allocation), cash=float(allocation), equity=float(allocation))
    prev_trade_positions: dict[str, float] = {}
    equity_rows: list[dict] = []
    position_rows: list[dict] = []

    for _, row in equity.sort_values("execution_timestamp_ms").iterrows():
        ts = int(row["execution_timestamp_ms"])
        marks = marks_by_ts.get(ts)
        if not marks:
            continue

        mark_equity(book, marks)

        funding_cash = funding_by_ts.get(ts, 0.0)
        if funding_cash != 0.0:
            trade_exposure = _signed_exposure(prev_trade_positions, marks)
            signal_exposure = _signed_exposure(
                {symbol: position.qty for symbol, position in book.positions.items()},
                marks,
            )
            if abs(trade_exposure) > 1e-12:
                scaled_funding = funding_cash * (signal_exposure / trade_exposure)
                book.cash += scaled_funding
                book.funding_cum += scaled_funding
                mark_equity(book, marks)

        if bool(row["rebalance"]) and ts in fills_by_ts:
            for _, fill_row in fills_by_ts[ts].iterrows():
                apply_fill(book, _row_to_signal_fill(fill_row))

        mark_equity(book, marks)
        weights = actual_weights(book, marks)
        gross = sum(abs(weight) for weight in weights.values())
        net = sum(weights.values())
        targets = target_by_ts.get(ts, {})

        equity_rows.append(
            {
                "strategy_id": strategy_id,
                "allocation": allocation,
                "signal_timestamp": row["signal_timestamp"],
                "execution_timestamp_ms": ts,
                "rebalance": bool(row["rebalance"]),
                "equity": book.equity,
                "cash": book.cash,
                "gross_exposure": gross,
                "net_exposure": net,
                "realized_pnl": book.realized_pnl,
                "fees_cum": book.fees_cum,
                "funding_cum": book.funding_cum,
            }
        )

        for symbol, position in book.positions.items():
            if abs(position.qty) < 1e-12:
                continue
            mark_price = marks.get(symbol, 0.0)
            position_rows.append(
                {
                    "strategy_id": strategy_id,
                    "allocation": allocation,
                    "signal_timestamp": row["signal_timestamp"],
                    "execution_timestamp_ms": ts,
                    "rebalance": bool(row["rebalance"]),
                    "symbol": symbol,
                    "qty": position.qty,
                    "avg_entry_price": position.avg_entry_price,
                    "mark_price": mark_price,
                    "position_value": position.qty * mark_price,
                    "actual_weight": weights.get(symbol, 0.0),
                    "target_weight": targets.get(symbol, 0.0),
                }
            )

        prev_trade_positions = trade_pos_by_ts.get(ts, {})

    equity_df = pd.DataFrame(equity_rows)
    equity_df["timestamp"] = pd.to_datetime(equity_df["execution_timestamp_ms"], unit="ms", utc=True)
    equity_df["signal_timestamp"] = pd.to_datetime(equity_df["signal_timestamp"], utc=True, errors="coerce")

    signal_fills = to_signal_fills(fills)
    if not signal_fills.empty:
        signal_fills["timestamp"] = pd.to_datetime(signal_fills["execution_timestamp_ms"], unit="ms", utc=True)
        signal_fills["signal_timestamp"] = pd.to_datetime(signal_fills["signal_timestamp"], utc=True, errors="coerce")

    positions_df = pd.DataFrame(position_rows)
    if not positions_df.empty:
        positions_df["timestamp"] = pd.to_datetime(positions_df["execution_timestamp_ms"], unit="ms", utc=True)
        positions_df["signal_timestamp"] = pd.to_datetime(positions_df["signal_timestamp"], utc=True, errors="coerce")

    return equity_df, signal_fills, positions_df


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
