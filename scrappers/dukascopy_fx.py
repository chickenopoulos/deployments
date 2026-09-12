"""Refresh Dukascopy G7 FX daily bars for STF id34/id35.

Incremental: the wrapper fetch merges from last-bar minus overlap, then this
module copies the 1d panel into deployments/data/dukascopy_fx_1d.parquet.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import pandas as pd

from deployments.paths import DATA_DIR

WRAPPER_ROOT = Path("/root/thequantgpt-wrapper")
WRAPPER_FETCH = WRAPPER_ROOT / "scripts" / "dukascopy_fetch_fx.py"
WRAPPER_VENV_PY = WRAPPER_ROOT / ".venv" / "bin" / "python"
WRAPPER_1D = WRAPPER_ROOT / "data" / "dukascopy" / "fx" / "dukascopy_g7_ohlcv_1d.parquet"
OUTPUT_NAME = "dukascopy_fx_1d.parquet"
PAIRS = ("EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Incremental Dukascopy G7 FX 1d refresh.")
    parser.add_argument("--intervals", nargs="*", default=["1d"], choices=("1d", "1h"))
    parser.add_argument("--overlap-days", type=int, default=7)
    parser.add_argument("--full-refresh", action="store_true")
    parser.add_argument(
        "--skip-fetch",
        action="store_true",
        help="Only copy existing wrapper parquet into deployments/data.",
    )
    return parser.parse_args()


def _python() -> str:
    if WRAPPER_VENV_PY.exists():
        return str(WRAPPER_VENV_PY)
    return sys.executable


def fetch_wrapper(args: argparse.Namespace) -> None:
    cmd = [
        _python(),
        str(WRAPPER_FETCH),
        "--intervals",
        *args.intervals,
        "--symbols",
        *PAIRS,
        "--overlap-days",
        str(args.overlap_days),
    ]
    if args.full_refresh:
        cmd.append("--full-refresh")
    print(" ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=str(WRAPPER_ROOT))


def sync_deployments_panel() -> pd.DataFrame:
    if not WRAPPER_1D.exists():
        raise FileNotFoundError(f"Missing Dukascopy panel {WRAPPER_1D}")
    panel = pd.read_parquet(WRAPPER_1D)
    panel["time"] = pd.to_datetime(panel["time"], utc=True)
    out = panel.rename(columns={"time": "open_time"}).copy()
    out["close_time"] = out["open_time"] + pd.Timedelta(days=1)
    dest = DATA_DIR / OUTPUT_NAME
    dest.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(dest, index=False)
    assets = sorted(out["asset"].astype(str).unique().tolist())
    print(f"Wrote {len(out)} rows ({len(assets)} assets) to {dest}")
    print(f"span {out['open_time'].min()} → {out['open_time'].max()}")
    return out


def main() -> None:
    args = parse_args()
    if not args.skip_fetch:
        fetch_wrapper(args)
    sync_deployments_panel()


if __name__ == "__main__":
    main()
