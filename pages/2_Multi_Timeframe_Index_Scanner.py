from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from intraday_scanner import WATCHLIST, analyse_symbol

st.set_page_config(page_title="Multi-Timeframe Index Scanner", page_icon="🧭", layout="wide")
st.title("🧭 Multi-Timeframe Index & OB/FVG Scanner")
st.caption("यह मौजूदा CRT Scanner से अलग पेज है। Existing CRT rules, scanner.py और Backtest को यह पेज नहीं बदलता।")

st.info("यह अलग scanner Daily breakout context, 1H structure/CHoCH, OB candidates और FVG candidates तथा 15M retest को जाँचता है। Yahoo Finance intraday data delayed/incomplete हो सकता है; यह order execute नहीं करता।")

c1, c2 = st.columns([2, 1])
with c1:
    selected_name = st.selectbox("Index चुनें", list(WATCHLIST.keys()) + ["Custom NSE symbol"])
with c2:
    custom = st.text_input("Custom symbol (उदा. TEXMOPIPES.NS)", disabled=selected_name != "Custom NSE symbol")

if selected_name == "Custom NSE symbol":
    symbol = custom.strip().upper()
    name = symbol or "Custom"
else:
    symbol = WATCHLIST[selected_name]
    name = selected_name

run = st.button("🔍 Run separate MTF scan", type="primary", disabled=not symbol)
if run:
    try:
        with st.spinner("Daily, 1H और 15M candles डाउनलोड एवं analyse हो रहे हैं..."):
            result = analyse_symbol(symbol, name)
        st.session_state["mtf_scan_result"] = result
    except Exception as exc:
        st.error(f"Scan पूरा नहीं हुआ: {exc}")

result = st.session_state.get("mtf_scan_result")
if result:
    st.divider()
    st.subheader(result["Name"])
    a,b,c,d = st.columns(4)
    a.metric("Latest Daily Close", f'{result["Last Daily Close"]:,.2f}')
    b.metric("Daily Bias", result["Daily Bias"])
    c.metric("Daily Breakout", result["Daily Breakout"])
    d.metric("1H CHoCH", result["1H CHoCH"])
    e,f,g = st.columns(3)
    e.metric("20-session Resistance", f'{result["20-session Resistance"]:,.2f}')
    f.metric("20-session Support", f'{result["20-session Support"]:,.2f}')
    g.metric("1H Bias", result["1H Bias"])
    st.caption(f'Data candles — Daily: {result["Daily Candle"]} · 1H: {result["1H Candle"]} · 15M: {result["15M Candle"]}')

    st.subheader("OB / FVG candidate zones")
    zones = pd.DataFrame(result["Zones"])
    if zones.empty:
        st.warning("Latest data में कोई mechanical FVG/OB candidate नहीं मिला।")
    else:
        st.dataframe(zones, use_container_width=True, hide_index=True)
        st.caption("OB/FVG candidate labels mechanical OHLC rules से बने हैं। Advance OB discretionary concept है; इस version में उसे स्वतः confirmed नहीं माना गया है। Retest candidate का अर्थ केवल zone overlap है, entry trigger नहीं।")

    st.subheader("15M price chart")
    frame = result["Fifteen"].tail(160)
    fig = go.Figure(data=[go.Candlestick(x=frame.index, open=frame.Open, high=frame.High, low=frame.Low, close=frame.Close, name="15M")])
    for zone in result["Zones"]:
        fig.add_hrect(y0=zone["Low"], y1=zone["High"], opacity=0.16, line_width=1, annotation_text=zone["Type"])
    fig.update_layout(height=560, xaxis_rangeslider_visible=False, title=f'{result["Name"]} · 15 Minute')
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("1H chart"):
        h = result["Hourly"].tail(160)
        hf = go.Figure(data=[go.Candlestick(x=h.index, open=h.Open, high=h.High, low=h.Low, close=h.Close, name="1H")])
        for zone in result["Zones"]:
            hf.add_hrect(y0=zone["Low"], y1=zone["High"], opacity=0.12, line_width=1, annotation_text=zone["Type"])
        hf.update_layout(height=480, xaxis_rangeslider_visible=False)
        st.plotly_chart(hf, use_container_width=True)
else:
    st.caption("Index चुनें और Run दबाएँ। परिणाम इसी अलग पेज पर आएँगे; मुख्य CRT Scanner के परिणाम/सेटिंग्स अलग रहेंगे।")
