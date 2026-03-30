from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from deployments.paths import STATE_DIR
from deployments.strategy_types import StrategyResult


def _sign(x: float) -> int:
    return 1 if x > 0 else -1 if x < 0 else 0


def _normalize_targets(targets: dict[str, float]) -> dict[str, float]:
    cleaned = {str(k): float(v) for k, v in targets.items() if float(v) != 0.0}
    return dict(sorted(cleaned.items()))


def load_previous_targets(state_path: Path | None = None) -> dict[str, dict[str, float]]:
    path = state_path or (STATE_DIR / "last_targets.json")
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)
    strategies = raw.get("strategies", [])
    out: dict[str, dict[str, float]] = {}
    for item in strategies:
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


def merge_targets_payload(previous: dict[str, dict[str, float]], payload: dict) -> dict:
    merged = {
        str(strategy_id): {str(k): float(v) for k, v in targets.items()}
        for strategy_id, targets in previous.items()
    }

    latest_signal_timestamp = payload["signal_timestamp"]

    for item in payload.get("strategies", []):
        strategy_id = str(item["strategy_id"])
        merged[strategy_id] = {
            str(k): float(v) for k, v in item.get("targets", {}).items()
        }
        item_signal_timestamp = item.get("signal_timestamp")
        if item_signal_timestamp and item_signal_timestamp > latest_signal_timestamp:
            latest_signal_timestamp = item_signal_timestamp

    return {
        "signal_timestamp": latest_signal_timestamp,
        "strategies": [
            {
                "strategy_id": strategy_id,
                "signal_timestamp": latest_signal_timestamp,
                "rebalance": True,
                "targets": dict(sorted(targets.items())),
            }
            for strategy_id, targets in sorted(merged.items())
        ],
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
