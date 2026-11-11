from __future__ import annotations

import pandas as pd
import streamlit as st

from data_fetch import download_market_data
from scanner import ScanConfig, scan_symbol
from storage import add_alert, add_watchlist, list_alerts, list_watchlist, remove_watchlist

st.set_page_config(page_title="Watchlist & Alerts", page_icon="🔔", layout="wide")
st.title("🔔 Watchlist & Monthly-Daily CRT Alerts")
st.caption("Watchlist symbols are checked only with Monthly (1M) liquidity context and Daily (1D) entry logic.")

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
    st.subheader("Scan Monthly-Daily CRT and create alerts")
    st.caption("एक बार में अधिकतम 10 symbols; alert तभी बनेगा जब Entry trigger हो और M1 Target pending हो।")
    if st.button("🔎 Scan Watchlist", type="primary"):
        symbols = watch["Symbol"].astype(str).tolist()[:10]
        if len(watch) > 10:
            st.warning("पहले 10 symbols scan किए गए हैं। बाकी symbols अगले scan में जाँचें।")
        with st.spinner("Daily OHLC data डाउनलोड और Monthly-Daily CRT जाँच जारी है..."):
            price_map, errors = download_market_data(symbols, period="1y", batch_size=10)
        output = []
        new_alerts = []
        for idx, ticker in enumerate(symbols, start=1):
            prices = price_map.get(ticker, pd.DataFrame())
            label = watch.loc[watch["Symbol"] == ticker, "Label"].iloc[0] if "Label" in watch.columns and (watch["Symbol"] == ticker).any() else ticker
            if prices.empty:
                output.append({"Symbol": ticker, "Name": label, "Setup": "NO DATA", "Data Note": errors.get(ticker, "No Daily OHLC returned")})
                continue
            try:
                row = scan_symbol(ticker, label, prices, ScanConfig())
                if row is None:
                    output.append({"Symbol": ticker, "Name": label, "Setup": "NO CRT CONTEXT", "Data Note": "कम से कम 3 monthly buckets और पर्याप्त Daily candles चाहिए।"})
                    continue
                output.append(row)
                if row.get("Stage") == 3 and row.get("Setup") in {"BUY", "SELL"} and row.get("Target Status") == "TARGET PENDING":
                    dedupe = f"{ticker}|{row.get('Setup')}|{row.get('Entry Date')}|{row.get('Entry Zone Type')}"
                    message = (
                        f"Monthly-Daily CRT {row['Setup']} · zone {row.get('Entry Zone Type', '')} · "
                        f"entry {row.get('Entry')} · SL {row.get('SL')} · "
                        f"M1 target {row.get('Target (M1 Monthly H/L)')}"
                    )
                    if add_alert(dedupe, ticker, "Monthly-Daily", "ENTRY ACTIVE", message):
                        new_alerts.append(message)
            except Exception as exc:
                output.append({"Symbol": ticker, "Name": label, "Setup": "ERROR", "Data Note": f"{type(exc).__name__}: {exc}"})

            progress_placeholder = st.session_state.get("_watch_progress")
            if progress_placeholder is not None:
                progress_placeholder.progress(idx / max(len(symbols), 1))

        st.session_state["watch_scan_results"] = pd.DataFrame(output)
        st.session_state["watch_scan_new_alerts"] = new_alerts
        for msg in new_alerts:
            st.toast(msg, icon="🔔")
        st.rerun()

    scan_results = st.session_state.get("watch_scan_results")
    if isinstance(scan_results, pd.DataFrame) and not scan_results.empty:
        st.subheader("Latest scan results")
        show_cols = [
            "Symbol", "Name", "Bias", "Setup", "Entry Status", "Entry Zone Type",
            "Target Status", "Entry", "SL", "Target (M1 Monthly H/L)", "Monthly Status",
            "Sweep Date", "CHoCH Date", "Retest Date", "Entry Date", "Data Note",
        ]
        st.dataframe(scan_results[[c for c in show_cols if c in scan_results.columns]], use_container_width=True, hide_index=True)
        st.download_button(
            "⬇ Download latest scan CSV",
            scan_results.to_csv(index=False).encode("utf-8-sig"),
            file_name="watchlist_monthly_daily_crt.csv",
            mime="text/csv",
        )

st.divider()
st.subheader("Alert history")
alerts = list_alerts()
if alerts.empty:
    st.info("अभी कोई नया Active Monthly-Daily CRT alert दर्ज नहीं है।")
else:
    st.dataframe(alerts, use_container_width=True, hide_index=True)
    st.download_button(
        "⬇ Download alert history CSV",
        alerts.to_csv(index=False).encode("utf-8-sig"),
        file_name="crt_alert_history.csv",
        mime="text/csv",
    )

st.caption("Alerts app के अंदर log/toast होते हैं। Browser push, WhatsApp या email notifications अभी configured नहीं हैं.")
