#!/usr/bin/env bash
# Hourly Binance 1h scrape, then De Nicola 2h fade (id13) on even UTC hours.
#
# Invoked from crontab. Keep date formats here — crontab treats an unescaped
# percent-sign as a newline and will truncate the job.
set -euo pipefail

source /root/deployments/scripts/env.sh

mkdir -p /var/log/deployments

echo "==== START hourly ohlcv $(date -u '+%Y-%m-%d %H:%M:%S UTC') ===="

cd /root
python -m deployments.scrappers.binance_ohlcv --interval 1h >> /var/log/deployments/binance_ohlcv_1h.log 2>&1

hour=$(date -u +%H)
if (( 10#$hour % 2 == 0 )); then
  echo "==== even UTC hour ${hour}: running id13 ===="
  bash /root/deployments/scripts/run_strategy.sh id13 >> /var/log/deployments/strategy_id13.log 2>&1
else
  echo "==== odd UTC hour ${hour}: skip id13 ===="
fi

echo "==== END hourly ohlcv $(date -u '+%Y-%m-%d %H:%M:%S UTC') ===="
