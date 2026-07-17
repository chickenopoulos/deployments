#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_BIN="${ROOT}/env/bin"
STREAMLIT="${ENV_BIN}/streamlit"

export STF_PARQUET_ROOT="${STF_PARQUET_ROOT:-/root/shadow-trading-framework/data/parquet}"
export DASHBOARD_PORT="${DASHBOARD_PORT:-8502}"
export DASHBOARD_ADDRESS="${DASHBOARD_ADDRESS:-0.0.0.0}"

cd "${ROOT}/deployments/dashboard"
exec "${STREAMLIT}" run app.py \
  --server.port="${DASHBOARD_PORT}" \
  --server.address="${DASHBOARD_ADDRESS}" \
  --server.headless=true \
  --browser.gatherUsageStats=false
