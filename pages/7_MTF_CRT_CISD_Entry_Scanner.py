from __future__ import annotations

import pandas as pd
import streamlit as st

from mtf_analysis import PAIR_SPECS, analyze_mtf_symbol\nfrom dhan_live import fetch_dhan_live_ticker

st.set_page_config(page_title="Multi-Timeframe CRT + CISD Entry", page_icon="🎯", layout="wide")
st.title("🎯 Multi-Timeframe CRT + CISD Entry Scanner")
st.caption("CRT detection: 1H / 4H / Daily / Weekly · Entry confirmation: 15M / 5M")

st.info(
    "यह research-only scanner है। मौजूदा repository के CRT M1/M2 rule को चुने हुए higher timeframe पर "
    "लागू करता है: M1 range, M2 का एक तरफ liquidity sweep और M1 range के अंदर close। "
    "इसके बाद 15M/5M पर CHoCH → FVG/IFVG/OB/BOB zone → retest confirmation जाँची जाती है। "
    "यह किसी order को place नहीं करता।"
)


st.divider()
st.subheader("DhanHQ Live Market Feed — Connection Test")
st.caption("यह केवल read-only live LTP test है। सही Futures contract का Dhan Security ID चुनें; अनुमानित ID या spot instrument न डालें.")
dhan_col1, dhan_col2, dhan_col3 = st.columns([1, 1, 1])
with dhan_col1:
    dhan_segment = st.selectbox("Dhan Exchange Segment", ["MCX_COMM", "NSE_FNO", "NSE_EQ"], index=0)
with dhan_col2:
    dhan_security_id = st.text_input("Futures Security ID", placeholder="Dhan instrument master se numeric ID")
with dhan_col3:
    st.write("")
    st.write("")
    dhan_test = st.button("Test Dhan Live Feed", type="secondary", disabled=not dhan_security_id.strip())
if dhan_test:
    try:
        with st.spinner("Dhan WebSocket se live ticker ka intezar..."):
            quote = fetch_dhan_live_ticker(dhan_segment, dhan_security_id.strip())
        st.session_state["dhan_live_quote"] = quote
        st.success("Dhan se matching live ticker packet receive hua.")
    except Exception as exc:
        st.session_state["dhan_live_error"] = f"{type(exc).__name__}: {exc}"
        st.error(st.session_state["dhan_live_error"])
quote = st.session_state.get("dhan_live_quote")
if quote:
    q1, q2, q3 = st.columns(3)
    q1.metric("Dhan Live LTP", f'{quote["ltp"]:,.2f}')
    q2.metric("Security ID", quote["security_id"])
    q3.metric("Feed Status", quote["status"])
    st.caption(f'Provider: {quote["provider"]} · Segment: {quote["exchange_segment"]} · Last trade UTC: {quote["last_trade_time"]} · Received UTC: {quote["received_at"]}')
st.warning("Dhan LTP connection test ko abhi CRT candle source se alag rakha gaya hai. CRT/CISD signals tab tak Yahoo historical candles par hi calculate honge jab tak Dhan historical OHLC + live candle aggregation integration aur validation complete nahi hoti.")
\nsymbol = st.text_input("Yahoo Finance symbol", value="^NSEI", help="उदाहरण: ^NSEI, RELIANCE.NS, BTC-USD")
st.caption("Data source: Yahoo Finance. Intraday history सीमित और delayed/incomplete हो सकती है. 15M/5M entry history फिलहाल पिछले लगभग 60 दिनों तक सीमित है.")
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
