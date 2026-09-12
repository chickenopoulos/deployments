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

### Yahoo Finance (cash equities / ETFs)

Temporary adapter until IBKR. Writes `data/yfinance_ohlcv_1d.parquet`.

```bash
python -m deployments.scrappers.yfinance_ohlcv --interval 1d
```

### Dukascopy G7 FX (id34 / id35)

Incremental daily mid (bid+ask). Writes wrapper `data/dukascopy/fx/` and `deployments/data/dukascopy_fx_1d.parquet`.

```bash
python -m deployments.scrappers.dukascopy_fx --intervals 1d
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

SPY overlay + sleeves + ETF49 + id31 macro calendar + id33 Connors %B (after the US cash close scrape):

```bash
bash /root/deployments/scripts/run_daily_spy_portfolio.sh
```

Mulvaney/Concretum replica (Yahoo futures/index proxies; after CME close):

```bash
bash /root/deployments/scripts/run_daily_mulvaney_cta.sh
```

id21 is the canonical Concretum-default book. id22 is the in-sample PSA peak (long-only, lag 0), not a second canonical spec. id30 is ES Turnaround Wednesday lag-0 on the same Yahoo `ES=F` series (Tue down + IBS<0.25, QS-or-hold-5). id32 is the High10 lag-1 PSA representative (lookback 12, IBS entry 0.25, IBS exit 0.90, hold 5) on the same `ES=F` series — not canonical High10 (10 / 0.20 / 0.90 / 5).

G7 Yahoo FX overnight squeeze (separate books; after Yahoo daily close / next open):

```bash
bash /root/deployments/scripts/run_daily_g7_vol_compression.sh close
bash /root/deployments/scripts/run_daily_g7_vol_compression.sh open
```

id23–id29 are EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, USDCAD, NZDUSD. Frozen BB(20,2)×IBS<0.15, buy Yahoo close, sell next Yahoo open. This incubates a yfinance snapshot bounce, not a Dukascopy FX session. Use Signal simulation on the dashboard.

id31 is the Robot James macro ETF calendar (lab: `rj_macro_etf_calendar`): always-on TLT turn-of-month plus a SPY overlay signed by 60/40 SPY/IEF implied rebalance pressure. IEF is signal-only. Same yfinance cash-close scrape as id14–id20.

id33 is textbook Connors %B on SPY cash (lab: `qs_spy_two_mr`): close > SMA(200) and %B of BB(5, 1σ, ddof=0) < 0.2 for 3 consecutive days; exit %B > 0.8. Lag-0 MOC after the US cash close. This is the public Connors recipe, not the teaser-fit fingerprint (%B < −0.1 / exit > 1.0) and not the PSA representative or grid peak. Seasonal IBS/RSI stays lab-only.

G7 Dukascopy inside-bar compression EW (lab: `audjpy_inside_compress`):

```bash
bash /root/deployments/scripts/run_daily_g7_inside_compress.sh
```

id34 is the locked fingerprint (ratio 0.7, mother ATR 0.8, hold 6) equal-weight 1/7 across EURUSD.DK … NZDUSD.DK. id35 is the same rule with each sleeve’s IS median-stable representative — not a second canonical. Data is Dukascopy daily mid (bid/ask kept for the paper spread), not Yahoo. Saturday sessions are dropped. Buy next open; inside-low stop is not live on the fill bar.
---

## Scheduling (Cron)

All pipelines and strategies are scheduled via `crontab`.

### Key Principles
- Each pipeline runs on a fixed schedule
- Strategies run immediately after their dependent data pipeline
- `flock` is used to prevent overlapping executions
- All jobs use the same environment (`/root/env`)
- **Never put date format percent-signs in crontab.** Cron replaces an unescaped percent-sign with a newline and feeds the rest of the line to stdin. Put `date` formats in a shell script (see `scripts/run_hourly_ohlcv_and_id13.sh`).

The live crontab lives in `config/crontab`. Install with:

```bash
bash /root/deployments/scripts/install_crontab.sh
```

### Production Crontab

Source of truth: `config/crontab`. That file must not contain percent-signs.

```cron
SHELL=/bin/bash
PATH=/root/env/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
PYTHONPATH=/root

# Binance OHLCV hourly at HH:05, then id13 on even UTC hours (see wrapper).
5 * * * * flock -n /tmp/binance_ohlcv_1h.lock bash /root/deployments/scripts/run_hourly_ohlcv_and_id13.sh >> /var/log/deployments/hourly_ohlcv_id13.log 2>&1

# Binance OHLCV daily at 00:05, then id8, id9, id10, id11, id12
5 0 * * * flock -n /tmp/binance_ohlcv_1d_id8_id9.lock -c 'cd /root && python -m deployments.scrappers.binance_ohlcv --interval 1d >> /var/log/deployments/binance_ohlcv_1d.log 2>&1 && bash /root/deployments/scripts/run_strategy.sh id8 >> /var/log/deployments/strategy_id8.log 2>&1 && bash /root/deployments/scripts/run_strategy.sh id9 >> /var/log/deployments/strategy_id9.log 2>&1 && bash /root/deployments/scripts/run_strategy.sh id10 >> /var/log/deployments/strategy_id10.log 2>&1 && bash /root/deployments/scripts/run_strategy.sh id11 >> /var/log/deployments/strategy_id11.log 2>&1 && bash /root/deployments/scripts/run_strategy.sh id12 >> /var/log/deployments/strategy_id12.log 2>&1'

# Coinglass daily at 04:00, then id4, id5, id6
0 4 * * * flock -n /tmp/coinglass_id456.lock -c 'cd /root && python -m deployments.scrappers.coinglass >> /var/log/deployments/coinglass.log 2>&1 && bash /root/deployments/scripts/run_strategy.sh id4 >> /var/log/deployments/strategy_id4.log 2>&1 && bash /root/deployments/scripts/run_strategy.sh id5 >> /var/log/deployments/strategy_id5.log 2>&1 && bash /root/deployments/scripts/run_strategy.sh id6 >> /var/log/deployments/strategy_id6.log 2>&1'

# Bgeometrics daily at 10:00, then id2, id3, id7
0 10 * * * flock -n /tmp/bgeometrics_id237.lock bash /root/deployments/scripts/run_daily_bgeometrics_id237.sh >> /var/log/deployments/bgeometrics_id237.log 2>&1

# Equity yfinance after US cash close, then id14-id20, id31, and id33
15 21 * * 1-5 flock -n /tmp/equity_yfinance_id14_20.lock bash /root/deployments/scripts/run_daily_spy_portfolio.sh >> /var/log/deployments/equity_yfinance_id14_20.log 2>&1

# Mulvaney/Concretum Yahoo proxies after CME 17:00 CT, then id21-id22-id30-id32
0 23 * * 1-5 flock -n /tmp/mulvaney_yfinance_id21_22.lock bash /root/deployments/scripts/run_daily_mulvaney_cta.sh >> /var/log/deployments/mulvaney_yfinance_id21_22.log 2>&1

# G7 Yahoo FX overnight squeeze (id23-id29)
10 0 * * 2-6 flock -n /tmp/g7_vc_yf_close.lock bash /root/deployments/scripts/run_daily_g7_vol_compression.sh close >> /var/log/deployments/g7_vol_compression_close.log 2>&1
20 0 * * 1-5 flock -n /tmp/g7_vc_yf_open.lock bash /root/deployments/scripts/run_daily_g7_vol_compression.sh open >> /var/log/deployments/g7_vol_compression_open.log 2>&1

# G7 Dukascopy inside-bar compression EW (id34 locked, id35 representatives)
15 0 * * 1-6 flock -n /tmp/g7_inside_compress_duka.lock bash /root/deployments/scripts/run_daily_g7_inside_compress.sh >> /var/log/deployments/g7_inside_compress.log 2>&1
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
