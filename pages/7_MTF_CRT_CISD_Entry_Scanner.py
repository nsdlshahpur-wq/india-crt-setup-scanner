from __future__ import annotations

import pandas as pd
import streamlit as st

from mtf_analysis import PAIR_SPECS, analyze_mtf_symbol

st.set_page_config(page_title="Multi-Timeframe CRT + CISD Entry", page_icon="🎯", layout="wide")
st.title("🎯 Multi-Timeframe CRT + CISD Entry Scanner")
st.caption("CRT detection: 1H / 4H / Daily / Weekly · Entry confirmation: 15M / 5M")

st.info(
    "यह research-only scanner है। मौजूदा repository के CRT M1/M2 rule को चुने हुए higher timeframe पर "
    "लागू करता है: M1 range, M2 का एक तरफ liquidity sweep और M1 range के अंदर close। "
    "इसके बाद 15M/5M पर CHoCH → FVG/IFVG/OB/BOB zone → retest confirmation जाँची जाती है। "
    "यह किसी order को place नहीं करता।"
)


symbol = st.text_input("Yahoo Finance symbol", value="^NSEI", help="उदाहरण: ^NSEI, RELIANCE.NS, BTC-USD")
st.caption("Data source: Yahoo Finance (yfinance). Intraday candles delayed/incomplete हो सकती हैं; Yahoo की उपलब्धता के अनुसार 5M/15M history सीमित रहती है. यह broker-grade exchange feed नहीं है.")
if st.button("🔍 Scan all CRT / entry timeframe combinations", type="primary", disabled=not symbol.strip()):
    try:
        with st.spinner("1H, 4H, Daily, Weekly CRT और 15M/5M entry data analyse हो रहा है..."):
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
    st.dataframe(result, use_container_width=True, hide_index=True)
    ready = result[result["Entry Status"] == "ORDER"] if "Entry Status" in result else pd.DataFrame()
    a, b, c = st.columns(3)
    a.metric("Timeframe combinations", len(PAIR_SPECS))
    b.metric("Confirmed entry signals", len(ready))
    c.metric("Data errors", len(st.session_state.get("mtf_crt_cisd_errors", {})))
    if not ready.empty:
        st.success("Confirmed 15M/5M entry candidate(s) found. Verify chart and feed before any decision.")
    else:
        st.warning("इस scan में कोई fresh confirmed entry नहीं मिली। WAIT status का अर्थ है कि confirmation/retest अभी पूरा नहीं हुआ।")
    errors = st.session_state.get("mtf_crt_cisd_errors", {})
    if errors:
        with st.expander("Data limitations / errors"):
            st.json(errors)
    st.download_button("Download scan CSV", result.to_csv(index=False).encode("utf-8-sig"),
                       f"{st.session_state.get('mtf_crt_cisd_symbol', 'symbol')}_mtf_crt_cisd.csv",
                       "text/csv")
else:
    st.caption("Symbol डालें और scan चलाएँ। सभी आठ combinations अलग-अलग दिखाई देंगे।")
