from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from data_fetch import download_market_data
from scanner import ScanConfig, scan_symbol
from universe import make_universe

st.set_page_config(page_title="India CRT Setup Scanner", page_icon="📈", layout="wide")
st.title("🇮🇳 India CRT Setup Scanner")
st.caption("Monthly CRT Bias  →  Daily Liquidity Sweep  →  Displacement Entry")

with st.sidebar:
    st.header("Scanner Settings")
    universe_mode = st.selectbox(
        "Market universe",
        [
            "All NSE + BSE stocks + all indices",
            "All India stocks + indices",
            "All NSE + BSE stocks",
            "All NSE EQ stocks",
            "All BSE EQ stocks",
            "All Indian indices",
            "Custom symbols",
        ],
        index=0,
        help="Loads NSE EQ stocks, BSE equity scrips and the Nifty equity-index catalogue. Only verified Yahoo tickers can be downloaded; unmapped indices are listed separately.",
    )
    custom_symbols = ""
    if universe_mode == "Custom symbols":
        custom_symbols = st.text_area(
            "Symbols (comma separated)",
            "RELIANCE, HDFCBANK, INFY, TCS, NIFTY 50, NIFTY BANK",
            height=90,
        )
    history_period = st.selectbox("Daily history", ["1y", "2y", "3y", "5y"], index=2)
    batch_size = st.slider("Download batch size", min_value=10, max_value=80, value=30, step=10)
    st.divider()
    st.subheader("Strategy")
    atr_length = st.number_input("ATR Length", min_value=2, max_value=100, value=14)
    displacement_atr = st.number_input("Displacement × ATR", min_value=0.1, max_value=5.0, value=1.2, step=0.1)
    pivot_left = st.number_input("Pivot Left", min_value=1, max_value=15, value=3)
    pivot_right = st.number_input("Pivot Right", min_value=1, max_value=15, value=3)
    sweep_lookback = st.number_input("Sweep Lookback (daily candles)", min_value=3, max_value=40, value=10)
    entry_valid_days = st.number_input("Entry valid (daily candles)", min_value=1, max_value=10, value=3)
    only_setup = st.checkbox("Show only setup-ready symbols", value=True)
    st.divider()
    st.caption(
        "Data source: Yahoo Finance via yfinance. This is an unofficial source; prices can be delayed, "
        "incomplete, or unavailable. The scanner is read-only and does not place orders."
    )

col_a, col_b = st.columns([1, 4])
with col_a:
    refresh = st.button("🔄 Scan market", type="primary", use_container_width=True)
with col_b:
    st.caption("Daily strategy checks completed candles. For the cleanest daily scan, run after the NSE cash-market close.")


@st.cache_data(ttl=1800, show_spinner=False)
def _load_universe(mode: str, custom: str) -> pd.DataFrame:
    return make_universe(mode, custom_symbols=custom)


if refresh:
    try:
        with st.spinner("Loading the NSE symbol universe..."):
            universe = _load_universe(universe_mode, custom_symbols)
        if universe.empty:
            st.error("इस चयन के लिए कोई symbol नहीं मिला। NSE/BSE master या symbol spelling जाँचें।")
            st.stop()

        downloadable = universe[universe["Symbol"].fillna("").astype(str).str.strip().ne("")].copy()
        unmapped = universe[universe["Symbol"].fillna("").astype(str).str.strip().eq("")].copy()
        st.info(
            f"Universe में {len(universe):,} entries हैं; {len(downloadable):,} के Yahoo Finance symbols mapped हैं। "
            "Unmapped indices और unavailable data अलग सूची में दिखेंगे."
        )
        progress = st.progress(0.0, text="Preparing data download...")
        status = st.empty()

        def update_progress(done: int, total: int, last_symbol: str):
            pct = done / max(total, 1)
            progress.progress(pct, text=f"Data download: {done:,}/{total:,}")
            status.caption(f"Last processed: {last_symbol}")

        cfg = ScanConfig(
            atr_length=int(atr_length),
            displacement_atr=float(displacement_atr),
            pivot_left=int(pivot_left),
            pivot_right=int(pivot_right),
            sweep_lookback=int(sweep_lookback),
            entry_valid_days=int(entry_valid_days),
        )
        price_map, errors = download_market_data(
            downloadable["Symbol"].drop_duplicates().tolist(),
            period=history_period,
            batch_size=int(batch_size),
            progress_callback=update_progress,
        )
        for item in unmapped.itertuples(index=False):
            if item.Type == "Source warning":
                errors[f"{item.Exchange} | {item.Name}"] = "Exchange master could not be loaded"
            else:
                errors[f"{item.Exchange} INDEX | {item.Name}"] = "Official index is catalogued, but no verified Yahoo Finance ticker mapping is configured"

        rows = []
        scan_progress = st.progress(0.0, text="Calculating CRT setups...")
        scan_rows = downloadable.drop_duplicates(subset=["Symbol", "Name", "Exchange"])
        total_scan_rows = max(len(scan_rows), 1)
        for i, item in enumerate(scan_rows.itertuples(index=False), start=1):
            prices = price_map.get(item.Symbol)
            if prices is not None:
                result = scan_symbol(item.Symbol, item.Name, prices, cfg)
                if result:
                    result["Exchange"] = item.Exchange
                    result["Category"] = item.Category
                    rows.append(result)
            scan_progress.progress(i / total_scan_rows, text=f"Scanning {i:,}/{len(scan_rows):,}")

        result_df = pd.DataFrame(rows)
        if not result_df.empty:
            stage_order = {3: 0, 2: 1, 1: 2, 0: 3}
            result_df["_order"] = result_df["Stage"].map(stage_order).fillna(4)
            result_df = result_df.sort_values(["_order", "Symbol"]).drop(columns="_order")
            if only_setup:
                result_df = result_df[result_df["Stage"] >= 1]

        st.session_state["scan_results"] = result_df
        st.session_state["scan_universe_count"] = len(universe)
        st.session_state["scan_data_count"] = len(price_map)
        st.session_state["scan_error_count"] = len(errors)
        st.session_state["scan_unmapped_count"] = len(unmapped)
        st.session_state["scan_errors"] = errors
        st.session_state["scan_time"] = datetime.now().strftime("%d-%b-%Y %I:%M:%S %p")
        st.rerun()
    except Exception as exc:
        st.exception(exc)


if "scan_results" in st.session_state:
    results = st.session_state["scan_results"].copy()
    total_universe = st.session_state.get("scan_universe_count", 0)
    data_count = st.session_state.get("scan_data_count", 0)
    error_count = st.session_state.get("scan_error_count", 0)
    unmapped_count = st.session_state.get("scan_unmapped_count", 0)
    scan_time = st.session_state.get("scan_time", "")
    buy_count = int((results["Setup"] == "BUY").sum()) if not results.empty else 0
    sell_count = int((results["Setup"] == "SELL").sum()) if not results.empty else 0
    sweep_count = int((results["Stage"] == 2).sum()) if not results.empty else 0
    wait_sweep_count = int((results["Stage"] == 1).sum()) if not results.empty else 0

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Universe entries", f"{total_universe:,}")
    m2.metric("Data received", f"{data_count:,}")
    m3.metric("BUY setups", f"{buy_count:,}")
    m4.metric("SELL setups", f"{sell_count:,}")
    m5.metric("Wait Sweep / Entry", f"{wait_sweep_count:,} / {sweep_count:,}")
    m6.metric("Unmapped catalogue", f"{unmapped_count:,}")
    st.caption(f"Source: Yahoo Finance · Last scan: {scan_time} · Data errors / unavailable tickers: {error_count:,}")

    if results.empty:
        st.warning("चुने गए filter में कोई setup-ready symbol नहीं मिला। 'Show only setup-ready symbols' बंद करके सभी scanned symbols देखें।")
    else:
        stage_filter = st.multiselect(
            "Show stages",
            ["BUY", "SELL", "Wait Entry", "Wait Sweep", "-"],
            default=["BUY", "SELL", "Wait Entry", "Wait Sweep"],
        )
        view = results[results["Setup"].isin(stage_filter)].copy()
        preferred = [
            "Symbol", "Name", "Bias", "Setup", "LTP", "Entry", "SL", "T1 (2R)",
            "T2 (M2 H/L)", "Invalidation", "M1 High", "M1 Low", "M2 High", "M2 Low",
            "M2 Close", "Sweep Date", "Entry Date", "Last Candle",
        ]
        view = view[[c for c in preferred if c in view.columns]]
        st.dataframe(
            view,
            use_container_width=True,
            hide_index=True,
            column_config={
                "LTP": st.column_config.NumberColumn(format="₹%.2f"),
                "Entry": st.column_config.NumberColumn(format="₹%.2f"),
                "SL": st.column_config.NumberColumn(format="₹%.2f"),
                "T1 (2R)": st.column_config.NumberColumn(format="₹%.2f"),
                "T2 (M2 H/L)": st.column_config.NumberColumn(format="₹%.2f"),
                "Invalidation": st.column_config.NumberColumn(format="₹%.2f"),
            },
        )
        csv = view.to_csv(index=False).encode("utf-8-sig")
        st.download_button("⬇️ Download CSV", csv, file_name="india_crt_scan_results.csv", mime="text/csv")

    errors = st.session_state.get("scan_errors", {})
    if errors:
        with st.expander(f"Unavailable / failed tickers ({len(errors):,})"):
            error_df = pd.DataFrame([{"Symbol": key, "Reason": value} for key, value in errors.items()])
            st.dataframe(error_df, use_container_width=True, hide_index=True)
else:
    st.info("पहला scan शुरू करने के लिए **Scan market** दबाएँ।")
    st.markdown(
        "**Stage meaning**  \n"
        "- **Stage 1 – Wait Sweep:** Monthly CRT bias मौजूद है।  \n"
        "- **Stage 2 – Wait Entry:** Bias के बाद daily liquidity sweep मिल चुका है।  \n"
        "- **Stage 3 – BUY / SELL:** Sweep के बाद displacement candle ने entry condition पूरी की है।"
    )

st.divider()
st.caption(
    "Read-only technical scanner: कोई order place नहीं होता और यह investment advice नहीं है। "
    "Yahoo Finance data unofficial है; Entry/SL/Targets को broker chart पर verify करें।"
)
