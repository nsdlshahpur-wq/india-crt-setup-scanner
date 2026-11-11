from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from backtesting import backtest_symbol
from data_fetch import download_market_data
from scanner import ScanConfig

st.set_page_config(page_title="CRT Backtesting & Performance", page_icon="📊", layout="wide")
st.title("📊 Backtesting & Performance")
st.caption("3-year historical replay: Monthly CRT sweep/reclaim → Daily CHoCH → retest in FVG / IFVG / OB / BOB; sweep-candle SL; opposite M1 liquidity target.")

scan_map = st.session_state.get("scan_price_map", {})
scan_names = st.session_state.get("scan_symbol_names", {})
if scan_map:
    choices = sorted(scan_map)
    symbol = st.selectbox(
        "Select symbol from your last market scan",
        choices,
        format_func=lambda x: f"{x} — {scan_names.get(x, '')}",
    )
    use_last_scan = st.checkbox("Use last scan data", value=True)
else:
    symbol = st.text_input("NSE / BSE symbol (bare NSE symbols are auto-mapped to .NS)", "RELIANCE")
    use_last_scan = False

with st.sidebar:
    st.subheader("Backtest settings")
    period_bars = st.selectbox("Backtest period", [756], index=0, format_func=lambda n: "3 years (~756 daily candles)")
    capital = st.number_input("Initial capital (₹)", min_value=10000.0, value=100000.0, step=10000.0)
    risk_pct = st.slider("Risk per trade (%)", 0.25, 3.0, 1.0, 0.25)
    st.caption("Target: Opposite CRT liquidity (not fixed R).")
    holding = st.slider("Maximum holding days", 1, 60, 20)
    costs_bps = st.number_input("Round-trip charges + slippage (basis points)", min_value=0.0, max_value=100.0, value=10.0, step=1.0)

if st.button("▶ Run historical backtest", type="primary"):
    try:
        if use_last_scan and symbol in scan_map:
            prices = scan_map[symbol].copy()
            company_name = scan_names.get(symbol, symbol)
        else:
            with st.spinner(f"Downloading daily candles for {symbol}..."):
                price_result, errors = download_market_data([symbol], period="3y", batch_size=1)
            prices = price_result.get(symbol, pd.DataFrame())
            company_name = symbol
            if prices.empty:
                st.error(f"Data unavailable for {symbol}: {errors.get(symbol, 'No OHLC history returned')}")
                st.stop()

        with st.spinner("Replaying historical completed candles without look-ahead entries..."):
            result = backtest_symbol(
                symbol=symbol,
                name=company_name,
                raw_data=prices,
                config=ScanConfig(),
                lookback_bars=int(period_bars),
                initial_capital=float(capital),
                risk_per_trade_pct=float(risk_pct),
                target_r=None,
                max_holding_bars=int(holding),
                round_trip_cost_bps=float(costs_bps),
            )
        st.session_state["backtest_result"] = result
        st.session_state["backtest_symbol"] = symbol
        st.session_state["backtest_settings"] = {
            "Initial Capital": capital, "Risk / trade %": risk_pct,
            "Target": "Opposite CRT liquidity", "Max holding days": holding,
            "Round-trip cost bps": costs_bps, "Backtest bars": period_bars,
        }
    except Exception as exc:
        st.exception(exc)

result = st.session_state.get("backtest_result")
if result:
    metrics = result["metrics"]
    st.subheader(f"Results — {st.session_state.get('backtest_symbol', '')}")
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total Trades", f"{metrics['total_trades']:,}")
    m2.metric("Win Rate", f"{metrics['win_rate']:.1f}%")
    pf = metrics["profit_factor"]
    m3.metric("Profit Factor", "∞" if pf is None else f"{pf:.2f}")
    m4.metric("Average RR", f"{metrics['average_rr']:.2f}R")
    m5.metric("Max Drawdown", f"{metrics['max_drawdown_pct']:.2f}%")
    p1, p2, p3 = st.columns(3)
    p1.metric("Net P&L", f"₹{metrics['net_pnl']:,.2f}")
    p2.metric("Ending Equity", f"₹{metrics['ending_equity']:,.2f}")
    p3.metric("Max Drawdown Amount", f"₹{metrics['max_drawdown_amount']:,.2f}")

    st.caption(result.get("message", ""))
    if not result["equity_curve"].empty:
        curve = result["equity_curve"]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=curve["Date"], y=curve["Equity"], mode="lines", name="Equity"))
        fig.update_layout(title="Equity Curve", xaxis_title="Exit date", yaxis_title="Equity (₹)", height=360, template="plotly_white")
        st.plotly_chart(fig, use_container_width=True)

    trades = result["trades"]
    st.subheader("Trade history")
    if trades.empty:
        st.info("चयनित अवधि में scanner के पूरे नियमों के अनुसार कोई completed BUY/SELL trade नहीं मिला।")
    else:
        st.dataframe(trades, use_container_width=True, hide_index=True)
        st.download_button(
            "⬇ Download backtest trades CSV",
            trades.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"{st.session_state.get('backtest_symbol', 'symbol')}_crt_backtest.csv",
            mime="text/csv",
        )
    with st.expander("Backtest assumptions — read before interpreting results"):
        st.markdown(
            "- Signal केवल उस daily candle के close होने पर माना जाता है जिस दिन scanner BUY/SELL देता है.\n"
            "- CHoCH के बाद FVG retest-confirmation signal के अगले trading session के Open पर entry simulate होती है; उसी candle close पर fill नहीं मानते.\n"
            "- Daily candle में SL और Target दोनों touch हों, तो conservative रूप से SL पहले माना जाता है.\n"
            "- Position size risk-per-trade और available cash से निकाली जाती है; leverage नहीं माना गया.\n"
            "- Target opposite CRT liquidity (M1 range का opposite extreme) है; fixed R target नहीं.\n"
            "- SL sweep/reclaim करने वाली actual daily sweep candle के High/Low पर रखा जाता है.\n"
            "- Brokerage, taxes, spread और slippage को एक अनुमानित round-trip basis-point cost से दर्शाया गया है; वास्तविक charges अलग हो सकते हैं.\n"
            "- Backtest एक symbol पर एक समय में एक position रखता है. यह simulation है, future performance की guarantee नहीं."
        )
else:
    st.info("Symbol चुनें और **Run historical backtest** दबाएँ। Backtest पिछले 3 वर्षों के daily candles पर चलेगा।")
