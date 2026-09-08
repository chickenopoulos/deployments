#!/usr/bin/env bash
set -euo pipefail

source /root/deployments/scripts/env.sh

if [ "$#" -lt 1 ]; then
  echo "Usage: $0 <strategy_id> [--as-of UTC_TIMESTAMP]"
  exit 1
fi

STRATEGY="$1"
shift
AS_OF=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --as-of)
      if [ "$#" -lt 2 ]; then
        echo "Missing value for --as-of" >&2
        exit 1
      fi
      AS_OF="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: $0 <strategy_id> [--as-of UTC_TIMESTAMP]" >&2
      exit 1
      ;;
  esac
done

LOG_DIR="$DEPLOYMENTS_ROOT/logs"
mkdir -p "$LOG_DIR"

TIMESTAMP=$(date +%F_%H-%M-%S)
LOG_FILE="$LOG_DIR/${STRATEGY}_${TIMESTAMP}.log"

exec > >(tee -a "$LOG_FILE") 2>&1

echo "==== START $STRATEGY $(date -u '+%Y-%m-%d %H:%M:%S UTC') ===="
if [ -n "$AS_OF" ]; then
  echo "==== as-of $AS_OF ===="
fi

TARGET_FILE="$STF_ROOT/data/targets/targets.json"

cd "$DEPLOYMENTS_ROOT"

echo "==== Build targets for $STRATEGY ===="
pipeline_args=(
  python -m deployments.run_pipeline
  --strategy "$STRATEGY"
  --target-output "$TARGET_FILE"
)
if [ -n "$AS_OF" ]; then
  pipeline_args+=(--as-of "$AS_OF")
fi
"${pipeline_args[@]}"

cd "$STF_ROOT"

echo "==== Run STF for $STRATEGY ===="
shadow-sim --config-dir config --strategy-id "$STRATEGY"

echo "==== END $STRATEGY $(date -u '+%Y-%m-%d %H:%M:%S UTC') ===="
echo "==== Log written to $LOG_FILE ===="
