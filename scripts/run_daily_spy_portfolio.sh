#!/usr/bin/env bash
# Daily yfinance refresh (SPY + reconstructed ETF49), then:
#   id14-id17  SPY QS overlay and sleeves
#   id18-id20  Concretum daily analog overnight continuation (mapping A)
#   id31       Macro ETF calendar (TLT ToM + SPY 60/40 overlay)
#   id33       Textbook Connors %B lag-0 MOC on SPY
# Run after the US cash close. Keep date formats here — crontab treats '%' as newline.
set -euo pipefail

source /root/deployments/scripts/env.sh

mkdir -p /var/log/deployments

echo "==== START yfinance equity + id14-20 + id31 + id33 $(date -u '+%Y-%m-%d %H:%M:%S UTC') ===="

cd /root
python -m deployments.scrappers.yfinance_ohlcv --interval 1d >> /var/log/deployments/yfinance_ohlcv_1d.log 2>&1

failures=0
for sid in id14 id15 id16 id17 id18 id19 id20 id31 id33; do
  echo "==== running ${sid} ===="
  if ! bash /root/deployments/scripts/run_strategy.sh "${sid}" >> /var/log/deployments/strategy_${sid}.log 2>&1; then
    echo "ERROR ${sid} failed (see /var/log/deployments/strategy_${sid}.log)"
    failures=$((failures + 1))
  fi
done

echo "==== END yfinance equity + id14-20 + id31 + id33 $(date -u '+%Y-%m-%d %H:%M:%S UTC') ===="
if [ "${failures}" -ne 0 ]; then
  echo "==== ${failures} strategy run(s) failed ===="
  exit 1
fi
