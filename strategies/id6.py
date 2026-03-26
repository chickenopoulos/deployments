from __future__ import annotations

import numpy as np
import pandas as pd
import vectorbt as vbt
import empyrical as ep

from deployments.data_loader import (
    load_binance_ohlcv,
    load_coinglass_basis,
    load_coinglass_funding_rate,
    load_coinglass_funding_rate_oi_weight,
    load_coinglass_orderbook,
)
from deployments.types import StrategyContext, StrategyResult

STRATEGY_ID = "id6"
REBALANCING_STYLE = "freq_based"
RUN_FREQUENCY = "1d"


def quantile_long_short_weights(factor: pd.DataFrame, q: float = 0.2) -> pd.DataFrame:
    ranks = factor.rank(axis=1, method="first", ascending=True)
    n = factor.count(axis=1)
    bottom_cutoff = n * q
    top_cutoff = n * (1 - q)
    bottom_mask = ranks.le(bottom_cutoff, axis=0)
    top_mask = ranks.gt(top_cutoff, axis=0)
    n_bottom = bottom_mask.sum(axis=1)
    n_top = top_mask.sum(axis=1)
    weights = pd.DataFrame(0.0, index=factor.index, columns=factor.columns)
    weights[bottom_mask] = (-1 / (2 * n_bottom)).values.repeat(bottom_mask.shape[1]).reshape(bottom_mask.shape)
    weights[top_mask] = (1 / (2 * n_top)).values.repeat(top_mask.shape[1]).reshape(top_mask.shape)
    return weights


def quantile_long_short_btc_delta_neutral_weights(factor: pd.DataFrame, price: pd.DataFrame, q: float = 0.2, beta_window: int = 30):
    returns = price.pct_change()
    btc_ret = returns["BTCUSDT"]
    asset_rets = returns[factor.columns]
    cov = asset_rets.rolling(beta_window).cov(btc_ret)
    var = btc_ret.rolling(beta_window).var()
    betas = cov.div(var, axis=0).clip(-5, 5)
    ranks = factor.rank(axis=1, method="first", ascending=True)
    n = factor.count(axis=1)
    bottom_cutoff = n * q
    top_cutoff = n * (1 - q)
    bottom_mask = ranks.le(bottom_cutoff, axis=0)
    top_mask = ranks.gt(top_cutoff, axis=0)
    n_bottom = bottom_mask.sum(axis=1)
    n_top = top_mask.sum(axis=1)
    beta_long = (betas * top_mask).sum(axis=1) / n_top
    beta_short = (betas * bottom_mask).sum(axis=1) / n_bottom
    denom = (beta_long + beta_short).replace(0, np.nan)
    long_gross = beta_short / denom
    short_gross = beta_long / denom
    weights = pd.DataFrame(0.0, index=factor.index, columns=factor.columns)
    weights[top_mask] = ((long_gross / n_top).values.repeat(weights.shape[1]).reshape(weights.shape))
    weights[bottom_mask] = ((-short_gross / n_bottom).values.repeat(weights.shape[1]).reshape(weights.shape))
    return weights.fillna(0.0)


def _load_price_volume_liq():
    ohlcv = load_binance_ohlcv('1d').copy()
    ohlcv.set_index('open_time', inplace=True)
    ohlcv.index.name = 'Open time'
    ohlcv['symbol'] = ohlcv.asset.copy()
    ohlcv.index = pd.to_datetime(ohlcv.index, utc=True)
    ohlcv.reset_index(inplace=True)
    price = ohlcv.set_index(['Open time', 'symbol']).unstack('symbol').close
    price.columns.name = None
    volume = ohlcv.set_index(['Open time', 'symbol']).unstack('symbol').volume
    volume.columns.name = None
    liq = load_coinglass_orderbook().copy()
    liq['date'] = pd.to_datetime(liq['datetime'], utc=True)
    liq['symbol'] = liq['asset'].copy()
    bids_usd = liq.set_index(['date', 'symbol']).unstack('symbol').bids_usd.astype(float)
    asks_usd = liq.set_index(['date', 'symbol']).unstack('symbol').asks_usd.astype(float)
    liq = (bids_usd + asks_usd)
    liq.columns.name = None
    liq = liq.resample('D').ffill()
    common_columns = price.columns.intersection(liq.columns)
    common_index = price.index.intersection(liq.index)
    return price[common_columns].loc[common_index], volume[common_columns].loc[common_index], liq[common_columns].loc[common_index]


def get_curr_exp(pf):
    last = pf.assets().iloc[-1]
    last = last[last != 0].sort_values()
    return np.sign(last).to_dict()


def build(context: StrategyContext) -> StrategyResult:
    pf = get_pf()
    return StrategyResult(
        strategy_id=STRATEGY_ID,
        portfolio=pf,
        current_exposure=get_curr_exp(pf),
        rebalancing_style=REBALANCING_STYLE,
        signal_timestamp=context.as_of.normalize().isoformat().replace('+00:00', 'Z'),
        run_frequency=RUN_FREQUENCY,
    )


def get_pf():
    price, volume, liq = _load_price_volume_liq()
    factor = load_coinglass_orderbook().copy()
    factor.dropna(subset=['datetime'], inplace=True)
    factor['date'] = pd.to_datetime(factor['datetime'], utc=True)
    bids_usd = factor.set_index(['date', 'asset']).unstack('asset').bids_usd.astype(float)
    asks_usd = factor.set_index(['date', 'asset']).unstack('asset').asks_usd.astype(float)
    factor = (bids_usd + asks_usd)
    factor.columns.name = None
    factor = factor.resample('D').ffill()
    common_columns = factor.columns.intersection(price.columns)
    common_index = factor.index.intersection(price.index)
    factor = factor[common_columns].loc[common_index]
    liquidity = pd.concat({'top_of_book_liq': factor.rank(axis=1, method="average", pct=True)}, axis=1).groupby(level=1, axis=1).median()
    top_n_mask = liq.rolling(7).median().shift().rank(axis=1, ascending=False, method="dense") <= 50
    weights = quantile_long_short_btc_delta_neutral_weights(liquidity.where(top_n_mask), price, beta_window=30)
    return vbt.Portfolio.from_orders(close=price[weights.columns].loc[weights.index], size=weights, size_type='targetpercent', init_cash=100, cash_sharing=True, group_by=True, call_seq="auto", fees=0.0005)
