from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from deployments.dashboard.config import DEFAULT_ALLOCATION, DEFAULT_PARQUET_ROOT
from deployments.dashboard.data_loader import (
    build_trades_from_fills,
    current_positions,
    list_allocations,
    list_strategy_ids,
    load_equity,
    load_fills,
)
from deployments.dashboard.metrics import performance_stats
from deployments.dashboard.signal_simulation import (
    current_signal_positions,
    replay_signal_simulation,
)

SIMULATION_MODES = {
    "Trade simulation": "trade",
    "Signal simulation": "signal",
}


@st.cache_data(ttl=60)
def get_strategy_bundle(
    strategy_id: str,
    allocation: float,
    parquet_root: str,
    simulation_mode: str,
):
    root = Path(parquet_root)
    if simulation_mode == "signal":
        equity, fills, positions_history = replay_signal_simulation(strategy_id, allocation, root)
        positions = current_signal_positions(positions_history)
    else:
        equity = load_equity(strategy_id, allocation, root)
        fills = load_fills(strategy_id, allocation, root)
        positions = current_positions(strategy_id, allocation, root)

    trades = build_trades_from_fills(fills)
    return equity, fills, positions, trades


st.set_page_config(page_title="Shadow Trading Dashboard", layout="wide")
st.title("Shadow Trading Dashboard")

if not DEFAULT_PARQUET_ROOT.exists():
    st.error(f"Parquet root not found: {DEFAULT_PARQUET_ROOT}")
    st.stop()

strategy_ids = list_strategy_ids()
if not strategy_ids:
    st.warning("No strategy data found.")
    st.stop()

col_strategy, col_alloc, col_mode = st.columns([1, 1, 1])
with col_strategy:
    strategy_id = st.selectbox("Strategy", strategy_ids, index=strategy_ids.index("id2") if "id2" in strategy_ids else 0)
with col_alloc:
    allocations = list_allocations(strategy_id)
    if not allocations:
        st.error(f"No allocations available for {strategy_id}.")
        st.stop()
    default_alloc = DEFAULT_ALLOCATION if DEFAULT_ALLOCATION in allocations else allocations[0]
    allocation = st.selectbox(
        "Allocation",
        allocations,
        index=allocations.index(default_alloc),
        format_func=lambda x: f"${x:,.0f}",
    )
with col_mode:
    simulation_label = st.selectbox("Simulation mode", list(SIMULATION_MODES.keys()))
    simulation_mode = SIMULATION_MODES[simulation_label]

equity, fills, positions, trades = get_strategy_bundle(
    strategy_id,
    allocation,
    str(DEFAULT_PARQUET_ROOT),
    simulation_mode,
)

if simulation_mode == "signal":
    st.caption(
        "Signal simulation assumes target weights are fully achieved at every rebalance. "
        "The normalized equity path is identical across allocations."
    )
else:
    st.caption("Trade simulation uses recorded fills, including partial execution.")

st.subheader("Equity Curve")
if equity.empty:
    st.info("No equity data for this strategy/allocation.")
else:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=equity["timestamp"],
            y=equity["equity"],
            mode="lines",
            name=f"${allocation:,.0f}",
            line={"color": "#2563eb", "width": 2},
        )
    )
    fig.add_hline(y=allocation, line_dash="dash", line_color="gray", opacity=0.6)
    fig.update_layout(
        height=420,
        margin=dict(l=20, r=20, t=30, b=20),
        xaxis_title="Time",
        yaxis_title="Equity ($)",
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)

st.subheader("Performance Stats")
stats_df = performance_stats(equity, allocation, len(trades))
st.table(stats_df.set_index("metric"))

st.subheader("Current Positions")
if positions.empty:
    st.info("Flat — no open positions.")
else:
    st.dataframe(positions, use_container_width=True, hide_index=True)

st.subheader("All Trades")
if trades.empty:
    st.info("No completed round-trip trades derived from fills.")
else:
    display_trades = trades.copy()
    for col in ("entry_time", "exit_time"):
        if col in display_trades.columns:
            display_trades[col] = display_trades[col].dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    st.dataframe(display_trades, use_container_width=True, hide_index=True)

st.subheader("All Fills")
if fills.empty:
    st.info("No fills recorded.")
else:
    display_fills = fills.copy()
    if "timestamp" in display_fills.columns:
        display_fills["timestamp"] = display_fills["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    if "signal_timestamp" in display_fills.columns:
        display_fills["signal_timestamp"] = pd.to_datetime(display_fills["signal_timestamp"], utc=True, errors="coerce").dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    st.dataframe(display_fills, use_container_width=True, hide_index=True)
