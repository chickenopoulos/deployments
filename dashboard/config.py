from __future__ import annotations

import os
from pathlib import Path

DASHBOARD_ROOT = Path(__file__).resolve().parent
DEPLOYMENTS_ROOT = DASHBOARD_ROOT.parent

DEFAULT_PARQUET_ROOT = Path(
    os.environ.get(
        "STF_PARQUET_ROOT",
        "/root/shadow-trading-framework/data/parquet",
    )
)

DEFAULT_ALLOCATION = float(os.environ.get("DASHBOARD_DEFAULT_ALLOCATION", "10000"))
STREAMLIT_PORT = int(os.environ.get("DASHBOARD_PORT", "8502"))
STREAMLIT_ADDRESS = os.environ.get("DASHBOARD_ADDRESS", "0.0.0.0")

DATASETS = ("equity", "fills", "positions", "rebalance")
