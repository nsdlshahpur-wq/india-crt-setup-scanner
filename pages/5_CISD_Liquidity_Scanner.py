from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from cisd_scanner import CISDConfig, backtest_cisd, find_day_setup, resample_1m_to_5m
from nifty50_history import load_full_nifty50_1m

st.set_page_config(page_title="NIFTY 50 CISD Scanner", page_icon="🎯", layout="wide")
st.title("🎯 NIFTY 50 — CISD Liquidity Sweep Scanner")
st.caption("Separate 5-minute entry model: Liquidity Sweep → CISD body close → FVG formation → FVG retest.")
st.warning(
    "Research-only scanner. It does not place orders. The uploaded lesson illustrates prior liquidity as target "
    "and shows an example RR of 1:2. This page applies your requested 1:3: the prior opposite-side liquidity "
    "must be at least 3R away, otherwise the setup is filtered out."
)

with st.sidebar:
    st.header("CISD Scanner Settings")
    rr = st.number_input("Risk : Reward target", min_value=1.0, max_value=6.0, value=3.0, step=0.5)
    stop_buffer = st.number_input("SL buffer (NIFTY points)", min_value=0.05, max_value=50.0, value=1.0, step=0.05)
    charges = st.number_input("Estimated charges (bps per side)", min_value=0.0, max_value=50.0, value=12.0, step=1.0)
    slippage = st.number_input("Slippage (points per side)", min_value=0.0, max_value=20.0, value=0.5, step=0.1)
    force_refresh = st.checkbox("Force refresh historical data", value=False)

st.markdown(
    "**Mechanical rules used:** Previous trading day High/Low is the liquidity reference. "
    "A sweep must pierce that level and close back inside. CISD is the open of the first candle "
    "in the immediately preceding opposing-colour candle run. The confirmation candle body must close "
    "across the CISD line; wick-only crosses are rejected. A 3-candle FVG must then form and be retested."
)

if st.button("Load 1-minute history → build 5-minute bars → scan + backtest", type="primary"):
    try:
        with st.spinner("Downloading public NIFTY 50 history and rebuilding 5-minute candles..."):
            one_min, source_report = load_full_nifty50_1m(force_refresh=force_refresh)
            five_min = resample_1m_to_5m(one_min)
        if five_min.empty:
            st.error("5-minute candles could not be built from the source data.")
            st.stop()
        cfg = CISDConfig(rr=float(rr), stop_buffer_points=float(stop_buffer), one_trade_per_day=True)
        with st.spinner("Running no-look-ahead CISD historical backtest..."):
            trades, metrics = backtest_cisd(
                five_min, cfg, charges_bps_per_side=float(charges),
                slippage_points_per_side=float(slippage)
            )
        st.session_state["cisd_5m_data"] = five_min
        st.session_state["cisd_5m_trades"] = trades
        st.session_state["cisd_5m_metrics"] = metrics
        st.session_state["cisd_5m_source"] = source_report
        st.session_state["cisd_5m_config"] = {"rr": rr, "stop_buffer": stop_buffer,
                                               "charges": charges, "slippage": slippage}
        st.rerun()
    except Exception as exc:
        st.exception(exc)

if "cisd_5m_data" in st.session_state:
    data = st.session_state["cisd_5m_data"]
    trades = st.session_state["cisd_5m_trades"]
    metrics = st.session_state["cisd_5m_metrics"]
    source = st.session_state.get("cisd_5m_source", {})
    cfg_values = st.session_state.get("cisd_5m_config", {})
    st.divider()
    st.subheader("Historical 5-minute backtest")
    st.caption(
        f"Bars: {len(data):,} · Data: {data.index.min()} to {data.index.max()} · "
        f"Target: 1:{cfg_values.get('rr', 3)} · One trade per session"
    )
    c = st.columns(5)
    c[0].metric("Total setups", f"{metrics.get('total_trades', 0):,}")
    c[1].metric("Win rate", f"{metrics.get('win_rate', 0):.2f}%")
    pf = metrics.get("profit_factor", 0)
    c[2].metric("Profit factor", "∞" if pf == float("inf") else f"{pf:.2f}")
    c[3].metric("Net points", f"{metrics.get('net_points', 0):+,.1f}")
    c[4].metric("Max drawdown", f"{metrics.get('max_drawdown_points', 0):,.1f} pts")
    st.write(
        f"**Wins:** {metrics.get('wins', 0)} · **Losses:** {metrics.get('losses', 0)} · "
        f"**EOD exits:** {metrics.get('eod_exits', 0)} · "
        f"**Average win:** {metrics.get('avg_win_points', 0):.1f} pts · "
        f"**Average loss:** {metrics.get('avg_loss_points', 0):.1f} pts"
    )
    if metrics.get("total_trades", 0) < 30:
        st.warning("Sample 30 trades se kam hai. Win rate ko reliable estimate na maanein.")
    st.caption(
        "Win rate = TP / (TP + SL); EOD exits separately shown. Results are NIFTY index points, "
        "not option/futures rupee P&L. Charges are approximate; index spot has no tradable lot sizing."
    )
    if not trades.empty:
        st.dataframe(trades, use_container_width=True, hide_index=True)
        st.download_button(
            "Download CISD trade log CSV", trades.to_csv(index=False).encode("utf-8-sig"),
            "nifty50_cisd_5m_trades.csv", "text/csv"
        )
        equity = trades["net_points"].cumsum()
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=trades["exit_time"], y=equity, mode="lines", name="Cumulative net points"))
        fig.update_layout(title="CISD cumulative net points", xaxis_title="Exit time",
                          yaxis_title="Cumulative NIFTY points", height=380)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("इन नियमों और इस RR filter पर कोई qualifying trade नहीं मिला।")
    st.divider()
    st.subheader("Latest completed session setup")
    sessions = list(data.groupby(data.index.date, sort=True))
    if len(sessions) >= 2:
        day_key, latest_day = sessions[-1]
        _, previous_day = sessions[-2]
        latest_cfg = CISDConfig(rr=float(cfg_values.get("rr", 3)),
                                stop_buffer_points=float(cfg_values.get("stop_buffer", 1)))
        latest = find_day_setup(latest_day, float(previous_day["High"].max()),
                                float(previous_day["Low"].min()), latest_cfg)
        if latest:
            st.success(f"{latest['side']} setup · Entry {latest['entry']:.2f} · SL {latest['stop']:.2f} · Target {latest['target']:.2f}")
            st.write(f"CISD line: {latest['cisd_line']:.2f} · FVG: {latest['fvg_low']:.2f}–{latest['fvg_high']:.2f} · Sweep extreme: {latest['sweep_extreme']:.2f}")
            st.caption(f"Signal close: {latest['signal_time']} · Planned next-bar entry: {latest['entry_time']}")
        else:
            st.info("Latest completed session mein is rule-set par koi fresh qualifying entry nahi mili.")
    with st.expander("Data source and coverage report"):
        st.write(source)
else:
    st.info("ऊपर बटन दबाकर public 1-minute history से 5-minute candles बनाएँ और CISD backtest चलाएँ.")
