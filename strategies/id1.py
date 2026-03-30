from __future__ import annotations

import numpy as np
import pandas as pd
import vectorbt as vbt

from deployments.data_loader import load_binance_ohlcv
from deployments.strategy_types import StrategyContext, StrategyResult
from deployments.utils.signals import Signal

STRATEGY_ID = "id1"
REBALANCING_STYLE = "on_sign_change"
RUN_FREQUENCY = "1d"


def explode_individual(individual: str) -> str:
    entry_part, exit_part = individual.split('$')
    entry_part = entry_part.strip()
    exit_part = exit_part.strip()
    for part in [entry_part, exit_part]:
        rules = part.split('&')
        for i, rule in enumerate(rules):
            rules[i] = rule.strip().replace('(', '(Signal(close).', 1)
        if part == entry_part:
            entry_part = ' & '.join(rules)
        else:
            exit_part = ' & '.join(rules)
    return f'{entry_part} $ {exit_part}'


def get_individual_performance(close, direction, individual) -> pd.Series:
    i = explode_individual(individual)
    entries = eval(i.split('$')[0])
    exits = eval(i.split('$')[1])
    _price = close.copy()
    entries.index.name = 'date'
    exits.index.name = 'date'
    _price.index.name = 'date'
    if direction == 'L':
        return vbt.Portfolio.from_signals(_price, entries=entries, exits=exits, fees=0.001, size=10)
    if direction == 'S':
        return vbt.Portfolio.from_signals(_price, short_entries=entries, short_exits=exits, fees=0.001, size=10)
    return vbt.Portfolio.from_signals(_price, entries=entries, short_entries=exits, fees=0.001, size=10)


def get_pf():
    close = load_binance_ohlcv('1d')
    close = close[close.asset == 'BTCUSDT'].set_index('open_time').close
    close = close.to_frame(name='BTCUSDT').dropna()
    close.index.name = 'time'
    close.index = pd.to_datetime(close.index, utc=True)
    inds = [
        '(TMA(20) < close) $ (WINS_LAST(20) > 0)',
        '(SMOOTHED_MA(20) < close) $ (BARPATH(4) == True)'
    ]
    exposure_df = []
    for ind in inds:
        _pf = get_individual_performance(close, 'LS', ind)
        single_exposure = _pf.assets()
        single_exposure.columns = [ind]
        exposure_df.append(single_exposure)
    exposure = pd.concat(exposure_df, axis=1)
    exposure_sign = np.sign(exposure).sum(axis=1)
    long = exposure_sign > len(inds) / 2
    short = exposure_sign < len(inds) / 2
    return vbt.Portfolio.from_signals(close['BTCUSDT'], entries=long, short_entries=short, fees=0.0005, freq='D')


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
