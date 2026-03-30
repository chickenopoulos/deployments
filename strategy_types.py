from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd


@dataclass
class StrategyContext:
    as_of: pd.Timestamp


@dataclass
class StrategyResult:
    strategy_id: str
    portfolio: Any
    current_exposure: dict[str, float]
    rebalancing_style: str
    signal_timestamp: str
    run_frequency: str
    metadata: dict[str, Any] = field(default_factory=dict)


def utc_now_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
