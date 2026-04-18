from __future__ import annotations

import numpy as np
import pandas as pd
import vectorbt as vbt

from deployments.data_loader import load_binance_ohlcv
from deployments.strategy_types import StrategyContext, StrategyResult

STRATEGY_ID = "id9"
REBALANCING_STYLE = "on_sign_change"
RUN_FREQUENCY = "1d"

def get_pf():
    close = load_binance_ohlcv('1d')
    close = close[close.asset == 'BTCUSDT'].set_index('open_time').close
    close = close.to_frame(name='BTCUSDT').dropna()
    close.index.name = 'time'
    close.index = pd.to_datetime(close.index, utc=True)

    donchian_upper = close.rolling(7).max().shift()
    donchian_mid = close.rolling(7).mean().shift()
    sma = close.rolling(50).mean().shift()

    entries = (close > donchian_upper) & (close > sma)
    exits = (close < donchian_mid) | (close < sma)

    return vbt.Portfolio.from_signals(close['BTCUSDT'], entries=entries, exits=exits, fees=0.0005, freq='D')


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
