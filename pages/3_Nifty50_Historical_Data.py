from __future__ import annotations

import pandas as pd
import streamlit as st

from nifty50_history import load_full_nifty50_1m, SOURCE_REPO

st.set_page_config(page_title="Nifty 50 Historical Data", page_icon="📚", layout="wide")
st.title("📚 Nifty 50 — Full Historical Data")
st.caption("यह पेज अलग Multi-Timeframe Scanner के लिए 1-minute historical data लोड करता है। पुराने CRT Scanner को नहीं बदलता।")
st.markdown(f"**Data source:** [{SOURCE_REPO}]({SOURCE_REPO})")
st.info("पूरा CSV डेटा Python source में hard-code नहीं किया गया है। ऐप जरूरत पर GitHub से सभी उपलब्ध सालाना/मासिक फाइलें डाउनलोड करके Streamlit cache में रखता है। इससे GitHub repository अनावश्यक रूप से कई GB की नहीं होती।")

if st.button("⬇️ Download / Load complete Nifty 50 history", type="primary"):
    with st.spinner("2017 से उपलब्ध नवीनतम महीने तक सभी 1-minute CSV डाउनलोड और जोड़ रहे हैं..."):
        try:
            data, report = load_full_nifty50_1m()
            st.session_state["nifty50_full_history"] = data
            st.session_state["nifty50_history_report"] = report
        except Exception as exc:
            st.error(f"Data load failed: {exc}")

data = st.session_state.get("nifty50_full_history")
report = st.session_state.get("nifty50_history_report")
if data is not None and report:
    a, b, c, d = st.columns(4)
    a.metric("Total 1-minute candles", f'{len(data):,}')
    b.metric("First date", data.index.min().strftime("%d-%b-%Y"))
    c.metric("Latest date", data.index.max().strftime("%d-%b-%Y"))
    d.metric("Years covered", len(report.get("years", [])))

    st.subheader("Year-wise data")
    yearly = data.groupby(data.index.year).size().rename("1-minute candles").to_frame()
    st.dataframe(yearly, use_container_width=True)

    st.subheader("Data integrity / download report")
    st.write(f"Files loaded: {len(report['files_loaded'])}")
    st.write(f"Missing files (not published / unavailable): {', '.join(report['files_missing']) or 'None'}")
    if report["errors"]:
        st.warning("\n".join(report["errors"]))
    else:
        st.success("All downloaded files passed the basic OHLC validation.")
    st.caption("Source CSVs have known gaps/outages and special-session rows. Backtest results must disclose these limitations.")

    st.subheader("Timeframe aggregation preview")
    agg = st.selectbox("Preview timeframe", ["15min", "60min"])
    bars = data.resample(agg, origin="start_day", offset="15min", label="left", closed="left").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last"}
    ).dropna()
    st.write(f"{len(bars):,} aggregated candles")
    st.dataframe(bars.tail(30), use_container_width=True)

    st.download_button(
        "Download combined OHLC CSV",
        data=data.to_csv().encode("utf-8"),
        file_name="NIFTY50_1min_full_history.csv",
        mime="text/csv",
    )
else:
    st.caption("ऊपर बटन दबाने पर पूरा उपलब्ध इतिहास डाउनलोड होगा।")
