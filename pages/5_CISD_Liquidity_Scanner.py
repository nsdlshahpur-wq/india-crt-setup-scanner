from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from cisd_scanner import CISDConfig, backtest_crt_cisd, resample_1m_to_5m
from nifty50_history import load_full_nifty50_1m

st.set_page_config(page_title="NIFTY 50 CRT + CISD Scanner", page_icon="🎯", layout="wide")
st.title("🎯 NIFTY 50 — CRT + CISD Liquidity Scanner")
st.caption("REPLACEMENT STRATEGY: Weekly / Daily / 4H / 1H CRT → 15M CISD → 5M FVG Retest → Entry")

st.warning(
    "पुराना केवल Previous-Day Liquidity Sweep → CISD → FVG मॉडल हटा दिया गया है। "
    "अब CRT की M1 range को M2 candle द्वारा केवल एक तरफ sweep करके M1 range के अंदर close करना होगा। "
    "उसके बाद 15M पर body-close CISD और 5M पर नया FVG बनकर retest होना जरूरी है। "
    "Scanner केवल research/backtest करता है; broker order place नहीं करता।"
)

with st.sidebar:
    st.header("CRT + CISD Strategy Settings")
    rr = st.selectbox("Final Risk : Reward target", options=[2.0, 3.0], index=1,
                      format_func=lambda x: f"1:{x:g}R")
    stop_buffer = st.number_input("SL buffer (NIFTY points)", min_value=0.05,
                                  max_value=50.0, value=1.0, step=0.05)
    slippage = st.number_input("Slippage (points per side)", min_value=0.0,
                               max_value=20.0, value=0.5, step=0.1)
    force_refresh = st.checkbox("Force refresh historical data", value=False)

st.markdown(
    "**Entry sequence:** (1) CRT M1/M2 sweep-and-reclaim on 1H, 4H, Daily or Weekly; "
    "(2) wait until M2 closes; (3) 15M candle body closes across CISD line; "
    "(4) 5M three-candle FVG forms after CISD; (5) later 5M candle retests FVG and rejects; "
    "(6) entry at next 5M candle open. SL is beyond M2 sweep extreme plus buffer. "
    "Both 2R and 3R levels are shown; selected R controls the backtest exit."
)

if st.button("Load historical data → build 5M / 15M bars → CRT + CISD backtest",
             type="primary"):
    try:
        with st.spinner("Loading historical NIFTY data and building timeframe candles..."):
            one_min, source_report = load_full_nifty50_1m(force_refresh=force_refresh)
            five_min = resample_1m_to_5m(one_min)
        if five_min.empty:
            st.error("5-minute candles could not be built from the source data.")
            st.stop()
        cfg = CISDConfig(rr=float(rr), stop_buffer_points=float(stop_buffer),
                         one_trade_per_day=True)
        with st.spinner("Running no-look-ahead CRT → 15M CISD → 5M FVG backtest..."):
            trades, metrics = backtest_crt_cisd(
                five_min, cfg, slippage_points_per_side=float(slippage)
            )
        st.session_state["cisd_5m_data"] = five_min
        st.session_state["cisd_5m_trades"] = trades
        st.session_state["cisd_5m_metrics"] = metrics
        st.session_state["cisd_5m_source"] = source_report
        st.session_state["cisd_5m_config"] = {
            "rr": rr, "stop_buffer": stop_buffer, "slippage": slippage
        }
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
    st.subheader("Historical CRT + CISD backtest")
    st.caption(
        f"Bars: {len(data):,} · Data: {data.index.min()} to {data.index.max()} · "
        f"CRT: 1H / 4H / Daily / Weekly · CISD: 15M · Entry: 5M · "
        f"Target: 1:{cfg_values.get('rr', 3)}R"
    )
    cols = st.columns(5)
    cols[0].metric("Total setups", f"{metrics.get('total_trades', 0):,}")
    cols[1].metric("Win rate", f"{metrics.get('win_rate', 0):.2f}%")
    pf = metrics.get("profit_factor", 0)
    cols[2].metric("Profit factor", "∞" if pf == float("inf") else f"{pf:.2f}")
    cols[3].metric("Net points", f"{metrics.get('net_points', 0):+,.1f}")
    cols[4].metric("Max drawdown", f"{metrics.get('max_drawdown_points', 0):,.1f} pts")
    st.write(
        f"**Wins:** {metrics.get('wins', 0)} · **Losses:** {metrics.get('losses', 0)} · "
        f"**EOD exits:** {metrics.get('eod_exits', 0)} · "
        f"**Average win:** {metrics.get('avg_win_points', 0):.1f} pts · "
        f"**Average loss:** {metrics.get('avg_loss_points', 0):.1f} pts"
    )
    if metrics.get("total_trades", 0) < 30:
        st.warning("Sample 30 trades se kam hai. Win rate ko reliable estimate na maanein.")
    st.caption(
        "Results are NIFTY index points, not option/futures rupee P&L. "
        "Historical data availability, slippage and index execution can differ from live trading."
    )
    if not trades.empty:
        st.dataframe(trades, use_container_width=True, hide_index=True)
        st.download_button(
            "Download CRT + CISD trade log CSV",
            trades.to_csv(index=False).encode("utf-8-sig"),
            "nifty50_crt_cisd_trades.csv", "text/csv"
        )
        curve = trades.sort_values("exit_time").copy()
        curve["cumulative_net_points"] = curve["net_points"].cumsum()
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=curve["exit_time"], y=curve["cumulative_net_points"],
                                 mode="lines", name="Cumulative net points"))
        fig.update_layout(title="CRT + CISD cumulative net points",
                          xaxis_title="Exit time", yaxis_title="Cumulative NIFTY points",
                          height=380)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("इस CRT + CISD rule-set पर कोई qualifying trade नहीं मिला।")
    st.divider()
    st.subheader("Latest completed setup")
    if not trades.empty:
        latest = trades.sort_values("entry_time").iloc[-1]
        st.success(
            f"{latest['CRT timeframe']} CRT · {latest['side']} · "
            f"Entry {latest['entry']:.2f} · SL {latest['stop_loss']:.2f} · "
            f"2R {latest['target_1_2R']:.2f} · 3R {latest['target_2_3R']:.2f}"
        )
        st.write(
            f"15M CISD line: {latest['cisd_line']:.2f} · "
            f"5M FVG: {latest['fvg_low']:.2f}–{latest['fvg_high']:.2f} · "
            f"Sweep extreme: {latest['sweep_extreme']:.2f}"
        )
        st.caption(f"Signal: {latest['signal_time']} · Entry: {latest['entry_time']}")
    else:
        st.info("अभी इस इतिहास में कोई completed qualifying setup उपलब्ध नहीं है।")
    with st.expander("Data source and coverage report"):
        st.write(source)
else:
    st.info("ऊपर बटन दबाकर historical 1-minute data से 5-minute candles बनाएँ और नया CRT + CISD backtest चलाएँ.")
