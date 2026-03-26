from __future__ import annotations

import numpy as np
import pandas as pd
import vectorbt as vbt

from deployments.data_loader import load_bgeometrics, load_binance_ohlcv
from deployments.types import StrategyContext, StrategyResult

STRATEGY_ID = "id7"
REBALANCING_STYLE = "on_sign_change"
RUN_FREQUENCY = "1h"


def get_pf():
    ohlcv = load_binance_ohlcv('1h')
    ohlcv = ohlcv[ohlcv.asset == 'BTCUSDT'].copy()
    ohlcv.set_index('open_time', inplace=True)
    ohlcv.index.name = 'date'
    ohlcv.index = pd.to_datetime(ohlcv.index, utc=True)

    bgeometrics_data = load_bgeometrics()
    metric = bgeometrics_data.mvrv.astype(float).copy()
    metric = metric.resample('1h').ffill().shift(9 if 'id7' != 'id7' else 8)
    common_idx = metric.index.intersection(ohlcv.index)
    metric = metric.loc[common_idx]
    btc_price = ohlcv.close.copy().loc[common_idx]
    window = 7 * 24
    ma = metric.rolling(window).mean().shift()
    std = metric.rolling(window).std().shift()
    z = (metric - ma) / std
    upper = ma + (1 * std)
    lower = ma - (1 * std)
    entries = metric > upper
    short_entries = metric < lower
    return vbt.Portfolio.from_signals(btc_price, entries=entries, short_entries=short_entries, fees=0.001, freq='D')


def get_curr_exp(pf):
    assets = pf.assets()
    signed = np.sign(assets)

    if hasattr(signed, "iloc"):
        last = signed.iloc[-1]
        if hasattr(last, "to_dict"):
            return last.to_dict()
        if hasattr(last, "item"):
            return {"BTCUSDT": float(last.item())}
        return {"BTCUSDT": float(last)}

    if hasattr(signed, "to_dict"):
        return signed.to_dict()

    if hasattr(signed, "item"):
        return {"BTCUSDT": float(signed.item())}

    return {"BTCUSDT": float(signed)}

def build(context: StrategyContext) -> StrategyResult:
    pf = get_pf()
    return StrategyResult(
        strategy_id=STRATEGY_ID,
        portfolio=pf,
        current_exposure=get_curr_exp(pf),
        rebalancing_style=REBALANCING_STYLE,
        signal_timestamp=context.as_of.isoformat().replace('+00:00', 'Z'),
        run_frequency=RUN_FREQUENCY,
    )
