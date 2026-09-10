#!/usr/bin/env bash
# Install deployments/config/crontab after rejecting percent-signs.
# Cron treats an unescaped percent-sign as a newline, which previously
# truncated the id13 even-hour job.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CRONTAB_FILE="$ROOT/config/crontab"

if [[ ! -f "$CRONTAB_FILE" ]]; then
  echo "Missing $CRONTAB_FILE" >&2
  exit 1
fi

if grep -n '%' "$CRONTAB_FILE"; then
  echo "ERROR: $CRONTAB_FILE contains a percent-sign." >&2
  echo "Cron replaces unescaped percent-signs with newlines. Put date formats in a shell script instead." >&2
  exit 1
fi

crontab "$CRONTAB_FILE"
echo "Installed crontab from $CRONTAB_FILE"
crontab -l
