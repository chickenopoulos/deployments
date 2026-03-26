from __future__ import annotations

import argparse
import importlib
from pathlib import Path

import pandas as pd
import yaml
from dotenv import load_dotenv

from deployments.paths import CONFIG_DIR
from deployments.target_writer import (
    build_targets_payload,
    load_previous_targets,
    merge_targets_payload,
    persist_last_targets,
    write_targets,
)
from deployments.types import StrategyContext


def _load_strategy_config() -> dict:
    cfg_path = CONFIG_DIR / "strategies.yaml"
    with cfg_path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _enabled_strategy_ids(config: dict) -> list[str]:
    strategies = config.get("strategies", {})
    enabled = []
    for strategy_id, payload in strategies.items():
        if isinstance(payload, dict) and payload.get("enabled", False):
            enabled.append(strategy_id)
    return enabled


def _discover_strategy(strategy_id: str):
    return importlib.import_module(f"deployments.strategies.{strategy_id}")


def _run_strategy(module, as_of: pd.Timestamp):
    context = StrategyContext(as_of=as_of)
    return module.build(context)


def _resolve_strategy_ids(config: dict, strategy: str | None) -> list[str]:
    enabled_ids = _enabled_strategy_ids(config)

    if strategy is None:
        if not enabled_ids:
            raise ValueError("No enabled strategies found in config/strategies.yaml")
        return enabled_ids

    strategies = config.get("strategies", {})
    if strategy not in strategies:
        raise ValueError(f"Strategy '{strategy}' not found in config/strategies.yaml")

    payload = strategies.get(strategy, {})
    if not isinstance(payload, dict):
        raise ValueError(f"Strategy '{strategy}' has invalid config payload")

    if not payload.get("enabled", False):
        raise ValueError(f"Strategy '{strategy}' is disabled in config/strategies.yaml")

    return [strategy]


def run_pipeline(
    target_output: str | Path,
    as_of: str | None = None,
    strategy: str | None = None,
) -> Path:
    load_dotenv()
    strategy_cfg = _load_strategy_config()
    strategy_ids = _resolve_strategy_ids(strategy_cfg, strategy)

    as_of_ts = pd.Timestamp(as_of, tz="UTC") if as_of else pd.Timestamp.now(tz="UTC")

    results = []
    for strategy_id in strategy_ids:
        module = _discover_strategy(strategy_id)
        result = _run_strategy(module, as_of_ts)
        results.append(result)

    previous = load_previous_targets()
    payload = build_targets_payload(results, previous)
    target_path = write_targets(payload, target_output)

    merged_payload = merge_targets_payload(previous, payload)
    persist_last_targets(merged_payload)

    return target_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run DPL pipeline and write STF targets.json"
    )
    parser.add_argument(
        "--target-output",
        required=True,
        help="Output path for STF targets json",
    )
    parser.add_argument(
        "--as-of",
        default=None,
        help="Override UTC timestamp, e.g. 2026-03-24T00:00:00Z",
    )
    parser.add_argument(
        "--strategy",
        default=None,
        help="Run only one enabled strategy, e.g. id4",
    )
    args = parser.parse_args()

    path = run_pipeline(
        target_output=args.target_output,
        as_of=args.as_of,
        strategy=args.strategy,
    )
    print(f"Wrote targets to {path}")


if __name__ == "__main__":
    main()
