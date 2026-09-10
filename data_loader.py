from __future__ import annotations

from pathlib import Path

import pandas as pd

from deployments.paths import DATA_DIR


def _read_parquet(filename: str) -> pd.DataFrame:
    path = DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Required dataset not found: {path}")
    return pd.read_parquet(path)


def load_binance_ohlcv(interval: str = "1d") -> pd.DataFrame:
    suffix = interval.replace('/', '_')
    filename = f"binance_futures_ohlcv_{suffix}.parquet"
    return _read_parquet(filename)


def load_bgeometrics() -> pd.DataFrame:
    return _read_parquet("bgeometrics_data.parquet")


def load_coinglass_orderbook() -> pd.DataFrame:
    return _read_parquet("binance_futures_orderbook_pair_coinglass.parquet")


def load_coinglass_funding_rate() -> pd.DataFrame:
    return _read_parquet("binance_futures_funding_rate_coinglass.parquet")


def load_coinglass_funding_rate_oi_weight() -> pd.DataFrame:
    return _read_parquet("binance_futures_funding_rate_oi_weight_coinglass.parquet")


def load_coinglass_basis() -> pd.DataFrame:
    return _read_parquet("binance_futures_basis_coinglass.parquet")


def load_yfinance_ohlcv(interval: str = "1d") -> pd.DataFrame:
    suffix = interval.replace("/", "_")
    return _read_parquet(f"yfinance_ohlcv_{suffix}.parquet")
