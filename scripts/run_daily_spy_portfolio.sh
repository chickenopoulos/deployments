#!/usr/bin/env bash
# Daily SPY yfinance refresh, then QS overlay (id14) and three sleeves (id15-id17).
# Run after the US cash close. Keep date formats here — crontab treats '%' as newline.
set -euo pipefail

source /root/deployments/scripts/env.sh

mkdir -p /var/log/deployments

echo "==== START spy yfinance + id14-17 $(date -u '+%Y-%m-%d %H:%M:%S UTC') ===="

cd /root
python -m deployments.scrappers.yfinance_ohlcv --interval 1d >> /var/log/deployments/yfinance_ohlcv_1d.log 2>&1

for sid in id14 id15 id16 id17; do
  echo "==== running ${sid} ===="
  bash /root/deployments/scripts/run_strategy.sh "${sid}" >> /var/log/deployments/strategy_${sid}.log 2>&1
done

echo "==== END spy yfinance + id14-17 $(date -u '+%Y-%m-%d %H:%M:%S UTC') ===="
