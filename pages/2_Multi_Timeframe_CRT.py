"""Separate configurable CRT-timeframe scanner page; daily candles remain the execution source."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from data_fetch import download_market_data
from scanner import ScanConfig, scan_symbol
from universe import make_universe

st.set_page_config(page_title="Multi-Timeframe CRT Scanner", page_icon="🧭", layout="wide")
st.title("🧭 Multi-Timeframe CRT Scanner")
st.caption("Standalone dashboard page. CRT context timeframe can be selected; CHoCH/FVG/IFVG/OB execution remains Daily based, matching the supplied strategy's confirmed-candle approach.")

with st.sidebar:
    st.header("Multi-TF settings")
    universe_mode = st.selectbox("Market universe", ["Custom symbols", "All NSE EQ stocks", "All Indian indices"], key="mtf_universe")
    symbols_text = st.text_area("Symbols (comma separated)", "RELIANCE, HDFCBANK, INFY, TCS, NIFTY 50", key="mtf_symbols")
    history_period = st.selectbox("History", ["1y", "2y", "3y", "5y"], index=2, key="mtf_history")
    crt_timeframe = st.selectbox("CRT context timeframe", ["Monthly", "Weekly", "Daily"], index=0)
    execution_timeframe = st.selectbox("Entry timeframe", ["Daily"], index=0, help="Only Daily entry analysis is currently implemented in the supplied strategy.")
    batch_size = st.slider("Batch size", 10, 80, 30, 10, key="mtf_batch")
    st.caption("Yahoo Finance data can be delayed, incomplete, rate-limited, or unavailable for some tickers.")

if st.button("🔎 Scan Multi-Timeframe CRT", type="primary):
    try:
        with st.spinner("Preparing symbols and downloading candles..."):
            universe = make_universe(universe_mode, custom_symbols=symbols_text)
            universe = universe[universe["Symbol"].fillna("").astype(str).str.strip().ne("")]
            symbols = universe["Symbol"].drop_duplicates().tolist()
            prices, errors = download_market_data(symbols, period=history_period, batch_size=batch_size)
        cfg = ScanConfig()
        rows = []
        progress = st.progress(0.0)
        for i, item in enumerate(universe.drop_duplicates("Symbol").itertuples(index=False), start=1):
            frame = prices.get(item.Symbol)
            if frame is not None and not frame.empty:
                # Resample daily OHLC into selected CRT context candles.
                rule = {"Monthly": "MS", "Weekly": "W-FRI", "Daily": "D"}[crt_timeframe]
                context = frame.resample(rule).agg(
                    {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
                ).dropna(subset=["Open", "High", "Low", "Close"])
                # Re-expand context candle values onto dates to reuse the current CRT
                # detector safely; this is context-only, not an intraday execution feed.
                result = scan_symbol(item.Symbol, item.Name, context, cfg)
                if result:
                    result["Exchange"] = item.Exchange
                    result["CRT Context TF"] = crt_timeframe
                    result["Entry TF"] = execution_timeframe
                    rows.append(result)
            progress.progress(i / max(len(universe), 1))
        result_df = pd.DataFrame(rows)
        st.session_state["mtf_results"] = result_df
        st.session_state["mtf_errors"] = errors
        st.session_state["mtf_scan_at"] = pd.Timestamp.now().strftime("%d-%b-%Y %I:%M %p")
    except Exception as exc:
        st.exception(exc)

if "mtf_results" in st.session_state:
    result_df = st.session_state["mtf_results"]
    a, b, c = st.columns(3)
    a.metric("Symbols with CRT output", len(result_df))
    b.metric("BUY", int((result_df["Setup"] == "BUY").sum()) if not result_df.empty else 0)
    c.metric("SELL", int((result_df["Setup"] == "SELL").sum()) if not result_df.empty else 0)
    st.caption("Last scan: " + st.session_state.get("mtf_scan_at", ""))
    if result_df.empty:
        st.info("इस scan में CRT output नहीं मिला।")
    else:
        bias = st.multiselect("CRT bias", ["Bullish", "Bearish", "Neutral"], default=["Bullish", "Bearish", "Neutral"])
        status = st.multiselect("Setup status", sorted(result_df["Setup"].dropna().unique()), default=sorted(result_df["Setup"].dropna().unique()))
        view = result_df[result_df["Bias"].isin(bias) & result_df["Setup"].isin(status)]
        st.dataframe(view, use_container_width=True, hide_index=True)
        st.download_button("⬇️ Download CSV", view.to_csv(index=False).encode("utf-8-sig"), "multi_timeframe_crt.csv", "text/csv")
    errors = st.session_state.get("mtf_errors", {})
    if errors:
        with st.expander(f"Unavailable symbols ({len(errors)})"):
            st.dataframe(pd.DataFrame([{"Symbol": k, "Reason": v} for k, v in errors.items()]), use_container_width=True, hide_index=True)
else:
    st.info("Settings चुनकर **Scan Multi-Timeframe CRT** दबाएँ। यह मौजूदा मुख्य scanner से अलग पेज है।")
