from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from deployments.paths import STATE_DIR
from deployments.strategy_types import StrategyResult


def _sign(x: float) -> int:
    return 1 if x > 0 else -1 if x < 0 else 0


def _normalize_targets(targets: dict[str, float]) -> dict[str, float]:
    # Keep explicit zeros so a declared universe (e.g. a fully-flat EW book)
    # still reaches STF for mark-to-market. Sign-change rebalance treats
    # missing the same as 0.0.
    return {str(k): float(v) for k, v in sorted(targets.items())}


def load_last_targets_document(state_path: Path | None = None) -> dict:
    path = state_path or (STATE_DIR / "last_targets.json")
    if not path.exists():
        return {"signal_timestamp": "", "strategies": []}
    with path.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)
    if not isinstance(raw, dict):
        return {"signal_timestamp": "", "strategies": []}
    raw.setdefault("signal_timestamp", "")
    raw.setdefault("strategies", [])
    return raw


def load_previous_targets(state_path: Path | None = None) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for item in load_last_targets_document(state_path).get("strategies", []):
        sid = item.get("strategy_id")
        targets = item.get("targets", {})
        if sid:
            out[str(sid)] = {str(k): float(v) for k, v in targets.items()}
    return out


def compute_rebalance(result: StrategyResult, previous_targets: dict[str, float]) -> bool:
    if result.rebalancing_style == "freq_based":
        return True
    if result.rebalancing_style != "on_sign_change":
        raise ValueError(f"Unsupported rebalancing_style: {result.rebalancing_style}")
    current = _normalize_targets(result.current_exposure)
    symbols = sorted(set(current) | set(previous_targets))
    return any(_sign(current.get(symbol, 0.0)) != _sign(previous_targets.get(symbol, 0.0)) for symbol in symbols)


def build_targets_payload(results: Iterable[StrategyResult], previous: dict[str, dict[str, float]]) -> dict:
    results = list(results)
    if not results:
        raise ValueError("No strategy results were produced")
    signal_timestamp = max(result.signal_timestamp for result in results)
    strategies = []
    for result in results:
        targets = _normalize_targets(result.current_exposure)
        strategies.append({
            "strategy_id": result.strategy_id,
            "signal_timestamp": result.signal_timestamp,
            "rebalance": compute_rebalance(result, previous.get(result.strategy_id, {})),
            "targets": targets,
        })
    return {"signal_timestamp": signal_timestamp, "strategies": strategies}


def _strategy_snapshot(item: dict, default_signal_timestamp: str = "") -> dict:
    strategy_id = str(item.get("strategy_id", ""))
    return {
        "strategy_id": strategy_id,
        "signal_timestamp": str(item.get("signal_timestamp") or default_signal_timestamp or ""),
        "rebalance": bool(item.get("rebalance", True)),
        "targets": {str(k): float(v) for k, v in sorted((item.get("targets") or {}).items())},
    }


def merge_targets_payload(previous: dict, payload: dict) -> dict:
    """Merge new snapshots into last_targets without rewriting other strategies' clocks.

    `previous` may be the full last_targets document or the legacy weights-only map.
    Only strategies present in `payload` are updated. Each row keeps its own
    signal_timestamp so an hourly crypto run cannot make id18 look current.
    """
    by_id: dict[str, dict] = {}
    if isinstance(previous, dict) and isinstance(previous.get("strategies"), list):
        for item in previous.get("strategies") or []:
            sid = str(item.get("strategy_id", ""))
            if sid:
                by_id[sid] = _strategy_snapshot(item)
    else:
        for strategy_id, targets in (previous or {}).items():
            by_id[str(strategy_id)] = _strategy_snapshot(
                {"strategy_id": strategy_id, "targets": targets, "rebalance": True}
            )

    default_ts = str(payload.get("signal_timestamp") or "")
    for item in payload.get("strategies", []):
        sid = str(item["strategy_id"])
        by_id[sid] = _strategy_snapshot(item, default_signal_timestamp=default_ts)

    timestamps = [row["signal_timestamp"] for row in by_id.values() if row.get("signal_timestamp")]
    latest_signal_timestamp = max(timestamps) if timestamps else default_ts
    return {
        "signal_timestamp": latest_signal_timestamp,
        "strategies": [by_id[key] for key in sorted(by_id)],
    }


def write_targets(payload: dict, output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=False)
    return path


def persist_last_targets(payload: dict, state_path: Path | None = None) -> Path:
    path = state_path or (STATE_DIR / "last_targets.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=False)
    return path
