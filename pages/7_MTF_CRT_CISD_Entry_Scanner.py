from __future__ import annotations

import pandas as pd
import streamlit as st

from mtf_analysis import CRT_SPECS, analyze_mtf_symbol

st.set_page_config(page_title="NIFTY CRT + CISD Intraday Scanner", page_icon="🎯", layout="wide")
st.title("🎯 NIFTY 50 — CRT + CISD Intraday Scanner")
st.caption("CRT: Weekly / Daily / 4H / 1H  ·  CISD confirmation: 15M  ·  Entry trigger: 5M")

st.info(
    "नई Strategy सक्रिय: CRT केवल Weekly, Daily, 4H और 1H पर detect होगा। "
    "CRT की M1 range को M2 candle का एक तरफ sweep करके उसी range में close करना होगा। "
    "इसके बाद 15M पर CISD का body-close confirmation और 5M पर post-CISD FVG retest जरूरी है। "
    "पुराना lower-timeframe CHoCH entry logic इस page पर इस्तेमाल नहीं होता। "
    "यह research / alert-only scanner है; कोई broker order place नहीं करता।"
)

symbol = st.text_input("Yahoo Finance symbol", value="^NSEI",
                       help="NIFTY 50 Spot: ^NSEI")
st.caption(
    "Data source: Yahoo Finance (yfinance). 5M/15M candles और intraday history delayed, "
    "limited या incomplete हो सकती हैं। Live execution से पहले broker-grade feed से verify करें."
)

if st.button("🔍 Scan NIFTY CRT + CISD", type="primary", disabled=not symbol.strip()):
    try:
        with st.spinner("Weekly/Daily/4H/1H CRT, 15M CISD और 5M Entry जाँची जा रही है..."):
            result, errors = analyze_mtf_symbol(symbol.strip().upper())
        st.session_state["mtf_crt_cisd_result"] = result
        st.session_state["mtf_crt_cisd_errors"] = errors
        st.session_state["mtf_crt_cisd_symbol"] = symbol.strip().upper()
    except Exception as exc:
        st.error(f"Scan पूरा नहीं हुआ: {type(exc).__name__}: {exc}")

result = st.session_state.get("mtf_crt_cisd_result")
if result is not None:
    st.divider()
    st.subheader(f"Results — {st.session_state.get('mtf_crt_cisd_symbol', symbol)}")
    preferred = [
        "CRT Timeframe", "CRT M1 High", "CRT M1 Low", "CRT M2 High", "CRT M2 Low",
        "CRT Sweep", "15M CISD", "CISD Reference", "5M Entry Status", "FVG Low",
        "FVG High", "Entry Price", "Stop Loss", "Target 1 (2R)", "Target 2 (3R)",
        "Risk Points", "RR", "Signal", "Entry Status", "Alignment",
    ]
    shown = [c for c in preferred if c in result.columns]
    st.dataframe(result[shown], use_container_width=True, hide_index=True)
    ready = result[result["Entry Status"] == "ORDER"] if "Entry Status" in result else pd.DataFrame()
    a, b, c = st.columns(3)
    a.metric("CRT timeframe models", len(CRT_SPECS))
    b.metric("Confirmed BUY/SELL", len(ready))
    c.metric("Data errors", len(st.session_state.get("mtf_crt_cisd_errors", {})))
    if not ready.empty:
        st.success("Fresh 5M FVG retest entry candidate found. Verify current quote and feed before any decision.")
    else:
        st.warning("इस scan में कोई fresh confirmed entry नहीं मिली। WAIT का अर्थ है कि CRT/CISD/5M retest की शर्तें पूरी नहीं हुईं।")
    errors = st.session_state.get("mtf_crt_cisd_errors", {})
    if errors:
        with st.expander("Data limitations / errors"):
            st.json(errors)
    st.download_button(
        "Download scan CSV", result.to_csv(index=False).encode("utf-8-sig"),
        f"{st.session_state.get('mtf_crt_cisd_symbol', 'NIFTY')}_crt_cisd.csv", "text/csv"
    )
else:
    st.caption("NIFTY 50 symbol डालें और scan चलाएँ। चार CRT timeframes के परिणाम अलग-अलग दिखेंगे।")
