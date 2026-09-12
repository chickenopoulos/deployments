#!/usr/bin/env bash
# G7 Yahoo FX overnight squeeze (id23–id29).
#   close — after the Yahoo 23:00 UTC daily stamp has rolled (cron: Tue-Sat 00:10).
#   open  — next weekday after the new daily bar prints: flatten at the open.
# Keep date formats here — crontab treats '%' as newline.
set -euo pipefail

source /root/deployments/scripts/env.sh

PHASE="${1:-}"
if [[ "${PHASE}" != "open" && "${PHASE}" != "close" ]]; then
  echo "Usage: $0 <open|close>" >&2
  exit 1
fi

mkdir -p /var/log/deployments
export G7_VC_PHASE="${PHASE}"

echo "==== START G7 vol-compression ${PHASE} $(date -u '+%Y-%m-%d %H:%M:%S UTC') ===="

cd /root
python -m deployments.scrappers.yfinance_ohlcv --interval 1d --universe g7_fx >> /var/log/deployments/yfinance_ohlcv_g7_fx.log 2>&1

for sid in id23 id24 id25 id26 id27 id28 id29; do
  echo "==== running ${sid} phase=${PHASE} ===="
  bash /root/deployments/scripts/run_strategy.sh "${sid}" >> /var/log/deployments/strategy_${sid}.log 2>&1
done

echo "==== END G7 vol-compression ${PHASE} $(date -u '+%Y-%m-%d %H:%M:%S UTC') ===="
