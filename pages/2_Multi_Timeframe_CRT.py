"""Standalone selected-pair CRT scanner using the correct Yahoo timeframe intervals."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from mtf_scanner import TIMEFRAME_PAIRS, analyze_timeframe_pair
from universe import make_universe

st.set_page_config(page_title="Multi-Timeframe CRT Scanner", page_icon="🧭", layout="wide")
st.title("🧭 Multi-Timeframe CRT Scanner")
st.caption(
    "Selected CRT timeframe is analyzed with its matching entry timeframe. "
    "Only completed candles are considered; intraday availability depends on Yahoo Finance history limits."
)

with st.sidebar:
    st.header("Multi-TF settings")
    universe_mode = st.selectbox(
        "Market universe",
        ["All Stocks", "All Index"],
        index=0,
        key="mtf_universe",
        help="All Stocks: NSE main-board EQ shares. BSE duplicate listings and SME scrips are excluded for faster scans. All Index: only indices with a Yahoo Finance ticker mapping.",
    )
    crt_timeframe = st.selectbox(
        "CRT context timeframe",
        list(TIMEFRAME_PAIRS),
        index=0,
        key="mtf_crt_context_tf",
    )
    entry_options = ["Daily", "4H", "30m", "5m", "1m"]
    default_entry = TIMEFRAME_PAIRS[crt_timeframe]
    execution_timeframe = st.selectbox(
        "Entry timeframe",
        entry_options,
        index=entry_options.index(default_entry),
        key="mtf_entry_tf",
        help="Default pair: Monthly→Daily, Weekly→4H, Daily→30m, 4H→5m, 1H→1m. You may select another supported entry timeframe.",
    )
    st.caption(
        "Yahoo Finance history limits vary by interval: 1m is very short-term, "
        "5m/30m are limited, while Daily and higher timeframes offer longer history."
    )

if st.button("🔎 Scan Multi-Timeframe CRT", type="primary"):
    try:
        with st.spinner("Preparing symbols..."):
            source_mode = {
                "All Stocks": "All NSE EQ stocks",
                "All Index": "All Indian indices",
            }[universe_mode]
            universe = make_universe(source_mode)
            universe = universe[
                universe["Symbol"].fillna("").astype(str).str.strip().ne("")
            ].drop_duplicates("Symbol")

        if universe.empty:
            st.error("इस चयन में कोई वैध symbol नहीं मिला। Symbol spelling जाँचें।")
            st.stop()

        symbols = list(universe.itertuples(index=False))
        rows: list[dict] = []
        errors: dict[str, str] = {}
        progress = st.progress(0.0, text="Downloading selected timeframe candles...")
        status = st.empty()

        for i, item in enumerate(symbols, start=1):
            row, symbol_errors = analyze_timeframe_pair(
                str(item.Symbol),
                crt_timeframe,
                execution_timeframe,
            )
            row["Name"] = item.Name
            row["Exchange"] = item.Exchange
            row["CRT Context TF"] = crt_timeframe
            row["Entry TF"] = execution_timeframe
            rows.append(row)

            for timeframe, reason in symbol_errors.items():
                errors[f"{item.Symbol} | {timeframe}"] = reason

            progress.progress(
                i / max(len(symbols), 1),
                text=f"Scanned {i:,}/{len(symbols):,} symbols",
            )
            status.caption(f"Last processed: {item.Symbol}")

        result_df = pd.DataFrame(rows)
        st.session_state["mtf_results"] = result_df
        st.session_state["mtf_errors"] = errors
        st.session_state["mtf_scan_at"] = pd.Timestamp.now().strftime("%d-%b-%Y %I:%M %p")
        st.session_state["mtf_pair"] = f"{crt_timeframe} CRT → {execution_timeframe} Entry"
    except Exception as exc:
        st.exception(exc)

if "mtf_results" in st.session_state:
    result_df = st.session_state["mtf_results"].copy()
    valid_count = int(result_df["CRT Status"].isin(["VALID - WAIT ENTRY", "ENTRY READY"]).sum()) if not result_df.empty else 0
    ready_count = int((result_df["CRT Status"] == "ENTRY READY").sum()) if not result_df.empty else 0
    no_data_count = int((result_df["CRT Status"] == "NO DATA").sum()) if not result_df.empty else 0

    a, b, c = st.columns(3)
    a.metric("Valid CRT", valid_count)
    b.metric("Entry Ready", ready_count)
    c.metric("No Data", no_data_count)
    st.caption(
        f"Pair: {st.session_state.get('mtf_pair', '')} · "
        f"Last scan: {st.session_state.get('mtf_scan_at', '')}"
    )

    if result_df.empty:
        st.info("इस scan में कोई परिणाम नहीं मिला।")
    else:
        statuses = sorted(result_df["CRT Status"].dropna().unique().tolist())
        selected_status = st.multiselect(
            "CRT status",
            statuses,
            default=statuses,
        )
        bias_options = ["Bullish", "Bearish", "Neutral"]
        selected_bias = st.multiselect(
            "HTF bias",
            bias_options,
            default=bias_options,
        )
        view = result_df[
            result_df["CRT Status"].isin(selected_status)
            & result_df["HTF Bias"].isin(selected_bias)
        ].copy()
        preferred = [
            "Symbol", "Name", "Exchange", "CRT Context TF", "Entry TF",
            "CRT Status", "CRT Mark", "HTF Bias", "Liquidity Sweep",
            "Structure / CHoCH", "Retest Price", "CRT Range High",
            "CRT Range Low", "Zone Low", "Zone High", "Entry", "SL",
            "Target", "CRT Candle", "Entry Candle", "Data Note",
        ]
        view = view[[column for column in preferred if column in view.columns]]
        st.dataframe(view, use_container_width=True, hide_index=True)
        st.download_button(
            "⬇️ Download CSV",
            view.to_csv(index=False).encode("utf-8-sig"),
            "multi_timeframe_crt.csv",
            "text/csv",
        )

    errors = st.session_state.get("mtf_errors", {})
    if errors:
        with st.expander(f"Unavailable data ({len(errors)})"):
            st.dataframe(
                pd.DataFrame([{"Symbol / Timeframe": key, "Reason": value} for key, value in errors.items()]),
                use_container_width=True,
                hide_index=True,
            )
else:
    st.info("Settings चुनकर **Scan Multi-Timeframe CRT** दबाएँ। यह page selected CRT और entry timeframe के वास्तविक candle intervals से analysis करता है।")
