#!/usr/bin/env bash
set -euo pipefail

source /root/deployments/scripts/env.sh

if [ "$#" -lt 1 ]; then
  echo "Usage: $0 <strategy_id>"
  exit 1
fi

STRATEGY="$1"

LOG_DIR="$DEPLOYMENTS_ROOT/logs"
mkdir -p "$LOG_DIR"

TIMESTAMP=$(date +%F_%H-%M-%S)
LOG_FILE="$LOG_DIR/${STRATEGY}_${TIMESTAMP}.log"

exec > >(tee -a "$LOG_FILE") 2>&1

echo "==== START $STRATEGY $(date -u '+%Y-%m-%d %H:%M:%S UTC') ===="

TARGET_FILE="$STF_ROOT/data/targets/targets.json"

cd "$DEPLOYMENTS_ROOT"

echo "==== Build targets for $STRATEGY ===="
python -m deployments.run_pipeline \
  --strategy "$STRATEGY" \
  --target-output "$TARGET_FILE"

cd "$STF_ROOT"

echo "==== Run STF for $STRATEGY ===="
shadow-sim --config-dir config --strategy-id "$STRATEGY"

echo "==== END $STRATEGY $(date -u '+%Y-%m-%d %H:%M:%S UTC') ===="
echo "==== Log written to $LOG_FILE ===="