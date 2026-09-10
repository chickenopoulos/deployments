#!/usr/bin/env bash
# Daily bitcoin-data.com refresh, then id2 / id3 / id7.
# Keep date formats here — crontab treats an unescaped percent-sign as a newline.
set -euo pipefail

source /root/deployments/scripts/env.sh

mkdir -p /var/log/deployments

echo "==== START bgeometrics id2/id3/id7 $(date -u '+%Y-%m-%d %H:%M:%S UTC') ===="

cd /root
python -m deployments.scrappers.bgeometrics >> /var/log/deployments/bgeometrics.log 2>&1

for sid in id2 id3 id7; do
  echo "==== running ${sid} ===="
  bash /root/deployments/scripts/run_strategy.sh "${sid}" >> /var/log/deployments/strategy_${sid}.log 2>&1
done

echo "==== END bgeometrics id2/id3/id7 $(date -u '+%Y-%m-%d %H:%M:%S UTC') ===="
