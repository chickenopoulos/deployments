#!/usr/bin/env bash
# G7 Dukascopy inside-bar compression EW: id34 locked, id35 representatives.
# Daily bar stamp T is complete at T+1d. Mon-Sat 00:15 UTC covers Fri's bar.
# Keep date formats here — crontab treats '%' as newline.
set -euo pipefail

source /root/deployments/scripts/env.sh

mkdir -p /var/log/deployments

echo "==== START Dukascopy G7 inside-compress id34/id35 $(date -u '+%Y-%m-%d %H:%M:%S UTC') ===="

cd /root
python -m deployments.scrappers.dukascopy_fx --intervals 1d >> /var/log/deployments/dukascopy_fx_1d.log 2>&1

for sid in id34 id35; do
  echo "==== running ${sid} ===="
  bash /root/deployments/scripts/run_strategy.sh "${sid}" >> /var/log/deployments/strategy_${sid}.log 2>&1
done

echo "==== END Dukascopy G7 inside-compress id34/id35 $(date -u '+%Y-%m-%d %H:%M:%S UTC') ===="
