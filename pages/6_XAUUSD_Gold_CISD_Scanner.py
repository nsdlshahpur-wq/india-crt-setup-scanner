from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from gold_cisd_scanner import CISDConfig, backtest_cisd, find_day_setup, load_gold_ohlc_csv

st.set_page_config(page_title="XAUUSD Gold CISD Scanner", page_icon="🥇", layout="wide")
st.title("🥇 XAUUSD Gold — CISD + FVG Scanner")
st.caption("Dono uploaded videos par aadharit: Liquidity Sweep → CISD → FVG → Retest → Entry")

st.info(
    "Video 1 se rule sequence liya gaya hai. Video 2 mein XAUUSD chart par bullish CISD, "
    "FVG zone aur Long Position risk box dikhte hain. Isliye yeh Gold-focused implementation "
    "hai; pehle NIFTY CISD page ko change nahi karta."
)
st.warning(
    "Video mein exact data feed, session boundary, candle timeframe aur har parameter ka "
    "written specification nahi diya gaya. Is page mein aapke uploaded OHLC CSV par "
    "rule-based scan hoga. Default RR 1:3 aapki pehle di hui preference hai, video se "
    "independently verified value nahi."
)

with st.sidebar:
    st.header("Gold Scanner Settings")
    rr = st.number_input("Risk : Reward", min_value=1.0, max_value=6.0, value=3.0, step=0.5)
    buffer = st.number_input("SL buffer (Gold price units)", min_value=0.0, max_value=100.0, value=0.5, step=0.1)
    charges = st.number_input("Estimated charges (bps per side)", min_value=0.0, max_value=100.0, value=0.0, step=1.0)
    slippage = st.number_input("Slippage (price units per side)", min_value=0.0, max_value=20.0, value=0.1, step=0.1)

uploaded = st.file_uploader("XAUUSD OHLC CSV upload karein (TradingView export supported)", type=["csv"])
st.caption("CSV mein Date/Time/Timestamp aur Open, High, Low, Close columns hone chahiye. Selected chart timeframe ki candles upload karein (video 2 chart par timeframe text poori tarah readable nahi hai).")

if uploaded is not None:
    try:
        data, report = load_gold_ohlc_csv(uploaded)
        st.success(f"Data loaded: {report['rows']:,} candles · {report['start']} → {report['end']}")
        st.caption("Session grouping uploaded timestamps ke calendar date par hoti hai. Agar CSV timezone/session boundary alag hai, results usse prabhavit ho sakte hain.")
        cfg = CISDConfig(rr=float(rr), stop_buffer_points=float(buffer), one_trade_per_day=True)
        if st.button("Run XAUUSD CISD scan + historical backtest", type="primary):
            with st.spinner("CISD / FVG sequence scan aur historical simulation chal raha hai..."):
                trades, metrics = backtest_cisd(
                    data, cfg, charges_bps_per_side=float(charges),
                    slippage_points_per_side=float(slippage)
                )
            st.session_state["gold_cisd_data"] = data
            st.session_state["gold_cisd_trades"] = trades
            st.session_state["gold_cisd_metrics"] = metrics
            st.session_state["gold_cisd_report"] = report
            st.rerun()
    except Exception as exc:
        st.error(str(exc))

if "gold_cisd_data" in st.session_state:
    data = st.session_state["gold_cisd_data"]
    trades = st.session_state["gold_cisd_trades"]
    metrics = st.session_state["gold_cisd_metrics"]
    report = st.session_state["gold_cisd_report"]
    st.divider()
    st.subheader("XAUUSD historical results")
    st.caption(f"Candles: {len(data):,} · {data.index.min()} to {data.index.max()} · RR 1:{rr:g}")
    cols = st.columns(5)
    cols[0].metric("Trades", metrics.get("total_trades", 0))
    cols[1].metric("Win rate", f"{metrics.get('win_rate', 0):.2f}%")
    pf = metrics.get("profit_factor", 0)
    cols[2].metric("Profit factor", "∞" if pf == float("inf") else f"{pf:.2f}")
    cols[3].metric("Net price units", f"{metrics.get('net_points', 0):+.2f}")
    cols[4].metric("Max drawdown", f"{metrics.get('max_drawdown_points', 0):.2f}")
    st.write(
        f"**Wins:** {metrics.get('wins', 0)} · **Losses:** {metrics.get('losses', 0)} · "
        f"**EOD exits:** {metrics.get('eod_exits', 0)}"
    )
    st.caption("Win rate = TP/(TP+SL); EOD exits separately shown. P&L Gold price units mein hai, USD/INR ya lot-based profit nahi. Actual contract size, spread, swap, commission aur broker execution alag ho sakte hain.")
    if len(trades) < 30:
        st.warning("30 se kam trades hain; win rate ko reliable estimate na maanein.")
    if not trades.empty:
        st.dataframe(trades, use_container_width=True, hide_index=True)
        st.download_button("Download XAUUSD trade log CSV", trades.to_csv(index=False).encode("utf-8-sig"), "xauusd_cisd_trades.csv", "text/csv")
        curve = trades["net_points"].cumsum()
        fig = go.Figure(go.Scatter(x=trades["exit_time"], y=curve, mode="lines", name="Cumulative net price units"))
        fig.update_layout(title="XAUUSD CISD cumulative result", xaxis_title="Exit time", yaxis_title="Cumulative price units", height=360)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Is uploaded data aur selected rules par koi qualifying setup nahi mila.")
    sessions = list(data.groupby(data.index.date, sort=True))
    st.subheader("Latest completed session signal")
    if len(sessions) >= 2:
        _, day = sessions[-1]
        _, prev = sessions[-2]
        latest = find_day_setup(day, float(prev["High"].max()), float(prev["Low"].min()), cfg)
        if latest:
            st.success(f"{latest['side']} · Entry {latest['entry']:.2f} · SL {latest['stop']:.2f} · Target {latest['target']:.2f}")
            st.write(f"CISD line: {latest['cisd_line']:.2f} · FVG: {latest['fvg_low']:.2f}–{latest['fvg_high']:.2f} · Sweep extreme: {latest['sweep_extreme']:.2f}")
            st.caption(f"Signal: {latest['signal_time']} · Planned entry: {latest['entry_time']}")
        else:
            st.info("Latest session mein qualifying setup nahi mila.")
    with st.expander("Data and assumptions"):
        st.write(report)
        st.write("Rules: previous session high/low sweep and reclaim; CISD body close across line; 3-candle FVG; FVG retest/rejection; entry next candle open; SL beyond sweep; opposite liquidity must allow requested RR.")
else:
    st.info("CSV upload karein aur scan button dabayein. Is app mein Gold ka external historical feed assume nahi kiya gaya hai.")
