from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from deployments.dashboard.config import DEFAULT_PARQUET_ROOT


def _dataset_path(root: Path, dataset: str, strategy_id: str, allocation: float) -> Path:
    alloc = int(allocation) if allocation == int(allocation) else allocation
    return root / dataset / f"strategy_id={strategy_id}" / f"allocation={alloc}" / "data.parquet"


def list_strategy_ids(root: Path = DEFAULT_PARQUET_ROOT) -> list[str]:
    equity_root = root / "equity"
    if not equity_root.exists():
        return []
    ids = sorted(
        p.name.replace("strategy_id=", "")
        for p in equity_root.glob("strategy_id=*")
        if p.is_dir()
    )
    return ids


def list_allocations(strategy_id: str, root: Path = DEFAULT_PARQUET_ROOT) -> list[float]:
    strategy_root = root / "equity" / f"strategy_id={strategy_id}"
    if not strategy_root.exists():
        return []
    allocs = []
    for p in strategy_root.glob("allocation=*"):
        try:
            allocs.append(float(p.name.replace("allocation=", "")))
        except ValueError:
            continue
    return sorted(allocs)


def _read_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def load_equity(strategy_id: str, allocation: float, root: Path = DEFAULT_PARQUET_ROOT) -> pd.DataFrame:
    df = _read_parquet(_dataset_path(root, "equity", strategy_id, allocation))
    if df.empty:
        return df
    out = df.copy()
    out["timestamp"] = pd.to_datetime(out["execution_timestamp_ms"], unit="ms", utc=True)
    out["signal_timestamp"] = pd.to_datetime(out["signal_timestamp"], utc=True, errors="coerce")
    return out.sort_values("timestamp").reset_index(drop=True)


def load_fills(strategy_id: str, allocation: float, root: Path = DEFAULT_PARQUET_ROOT) -> pd.DataFrame:
    df = _read_parquet(_dataset_path(root, "fills", strategy_id, allocation))
    if df.empty:
        return df
    out = df.copy()
    out["timestamp"] = pd.to_datetime(out["execution_timestamp_ms"], unit="ms", utc=True)
    out["signal_timestamp"] = pd.to_datetime(out["signal_timestamp"], utc=True, errors="coerce")
    return out.sort_values("timestamp").reset_index(drop=True)


def load_positions(strategy_id: str, allocation: float, root: Path = DEFAULT_PARQUET_ROOT) -> pd.DataFrame:
    df = _read_parquet(_dataset_path(root, "positions", strategy_id, allocation))
    if df.empty:
        return df
    out = df.copy()
    out["timestamp"] = pd.to_datetime(out["execution_timestamp_ms"], unit="ms", utc=True)
    out["signal_timestamp"] = pd.to_datetime(out["signal_timestamp"], utc=True, errors="coerce")
    return out.sort_values("timestamp").reset_index(drop=True)


def current_positions(strategy_id: str, allocation: float, root: Path = DEFAULT_PARQUET_ROOT) -> pd.DataFrame:
    positions = load_positions(strategy_id, allocation, root)
    if positions.empty:
        return positions

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


def build_trades_from_fills(fills: pd.DataFrame) -> pd.DataFrame:
    if fills.empty:
        return pd.DataFrame(
            columns=[
                "trade_id",
                "symbol",
                "side",
                "entry_time",
                "exit_time",
                "entry_price",
                "exit_price",
                "qty",
                "gross_pnl",
                "fees",
                "net_pnl",
            ]
        )

    rows: list[dict] = []
    trade_id = 1

    for symbol, grp in fills.sort_values("execution_timestamp_ms").groupby("symbol"):
        pos = 0.0
        entry_price = 0.0
        entry_time = None
        entry_fees = 0.0
        open_qty = 0.0
        open_side: str | None = None

        for _, fill in grp.iterrows():
            signed_qty = fill["filled_qty"] if fill["side"] == "BUY" else -fill["filled_qty"]
            ts = fill["timestamp"]
            fee = float(fill.get("fee", 0.0) or 0.0)
            price = float(fill["fill_price"])

            if pos == 0:
                pos = signed_qty
                open_qty = abs(pos)
                open_side = "long" if pos > 0 else "short"
                entry_price = price
                entry_time = ts
                entry_fees = fee
                continue

            same_direction = (pos > 0 and signed_qty > 0) or (pos < 0 and signed_qty < 0)
            if same_direction:
                new_abs = abs(pos) + abs(signed_qty)
                entry_price = ((abs(pos) * entry_price) + (abs(signed_qty) * price)) / new_abs
                pos += signed_qty
                open_qty = abs(pos)
                entry_fees += fee
                continue

            close_qty = min(abs(signed_qty), abs(pos))
            exit_price = price
            exit_time = ts
            exit_fees = fee * (close_qty / abs(signed_qty)) if signed_qty != 0 else fee

            if open_side == "long":
                gross_pnl = close_qty * (exit_price - entry_price)
            else:
                gross_pnl = close_qty * (entry_price - exit_price)

            total_fees = entry_fees + exit_fees
            rows.append(
                {
                    "trade_id": trade_id,
                    "symbol": symbol,
                    "side": open_side,
                    "entry_time": entry_time,
                    "exit_time": exit_time,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "qty": close_qty,
                    "gross_pnl": gross_pnl,
                    "fees": total_fees,
                    "net_pnl": gross_pnl - total_fees,
                }
            )
            trade_id += 1

            remaining = pos + signed_qty
            if abs(remaining) < 1e-12:
                pos = 0.0
                open_side = None
                open_qty = 0.0
                entry_fees = 0.0
            elif (pos > 0 > remaining) or (pos < 0 < remaining):
                pos = remaining
                open_side = "long" if pos > 0 else "short"
                open_qty = abs(pos)
                entry_price = price
                entry_time = ts
                entry_fees = fee * (1 - close_qty / abs(signed_qty)) if signed_qty != 0 else 0.0
            else:
                pos = remaining
                open_qty = abs(pos)
                entry_fees = 0.0

    return pd.DataFrame(rows)


