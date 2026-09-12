#!/usr/bin/env bash
# Daily Mulvaney/Concretum Yahoo-proxy scrape, then id21, id22, ES Turnaround
# Wednesday lag-0 (id30), and ES High10 lag-1 PSA representative (id32).
# Run after CME Globex day session (17:00 CT ≈ 22:00/23:00 UTC).
# Keep date formats here — crontab treats '%' as newline.
set -euo pipefail

source /root/deployments/scripts/env.sh

mkdir -p /var/log/deployments

echo "==== START mulvaney yfinance + id21-id22-id30-id32 $(date -u '+%Y-%m-%d %H:%M:%S UTC') ===="

cd /root
python -m deployments.scrappers.yfinance_ohlcv --interval 1d --universe mulvaney >> /var/log/deployments/yfinance_ohlcv_mulvaney.log 2>&1

for sid in id21 id22 id30 id32; do
  echo "==== running ${sid} ===="
  bash /root/deployments/scripts/run_strategy.sh "${sid}" >> /var/log/deployments/strategy_${sid}.log 2>&1
done

echo "==== END mulvaney yfinance + id21-id22-id30-id32 $(date -u '+%Y-%m-%d %H:%M:%S UTC') ===="
