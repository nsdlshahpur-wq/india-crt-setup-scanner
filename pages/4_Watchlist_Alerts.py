from __future__ import annotations

import pandas as pd
import streamlit as st

from mtf_scanner import analyze_multi_timeframe
from storage import add_alert, add_watchlist, list_alerts, list_watchlist, remove_watchlist

st.set_page_config(page_title="Watchlist & Alerts", page_icon="🔔", layout="wide")
st.title("🔔 Watchlist & CRT Alerts")
st.caption("Track only the symbols you add. Click Scan Watchlist to check valid CRT and Entry Ready states.")

with st.form("add_watch_symbol", clear_on_submit=True):
    c1, c2, c3 = st.columns([2, 2, 1])
    symbol = c1.text_input("Yahoo symbol", placeholder="RELIANCE.NS / ^NSEI / TCS.BO")
    label = c2.text_input("Company / index name (optional)")
    submitted = c3.form_submit_button("＋ Add")
    if submitted:
        try:
            added = add_watchlist(symbol, label)
            st.success("Watchlist में जोड़ा गया।" if added else "यह symbol पहले से मौजूद है।")
        except Exception as exc:
            st.error(str(exc))

watch = list_watchlist()
st.subheader(f"Your watchlist ({len(watch)})")
if watch.empty:
    st.info("अभी watchlist खाली है। ऊपर symbol जोड़ें।")
else:
    remove_symbol = st.selectbox("Remove symbol", ["—"] + watch["Symbol"].tolist())
    if st.button("Remove selected", disabled=remove_symbol == "—"):
        remove_watchlist(remove_symbol)
        st.rerun()
    st.dataframe(watch, use_container_width=True, hide_index=True)
    st.download_button(
        "⬇ Download watchlist CSV",
        watch.to_csv(index=False).encode("utf-8-sig"),
        file_name="crt_watchlist.csv",
        mime="text/csv",
    )

if not watch.empty:
    st.divider()
    st.subheader("Scan and create alerts")
    st.caption("Checks all five CRT → Entry timeframe pairs. To control provider requests, one scan is limited to 20 symbols.")
    if st.button("🔎 Scan Watchlist", type="primary):
        symbols = watch["Symbol"].astype(str).tolist()[:20]
        if len(watch) > 20:
            st.warning("पहले 20 symbols scan किए गए हैं। बाकी symbols अगले scan में जाँचें।")
        output = []
        new_alerts = []
        progress = st.progress(0.0)
        for idx, ticker in enumerate(symbols, start=1):
            try:
                rows, errors = analyze_multi_timeframe(ticker)
                for row in rows:
                    status = row.get("CRT Status", "")
                    mark = row.get("CRT Mark", "")
                    if mark == "✓ VALID CRT" and status in {"VALID - WAIT ENTRY", "ENTRY READY"}:
                        crt_candle = row.get("CRT Candle") or "unknown"
                        dedupe = f"{ticker}|{row['CRT TF']}|{status}|{crt_candle}"
                        message = f"{row['CRT TF']} CRT → {row['Entry TF']} entry · {status} · {row.get('HTF Bias', '')}"
                        is_new = add_alert(dedupe, ticker, row["CRT TF"], status, message)
                        if is_new:
                            new_alerts.append(message)
                    output.append({"Symbol": ticker, **row})
            except Exception as exc:
                output.append({"Symbol": ticker, "CRT TF": "-", "Entry TF": "-", "CRT Status": "ERROR", "Data Note": str(exc)})
            progress.progress(idx / len(symbols))
        st.session_state["watch_scan_results"] = pd.DataFrame(output)
        st.session_state["watch_scan_new_alerts"] = new_alerts
        for msg in new_alerts:
            st.toast(msg, icon="🔔")
        st.rerun()

    scan_results = st.session_state.get("watch_scan_results")
    if isinstance(scan_results, pd.DataFrame) and not scan_results.empty:
        st.subheader("Latest scan results")
        st.dataframe(scan_results, use_container_width=True, hide_index=True)
        st.download_button(
            "⬇ Download latest scan CSV",
            scan_results.to_csv(index=False).encode("utf-8-sig"),
            file_name="watchlist_crt_scan.csv",
            mime="text/csv",
        )

st.divider()
st.subheader("Alert history")
alerts = list_alerts()
if alerts.empty:
    st.info("अभी कोई नया valid CRT alert दर्ज नहीं है।")
else:
    st.dataframe(alerts, use_container_width=True, hide_index=True)
    st.download_button(
        "⬇ Download alert history CSV",
        alerts.to_csv(index=False).encode("utf-8-sig"),
        file_name="crt_alert_history.csv",
        mime="text/csv",
    )

st.caption("अभी alerts app के अंदर log/toast होते हैं। Browser push, WhatsApp या email alerts के लिए अलग notification credentials/configuration जोड़ना होगा.")
