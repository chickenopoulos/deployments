# Deployments + Shadow Trading Framework (STF)

## Overview
This repository contains data pipelines, scrapers, and strategy execution logic for the Shadow Trading Framework (STF).

It is designed to:
- Fetch and normalize market + derivatives data
- Store structured datasets (Parquet)
- Build trading signals ("targets")
- Run systematic strategies

All pipelines are executed via `python -m`, and orchestration is handled via `cron`.

---

## Project Structure

```
deployments/
├── scrappers/              # Data ingestion (Coinglass, Binance, etc.)
├── strategies/             # Strategy logic (e.g., id1–id7)
├── scripts/                # Utility + strategy runners
├── utils/                  # Shared utilities
├── data/
│   ├── parquet/            # Processed datasets
│   ├── targets/            # Strategy outputs
│   └── ...                 # Other state/output dirs
├── run_pipeline.py         # Main pipeline entrypoint
```

---

## Setup

### 1. Environment

```bash
python3 -m venv /root/env
source /root/env/bin/activate
pip install -r requirements.txt
```

### 2. Environment Variables

```bash
export COINGLASS_API_KEY=your_key_here
...
```

---

## Data Pipelines

All pipelines are executed via `python -m`:

### Binance OHLCV

```bash
python -m deployments.scrappers.binance_ohlcv --interval 1h
python -m deployments.scrappers.binance_ohlcv --interval 1d
```

### Coinglass

```bash
python -m deployments.scrappers.coinglass
```

### Bgeometrics

```bash
python -m deployments.scrappers.bgeometrics
```

---

## Strategy Execution

Strategies are executed via:

```bash
bash /root/deployments/scripts/run_strategy.sh <strategy_id>
```

Example:

```bash
bash /root/deployments/scripts/run_strategy.sh id1
```

---

## Scheduling (Cron)

All pipelines and strategies are scheduled via `crontab`.

### Key Principles
- Each pipeline runs on a fixed schedule
- Strategies run immediately after their dependent data pipeline
- `flock` is used to prevent overlapping executions
- All jobs use the same environment (`/root/env`)

### Production Crontab

```cron
SHELL=/bin/bash
PATH=/root/env/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
PYTHONPATH=/root/deployments

# Binance OHLCV hourly at HH:05 (excluding midnight)
5 1-23 * * * flock -n /tmp/binance_ohlcv_1h.lock -c 'cd /root/deployments && python -m deployments.scrappers.binance_ohlcv --interval 1h >> /var/log/deployments/binance_ohlcv_1h.log 2>&1'

# Binance OHLCV daily at 00:05, then id1
5 0 * * * flock -n /tmp/binance_ohlcv_1d_id1.lock -c 'cd /root/deployments && python -m deployments.scrappers.binance_ohlcv --interval 1d >> /var/log/deployments/binance_ohlcv_1d.log 2>&1 && bash /root/deployments/scripts/run_strategy.sh id1 >> /var/log/deployments/strategy_id1.log 2>&1'

# Coinglass daily at 04:00, then id4, id5, id6
0 4 * * * flock -n /tmp/coinglass_id456.lock -c 'cd /root/deployments && python -m deployments.scrappers.coinglass >> /var/log/deployments/coinglass.log 2>&1 && bash /root/deployments/scripts/run_strategy.sh id4 >> /var/log/deployments/strategy_id4.log 2>&1 && bash /root/deployments/scripts/run_strategy.sh id5 >> /var/log/deployments/strategy_id5.log 2>&1 && bash /root/deployments/scripts/run_strategy.sh id6 >> /var/log/deployments/strategy_id6.log 2>&1'

# Bgeometrics daily at 10:00, then id2, id3, id7
0 10 * * * flock -n /tmp/bgeometrics_id237.lock -c 'cd /root/deployments && python -m deployments.scrappers.bgeometrics >> /var/log/deployments/bgeometrics.log 2>&1 && bash /root/deployments/scripts/run_strategy.sh id2 >> /var/log/deployments/strategy_id2.log 2>&1 && bash /root/deployments/scripts/run_strategy.sh id3 >> /var/log/deployments/strategy_id3.log 2>&1 && bash /root/deployments/scripts/run_strategy.sh id7 >> /var/log/deployments/strategy_id7.log 2>&1'
```

### Logs

All logs are written to:

```
/var/log/deployments/
```

Create directory:

```bash
mkdir -p /var/log/deployments
```

---

## Resetting State

To reset all STF outputs:

```bash
bash /root/reset_stf_state.sh
```

This will:
- Reset targets
- Remove parquet data
- Clear intermediate outputs

---

## Data Storage

All processed datasets are stored under:

```
data/parquet/
```

---

## Notes

- Always use the same virtual environment (`/root/env`)
- Use small limits when debugging APIs
- `flock` ensures no overlapping runs
- Strategy execution depends on successful upstream data pipelines

---

## License

Private / Internal Project
