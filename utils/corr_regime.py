"""Correlation-regime market-neutral portfolio signals (id12 production logic)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from deployments.data_loader import load_binance_ohlcv

SMA_WINDOW = 90
CORR_WINDOW = 30
MIN_UNIVERSE = 20
Q_THRESHOLD = 3
DEPTH_QUANTILE = 0.35
FEE = 0.00045
SLIPPAGE = 0.0005

LONG_BASKET = [
    "SOLUSDT", "AVAXUSDT", "DOGEUSDT", "NEARUSDT", "RUNEUSDT",
    "BNBUSDT", "EGLDUSDT", "QTUMUSDT", "ZECUSDT", "ENJUSDT",
]
SHORT_BASKET = [
    "BELUSDT", "SUPERUSDT", "BIGTIMEUSDT", "TNSRUSDT", "C98USDT",
    "MTLUSDT", "LQTYUSDT", "KASUSDT", "MEWUSDT", "ARKUSDT",
]

# IS-calibrated spread magnitudes (frozen at research OOS cut 2025-01-01).
IS_LONG_WEIGHTS = {
    "SOLUSDT": 0.075062,
    "AVAXUSDT": 0.071337,
    "DOGEUSDT": 0.067825,
    "NEARUSDT": 0.056224,
    "RUNEUSDT": 0.052173,
    "BNBUSDT": 0.034462,
    "EGLDUSDT": 0.039266,
    "QTUMUSDT": 0.034462,
    "ZECUSDT": 0.034462,
    "ENJUSDT": 0.034729,
}
IS_SHORT_WEIGHTS = {
    "BELUSDT": 0.064365,
    "SUPERUSDT": 0.048404,
    "BIGTIMEUSDT": 0.048404,
    "TNSRUSDT": 0.048404,
    "C98USDT": 0.048404,
    "MTLUSDT": 0.048404,
    "LQTYUSDT": 0.048404,
    "KASUSDT": 0.048404,
    "MEWUSDT": 0.048404,
    "ARKUSDT": 0.048404,
}


def drop_incomplete_last_bar(close: pd.DataFrame) -> pd.DataFrame:
    """Drop the in-progress UTC daily bar when running shortly after midnight."""
    if close.empty:
        return close
    today = pd.Timestamp.now(tz="UTC").normalize()
    if close.index[-1] >= today:
        return close.iloc[:-1]
    return close


def load_close_panel() -> pd.DataFrame:
    ohlcv = load_binance_ohlcv("1d").copy()
    ohlcv["open_time"] = pd.to_datetime(ohlcv["open_time"], utc=True)
    close = (
        ohlcv.pivot_table(index="open_time", columns="asset", values="close", aggfunc="last")
        .sort_index()
        .astype(float)
    )
    return drop_incomplete_last_bar(close)


def market_depth_pct(close: pd.DataFrame, window: int = SMA_WINDOW) -> pd.Series:
    sma = close.rolling(window, min_periods=window).mean()
    above = close > sma
    valid = close.notna() & sma.notna()
    n_valid = valid.sum(axis=1)
    depth = above.where(valid).sum(axis=1) / n_valid.replace(0, np.nan)
    depth = depth.where(n_valid >= MIN_UNIVERSE)
    return (depth * 100.0).rename("market_depth_pct")


def rolling_mean_pairwise_corr(returns: pd.DataFrame, window: int = CORR_WINDOW) -> pd.Series:
    values = returns.to_numpy(dtype=float)
    index = returns.index
    out = np.full(len(index), np.nan)

    for i in range(window, len(index)):
        block = values[i - window : i]
        valid_cols = np.sum(~np.isnan(block), axis=0) >= window
        if valid_cols.sum() < 2:
            continue
        block = block[:, valid_cols]
        corr = np.corrcoef(block, rowvar=False)
        upper = corr[np.triu_indices(corr.shape[0], k=1)]
        if upper.size:
            out[i] = upper.mean()

    return pd.Series(out, index=index, name="market_corr_30d")


def expanding_corr_quintile(corr: pd.Series) -> pd.Series:
    lagged = corr.shift(1)
    ranks = lagged.expanding(min_periods=120).rank(pct=True)
    quintile = np.ceil(ranks * 5).clip(1, 5)
    return quintile.rename("corr_quintile")


def always_in_market_direction(
    quintile: pd.Series,
    depth: pd.Series,
    *,
    q_threshold: int = Q_THRESHOLD,
    depth_quantile: float = DEPTH_QUANTILE,
) -> pd.Series:
    q = quintile.shift(1)
    depth_lag = depth.shift(1)
    depth_thr = depth_lag.expanding(min_periods=120).quantile(depth_quantile)
    direction = pd.Series(1.0, index=quintile.index)
    flip = (q >= q_threshold) & (depth_lag < depth_thr)
    direction[flip] = -1.0
    return direction


def spread_weighted_targets(
    direction: pd.Series,
    long_weights: dict[str, float],
    short_weights: dict[str, float],
    columns: pd.Index,
) -> pd.DataFrame:
    weights = pd.DataFrame(0.0, index=direction.index, columns=columns)
    for asset, weight in long_weights.items():
        if asset in weights.columns:
            weights[asset] = direction * weight
    for asset, weight in short_weights.items():
        if asset in weights.columns:
            weights[asset] += direction * (-weight)
    return weights


def compute_signal_frame(close: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.Series]:
    """Return spread-weighted target weights and regime direction series."""
    if close is None:
        close = load_close_panel()

    returns = close.pct_change()
    corr = rolling_mean_pairwise_corr(returns)
    quintile = expanding_corr_quintile(corr)
    depth = market_depth_pct(close)
    direction = always_in_market_direction(quintile, depth)
    weights = spread_weighted_targets(direction, IS_LONG_WEIGHTS, IS_SHORT_WEIGHTS, close.columns)
    return weights, direction


def latest_exposure(weights: pd.DataFrame) -> dict[str, float]:
    last = weights.iloc[-1]
    last = last[last.abs() > 1e-8].sort_values()
    return {str(k): float(v) for k, v in last.items()}
