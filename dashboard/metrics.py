from __future__ import annotations

import empyrical as ep
import numpy as np
import pandas as pd


def _annualization_factor(returns: pd.Series) -> float:
    if len(returns) < 2:
        return 365.0
    idx = returns.index
    if isinstance(idx, pd.DatetimeIndex):
        deltas = idx.to_series().diff().dt.total_seconds().dropna() / 3600.0
        median_h = float(deltas.median()) if len(deltas) else 24.0
        if median_h > 0:
            return 365.0 * 24.0 / median_h
    return 365.0


def performance_stats(equity: pd.DataFrame, allocation: float, num_trades: int) -> pd.DataFrame:
    if equity.empty:
        return pd.DataFrame(
            {
                "metric": ["Sharpe", "Max Drawdown", "CAGR", "Sortino", "Number of trades"],
                "value": ["—", "—", "—", "—", 0],
            }
        )

    series = equity.set_index("timestamp")["equity"].astype(float)
    returns = series.pct_change().dropna()
    ann = _annualization_factor(returns)

    sharpe = ep.sharpe_ratio(returns, annualization=ann)
    sortino = ep.sortino_ratio(returns, annualization=ann)
    max_dd = ep.max_drawdown(returns)

    start = series.iloc[0]
    end = series.iloc[-1]
    days = max((series.index[-1] - series.index[0]).total_seconds() / 86400.0, 1.0)
    cagr = (end / start) ** (365.0 / days) - 1.0 if start > 0 else np.nan

    def fmt_pct(x: float) -> str:
        if x is None or (isinstance(x, float) and np.isnan(x)):
            return "—"
        return f"{x * 100:.2f}%"

    def fmt_num(x: float) -> str:
        if x is None or (isinstance(x, float) and np.isnan(x)):
            return "—"
        return f"{x:.2f}"

    return pd.DataFrame(
        {
            "metric": ["Sharpe", "Max Drawdown", "CAGR", "Sortino", "Number of trades"],
            "value": [
                fmt_num(float(sharpe)) if sharpe == sharpe else "—",
                fmt_pct(float(max_dd)),
                fmt_pct(float(cagr)) if cagr == cagr else "—",
                fmt_num(float(sortino)) if sortino == sortino else "—",
                int(num_trades),
            ],
        }
    )
