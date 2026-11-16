from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from gold_cisd_scanner import (
    CISDConfig, INSTRUMENTS, backtest_cisd, find_day_setup,
    fetch_market_data, load_gold_ohlc_csv,
)

st.set_page_config(page_title="Multi-Asset Futures CISD Scanner", page_icon="📈", layout="wide")
st.title("📈 Multi-Asset Futures CISD + FVG Scanner")
st.caption("Futures Market Data Only · Liquidity Sweep → CISD → FVG → Retest → Entry")

st.info(
    "Metals / FX / US index: Yahoo Finance continuous futures symbols. "
    "Crypto: Binance USD-M perpetual futures via CCXT. Options aur spot-market fallback disabled."
)
st.warning(
    "Yahoo futures quotes delayed ho sakte hain. Crypto contracts perpetual futures hain, dated delivery futures nahi. "
    "US30 ke liye YM=F E-mini Dow futures proxy hai, broker CFD nahi. Scanner sirf data padhta hai, orders place nahi karta."
)

with st.sidebar:
    st.header("Futures Market Selection")
    category = st.selectbox("Market category", list(INSTRUMENTS.keys()))
    instrument = st.selectbox("Futures contract / Pair", list(INSTRUMENTS[category].keys()))
    st.divider()
    st.header("Strategy Settings")
    rr = st.number_input("Risk : Reward", min_value=1.0, max_value=6.0, value=3.0, step=0.5)
    buffer = st.number_input("SL buffer (price units)", min_value=0.0, max_value=100.0, value=0.5, step=0.1)
    charges = st.number_input("Estimated charges (bps per side)", min_value=0.0, max_value=100.0, value=0.0, step=1.0)
    slippage = st.number_input("Slippage (price units per side)", min_value=0.0, max_value=20.0, value=0.1, step=0.1)

spec = INSTRUMENTS[category][instrument]
st.subheader(f"{instrument} · {category}")
st.caption(f"Data provider: {spec['provider']} · Price unit: {spec['unit']}")

refresh = st.button("🔄 Fetch latest futures quote + 5-minute candles", type="primary")
selected_key = f"{category}|{instrument}"
cached_key = st.session_state.get("multi_cisd_selected_key")
if refresh or cached_key != selected_key or "multi_cisd_data" not in st.session_state:
    try:
        with st.spinner(f"{spec['provider']} se {instrument} ka futures quote aur 5-minute candles la rahe hain..."):
            market_data, market_report = fetch_market_data(category, instrument)
        st.session_state["multi_cisd_data"] = market_data
        st.session_state["multi_cisd_report"] = market_report
        st.session_state["multi_cisd_selected_key"] = selected_key
        st.session_state.pop("multi_cisd_trades", None)
        st.session_state.pop("multi_cisd_metrics", None)
    except Exception as exc:
        st.error(f"Futures market data fetch nahi hua: {exc}")

if st.session_state.get("multi_cisd_selected_key") == selected_key and "multi_cisd_report" in st.session_state:
    report = st.session_state["multi_cisd_report"]
    q1, q2, q3 = st.columns(3)
    q1.metric("Latest futures price", f"{report['latest_price']:,.5f}")
    q2.metric("Provider / contract", f"{report['provider']} · {report['ticker']}")
    q3.metric("Quote type", report["quote_interval"])
    st.caption(f"Provider timestamp: {report['latest_timestamp']} · Contract: {report['display_name']}")
    st.caption(report["note"])
    data = st.session_state["multi_cisd_data"]
    st.success(
        f"5-minute futures history loaded: {report['history_rows']:,} candles · "
        f"{report['history_start']} → {report['history_end']}"
    )
    cfg = CISDConfig(rr=float(rr), stop_buffer_points=float(buffer), one_trade_per_day=True)
    if st.button(f"Run {instrument} futures CISD scan + backtest"):
        with st.spinner(f"{instrument} 5-minute futures candles par CISD / FVG backtest chal raha hai..."):
            trades, metrics = backtest_cisd(
                data, cfg, charges_bps_per_side=float(charges),
                slippage_points_per_side=float(slippage)
            )
        st.session_state["multi_cisd_trades"] = trades
        st.session_state["multi_cisd_metrics"] = metrics
        st.session_state["multi_cisd_report"] = report
        st.rerun()

st.divider()
with st.expander("Optional: Upload futures OHLC CSV for backtest"):
    uploaded = st.file_uploader("Selected futures contract ka OHLC CSV upload karein", type=["csv"])
    if uploaded is not None:
        try:
            csv_data, csv_report = load_gold_ohlc_csv(uploaded)
            st.success(f"CSV loaded: {csv_report['rows']:,} candles · {csv_report['start']} → {csv_report['end']}")
            cfg_csv = CISDConfig(rr=float(rr), stop_buffer_points=float(buffer), one_trade_per_day=True)
            if st.button("Run uploaded futures CSV backtest"):
                trades, metrics = backtest_cisd(
                    csv_data, cfg_csv, charges_bps_per_side=float(charges),
                    slippage_points_per_side=float(slippage)
                )
                st.session_state["multi_cisd_trades"] = trades
                st.session_state["multi_cisd_metrics"] = metrics
                st.session_state["multi_cisd_report"] = csv_report
                st.rerun()
        except Exception as exc:
            st.error(str(exc))

if "multi_cisd_trades" in st.session_state:
    trades = st.session_state["multi_cisd_trades"]
    metrics = st.session_state["multi_cisd_metrics"]
    st.divider()
    st.subheader("Historical futures CISD backtest")
    cols = st.columns(5)
    cols[0].metric("Trades", metrics.get("total_trades", 0))
    cols[1].metric("Win rate", f"{metrics.get('win_rate', 0):.2f}%")
    pf = metrics.get("profit_factor", 0)
    cols[2].metric("Profit factor", "∞" if pf == float("inf") else f"{pf:.2f}")
    cols[3].metric("Net price units", f"{metrics.get('net_points', 0):+.5f}")
    cols[4].metric("Max drawdown", f"{metrics.get('max_drawdown_points', 0):.5f}")
    st.write(
        f"**Wins:** {metrics.get('wins', 0)} · **Losses:** {metrics.get('losses', 0)} · "
        f"**EOD exits:** {metrics.get('eod_exits', 0)}"
    )
    st.caption("Win rate = TP/(TP+SL); EOD exits alag. Results broker spread, commission, swap, contract size aur execution se alag honge.")
    if len(trades) < 30:
        st.warning("30 se kam trades hain; win rate ko reliable estimate na maanein.")
    if not trades.empty:
        st.dataframe(trades, use_container_width=True, hide_index=True)
        st.download_button(
            "Download trade log CSV", trades.to_csv(index=False).encode("utf-8-sig"),
            "multi_asset_futures_cisd_trades.csv", "text/csv"
        )
        equity = trades["net_points"].cumsum()
        fig = go.Figure(go.Scatter(x=trades["exit_time"], y=equity, mode="lines", name="Cumulative net price units"))
        fig.update_layout(title=f"{instrument} cumulative result", xaxis_title="Exit time", yaxis_title="Cumulative price units", height=360)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Is futures contract aur selected rules par koi qualifying setup nahi mila.")
    data = st.session_state.get("multi_cisd_data")
    if data is not None:
        sessions = list(data.groupby(data.index.date, sort=True))
        if len(sessions) >= 2:
            cfg = CISDConfig(rr=float(rr), stop_buffer_points=float(buffer), one_trade_per_day=True)
            _, day = sessions[-1]
            _, previous = sessions[-2]
            latest = find_day_setup(day, float(previous["High"].max()), float(previous["Low"].min()), cfg)
            st.subheader("Latest session setup")
            if latest:
                st.success(f"{latest['side']} · Entry {latest['entry']:.5f} · SL {latest['stop']:.5f} · Target {latest['target']:.5f}")
            else:
                st.info("Latest session mein qualifying setup nahi mila.")
else:
    if "multi_cisd_data" not in st.session_state:
        st.info("Futures market aur contract select karke data fetch karein.")
