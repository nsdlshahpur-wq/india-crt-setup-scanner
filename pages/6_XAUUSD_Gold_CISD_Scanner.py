from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from gold_cisd_scanner import (
    CISDConfig, backtest_cisd, find_day_setup,
    fetch_yahoo_gold_data, load_gold_ohlc_csv,
)

st.set_page_config(page_title="XAUUSD Gold CISD Scanner", page_icon="🥇", layout="wide")
st.title("🥇 XAUUSD Gold — CISD + FVG Scanner")
st.caption("Dono videos par aadharit: Liquidity Sweep → CISD → FVG → Retest → Entry")

st.info(
    "Yahoo Finance se XAUUSD spot price aur 5-minute candles fetch kiye jaate hain. "
    "Agar spot feed available na ho to GC=F Gold futures fallback dikhaya jayega."
)
st.warning(
    "Yahoo Finance ka intraday data delayed ya incomplete ho sakta hai; yeh broker ka executable live quote nahi hai. "
    "Video ke rule sequence ko mechanical CISD/FVG rules mein badla gaya hai. Default RR 1:3 aapki preference hai."
)

with st.sidebar:
    st.header("Gold Scanner Settings")
    rr = st.number_input("Risk : Reward", min_value=1.0, max_value=6.0, value=3.0, step=0.5)
    buffer = st.number_input("SL buffer (Gold price units)", min_value=0.0, max_value=100.0, value=0.5, step=0.1)
    charges = st.number_input("Estimated charges (bps per side)", min_value=0.0, max_value=100.0, value=0.0, step=1.0)
    slippage = st.number_input("Slippage (price units per side)", min_value=0.0, max_value=20.0, value=0.1, step=0.1)

if st.button("🔄 Refresh Yahoo Gold Price and 5-minute Data", type="primary") or "gold_yahoo_data" not in st.session_state:
    try:
        with st.spinner("Yahoo Finance se XAUUSD quote aur 5-minute candles la rahe hain..."):
            yahoo_data, yahoo_report = fetch_yahoo_gold_data()
        st.session_state["gold_yahoo_data"] = yahoo_data
        st.session_state["gold_yahoo_report"] = yahoo_report
        st.session_state.pop("gold_cisd_data", None)
        st.session_state.pop("gold_cisd_trades", None)
        st.session_state.pop("gold_cisd_metrics", None)
    except Exception as exc:
        st.error(f"Yahoo data fetch nahi hua: {exc}")

if "gold_yahoo_report" in st.session_state:
    quote = st.session_state["gold_yahoo_report"]
    st.subheader("Yahoo Finance Gold Quote")
    q1, q2, q3 = st.columns(3)
    q1.metric("Latest available Gold price", f"{quote['latest_price']:,.2f}")
    q2.metric("Yahoo ticker / source", quote["ticker"])
    q3.metric("Quote candle", quote["quote_interval"])
    st.caption(f"Yahoo timestamp: {quote['latest_timestamp']} · Source: {quote['source']}")
    st.caption(quote["note"])
    yahoo_data = st.session_state["gold_yahoo_data"]
    st.success(
        f"Yahoo 5-minute history loaded: {quote['history_rows']:,} candles · "
        f"{quote['history_start']} → {quote['history_end']}"
    )
    cfg = CISDConfig(rr=float(rr), stop_buffer_points=float(buffer), one_trade_per_day=True)
    if st.button("Run Yahoo XAUUSD CISD scan + backtest"):
        with st.spinner("Yahoo 5-minute candles par CISD / FVG backtest chal raha hai..."):
            trades, metrics = backtest_cisd(
                yahoo_data, cfg, charges_bps_per_side=float(charges),
                slippage_points_per_side=float(slippage)
            )
        st.session_state["gold_cisd_data"] = yahoo_data
        st.session_state["gold_cisd_trades"] = trades
        st.session_state["gold_cisd_metrics"] = metrics
        st.session_state["gold_cisd_report"] = quote
        st.rerun()

st.divider()
st.subheader("Optional: apna TradingView CSV")
uploaded = st.file_uploader("XAUUSD OHLC CSV upload karein (optional)", type=["csv"])
if uploaded is not None:
    try:
        csv_data, csv_report = load_gold_ohlc_csv(uploaded)
        st.success(f"CSV loaded: {csv_report['rows']:,} candles · {csv_report['start']} → {csv_report['end']}")
        cfg_csv = CISDConfig(rr=float(rr), stop_buffer_points=float(buffer), one_trade_per_day=True)
        if st.button("Run uploaded CSV backtest"):
            trades, metrics = backtest_cisd(
                csv_data, cfg_csv, charges_bps_per_side=float(charges),
                slippage_points_per_side=float(slippage)
            )
            st.session_state["gold_cisd_data"] = csv_data
            st.session_state["gold_cisd_trades"] = trades
            st.session_state["gold_cisd_metrics"] = metrics
            st.session_state["gold_cisd_report"] = csv_report
            st.rerun()
    except Exception as exc:
        st.error(str(exc))

if "gold_cisd_data" in st.session_state:
    data = st.session_state["gold_cisd_data"]
    trades = st.session_state["gold_cisd_trades"]
    metrics = st.session_state["gold_cisd_metrics"]
    report = st.session_state["gold_cisd_report"]
    st.divider()
    st.subheader("Historical CISD backtest")
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
    st.caption("Win rate = TP/(TP+SL); EOD exits separately shown. P&L Gold price units mein hai, lot-based USD/INR profit nahi.")
    if len(trades) < 30:
        st.warning("30 se kam trades hain; win rate ko reliable estimate na maanein.")
    if not trades.empty:
        st.dataframe(trades, use_container_width=True, hide_index=True)
        st.download_button(
            "Download XAUUSD trade log CSV", trades.to_csv(index=False).encode("utf-8-sig"),
            "xauusd_cisd_trades.csv", "text/csv"
        )
        equity = trades["net_points"].cumsum()
        fig = go.Figure(go.Scatter(x=trades["exit_time"], y=equity, mode="lines", name="Cumulative net price units"))
        fig.update_layout(title="XAUUSD CISD cumulative result", xaxis_title="Exit time", yaxis_title="Cumulative price units", height=360)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Is data aur selected rules par koi qualifying setup nahi mila.")
    sessions = list(data.groupby(data.index.date, sort=True))
    st.subheader("Latest completed session signal")
    if len(sessions) >= 2:
        _, day = sessions[-1]
        _, previous = sessions[-2]
        latest = find_day_setup(day, float(previous["High"].max()), float(previous["Low"].min()), cfg)
        if latest:
            st.success(f"{latest['side']} · Entry {latest['entry']:.2f} · SL {latest['stop']:.2f} · Target {latest['target']:.2f}")
            st.write(f"CISD line: {latest['cisd_line']:.2f} · FVG: {latest['fvg_low']:.2f}–{latest['fvg_high']:.2f} · Sweep extreme: {latest['sweep_extreme']:.2f}")
            st.caption(f"Signal: {latest['signal_time']} · Planned entry: {latest['entry_time']}")
        else:
            st.info("Latest session mein qualifying setup nahi mila.")
else:
    st.info("Yahoo refresh button dabakar Gold ka latest available price aur 5-minute history load karein.")
