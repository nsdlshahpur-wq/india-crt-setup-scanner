from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data_fetch import download_market_data
from scanner import ScanConfig, scan_symbol
from universe import make_universe

st.set_page_config(page_title="India CRT Setup Scanner", page_icon="📈", layout="wide")
st.title("🇮🇳 India CRT Setup Scanner")
st.caption("3-Month CRT: M1 range → M2 sweep/reclaim → M3 Daily CHoCH → FVG + IFVG + OB retest")

with st.sidebar:
    st.header("Scanner Settings")
    universe_mode = st.selectbox(
        "Market universe",
        [
            "All NSE + BSE stocks + all indices",
            "All India stocks + indices",
            "All NSE + BSE stocks",
            "All NSE EQ + SME stocks",
            "All NSE + BSE stocks + SME",
            "All NSE EQ stocks",
            "All BSE EQ stocks",
            "All Indian indices",
            "Custom symbols",
        ],
        index=0,
        help="Loads NSE EQ and SME stocks, BSE equity scrips and the Nifty equity-index catalogue. Only verified Yahoo tickers can be downloaded; unmapped indices are listed separately.",
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
        with st.spinner("Loading NSE, SME, BSE and index universes..."):
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
        st.session_state["scan_price_map"] = price_map
        st.session_state["scan_symbol_names"] = dict(zip(scan_rows["Symbol"], scan_rows["Name"]))
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

    st.header("📊 Dashboard")
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
            ["BUY", "SELL", "Wait Retest", "Wait CHoCH", "-"],
            default=["BUY", "SELL", "Wait Retest", "Wait CHoCH"],
        )
        view = results[results["Setup"].isin(stage_filter)].copy()
        preferred = [
            "Symbol", "Name", "Exchange", "Category", "Bias", "Setup", "LTP", "Entry", "SL", "T1 (2R)",
            "Target (M1 Monthly H/L)", "Invalidation", "M1 High", "M1 Low", "M2 High", "M2 Low",
            "M2 Close", "M3 Month", "Sweep Date", "CHoCH Date", "Entry Date", "Zone Low", "Zone High", "Last Candle",
        ]
        view = view[[c for c in preferred if c in view.columns]]
        st.caption("BUY / SELL या किसी setup की row पर क्लिक करें—नीचे उसी शेयर का CRT chart और setup levels खुलेंगे।")
        st.dataframe(
            view,
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="setup_results_table",
            column_config={
                "LTP": st.column_config.NumberColumn(format="₹%.2f"),
                "Entry": st.column_config.NumberColumn(format="₹%.2f"),
                "SL": st.column_config.NumberColumn(format="₹%.2f"),
                "T1 (2R)": st.column_config.NumberColumn(format="₹%.2f"),
                "Target (M1 Monthly H/L)": st.column_config.NumberColumn(format="₹%.2f"),
                "Invalidation": st.column_config.NumberColumn(format="₹%.2f"),
            },
        )
        csv = view.to_csv(index=False).encode("utf-8-sig")
        st.download_button("⬇️ Download CSV", csv, file_name="india_crt_scan_results.csv", mime="text/csv")

    # Interactive CRT chart: uses the same daily OHLC data as the scanner.
    price_map = st.session_state.get("scan_price_map", {})
    if price_map:
        st.divider()
        st.subheader("📊 CRT Chart + Setup Levels")
        chart_symbols = sorted(price_map.keys())
        symbol_names = st.session_state.get("scan_symbol_names", {})
        # Selecting a row in the scan table opens that symbol's chart below.
        selected_rows = st.session_state.get("setup_results_table", {}).get("selection", {}).get("rows", [])
        selected_setup_symbol = None
        if selected_rows and not results.empty:
            try:
                selected_setup_symbol = str(view.iloc[int(selected_rows[0])]["Symbol"])
            except (IndexError, KeyError, ValueError):
                selected_setup_symbol = None
        preferred_chart_symbol = selected_setup_symbol if selected_setup_symbol in chart_symbols else chart_symbols[0]
        chart_symbol = st.selectbox(
            "Chart के लिए शेयर / Index चुनें",
            chart_symbols,
            index=chart_symbols.index(preferred_chart_symbol),
            format_func=lambda symbol: f"{symbol} — {symbol_names.get(symbol, '')}",
            key="crt_chart_symbol",
        )
        chart_data = price_map.get(chart_symbol)
        if chart_data is not None and not chart_data.empty:
            chart_data = chart_data.copy()
            if isinstance(chart_data.columns, pd.MultiIndex):
                chart_data.columns = [str(c[-1] if str(c[-1]).lower() in {"open", "high", "low", "close", "volume"} else c[0]).title() for c in chart_data.columns]
            chart_data.columns = [str(c).title() for c in chart_data.columns]
            required_chart_cols = ["Open", "High", "Low", "Close"]
            if all(col in chart_data.columns for col in required_chart_cols):
                chart_data = chart_data.dropna(subset=required_chart_cols).tail(250)
                # Indicator overlays for the price chart
                chart_data["EMA 20"] = chart_data["Close"].ewm(span=20, adjust=False).mean()
                chart_data["EMA 50"] = chart_data["Close"].ewm(span=50, adjust=False).mean()
                fig = go.Figure(
                    data=[
                        go.Candlestick(
                            x=chart_data.index,
                            open=chart_data["Open"],
                            high=chart_data["High"],
                            low=chart_data["Low"],
                            close=chart_data["Close"],
                            name=chart_symbol,
                        ),
                        go.Scatter(x=chart_data.index, y=chart_data["EMA 20"], name="EMA 20", line=dict(width=1.5)),
                        go.Scatter(x=chart_data.index, y=chart_data["EMA 50"], name="EMA 50", line=dict(width=1.5)),
                    ]
                )
                match = results[results["Symbol"] == chart_symbol] if not results.empty else pd.DataFrame()
                if not match.empty:
                    setup_row = match.iloc[0]
                    levels = [
                        ("M1 High", setup_row.get("M1 High"), "gray", "dash"),
                        ("M1 Low", setup_row.get("M1 Low"), "gray", "dash"),
                        ("M2 High", setup_row.get("M2 High"), "royalblue", "dot"),
                        ("M2 Low", setup_row.get("M2 Low"), "royalblue", "dot"),
                        ("Entry", setup_row.get("Entry"), "green", "solid"),
                        ("Stop Loss", setup_row.get("SL"), "red", "solid"),
                        ("Target 1", setup_row.get("T1 (2R)"), "green", "dash"),
                        ("M1 Full-Month Target", setup_row.get("Target (M1 Monthly H/L)"), "purple", "dash"),
                    ]
                    for label, value, color, dash in levels:
                        if pd.notna(value) and isinstance(value, (int, float)) and value > 0:
                            fig.add_hline(
                                y=float(value),
                                line_color=color,
                                line_dash=dash,
                                annotation_text=f"{label}: {float(value):.2f}",
                                annotation_position="right",
                            )
                    st.caption(
                        f"Bias: {setup_row.get('Bias', '-')} · Setup: {setup_row.get('Setup', '-')} · "
                        f"Last candle: {setup_row.get('Last Candle', '-')}"
                    )
                fig.update_layout(
                    title=f"{chart_symbol} — Daily Candlestick (last 250 candles)",
                    xaxis_title="Date",
                    yaxis_title="Price",
                    xaxis_rangeslider_visible=False,
                    height=620,
                    template="plotly_white",
                    margin=dict(l=20, r=30, t=60, b=20),
                    legend=dict(orientation="h"),
                )
                st.plotly_chart(fig, use_container_width=True)

                # Dedicated technical-indicator section, based on selected symbol's daily candles
                st.divider()
                st.header("📈 Indicator Section")
                close = chart_data["Close"].astype(float)
                delta = close.diff()
                gain = delta.clip(lower=0).ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
                loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
                rs = gain / loss.replace(0, float("nan"))
                chart_data["RSI 14"] = 100 - (100 / (1 + rs))
                prev_close = close.shift(1)
                true_range = pd.concat(
                    [chart_data["High"] - chart_data["Low"],
                     (chart_data["High"] - prev_close).abs(),
                     (chart_data["Low"] - prev_close).abs()], axis=1
                ).max(axis=1)
                chart_data["ATR 14"] = true_range.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
                ema12 = close.ewm(span=12, adjust=False).mean()
                ema26 = close.ewm(span=26, adjust=False).mean()
                chart_data["MACD"] = ema12 - ema26
                chart_data["MACD Signal"] = chart_data["MACD"].ewm(span=9, adjust=False).mean()
                chart_data["MACD Histogram"] = chart_data["MACD"] - chart_data["MACD Signal"]

                last = chart_data.iloc[-1]
                ind1, ind2, ind3, ind4 = st.columns(4)
                ind1.metric("RSI (14)", f"{last['RSI 14']:.2f}" if pd.notna(last["RSI 14"]) else "N/A")
                ind2.metric("ATR (14)", f"₹{last['ATR 14']:.2f}" if pd.notna(last["ATR 14"]) else "N/A")
                ind3.metric("EMA 20", f"₹{last['EMA 20']:.2f}")
                ind4.metric("EMA 50", f"₹{last['EMA 50']:.2f}")

                indicator_fig = go.Figure()
                indicator_fig.add_trace(go.Scatter(x=chart_data.index, y=chart_data["RSI 14"], name="RSI 14"))
                indicator_fig.add_hline(y=70, line_dash="dash", annotation_text="Overbought 70")
                indicator_fig.add_hline(y=30, line_dash="dash", annotation_text="Oversold 30")
                indicator_fig.update_layout(
                    title=f"{chart_symbol} — RSI (14)", yaxis_title="RSI", yaxis_range=[0, 100],
                    height=300, template="plotly_white", xaxis_rangeslider_visible=False,
                )
                st.plotly_chart(indicator_fig, use_container_width=True)

                macd_fig = go.Figure()
                macd_fig.add_trace(go.Scatter(x=chart_data.index, y=chart_data["MACD"], name="MACD"))
                macd_fig.add_trace(go.Scatter(x=chart_data.index, y=chart_data["MACD Signal"], name="Signal"))
                macd_fig.add_trace(go.Bar(x=chart_data.index, y=chart_data["MACD Histogram"], name="Histogram"))
                macd_fig.update_layout(
                    title=f"{chart_symbol} — MACD (12, 26, 9)", height=320,
                    template="plotly_white", xaxis_rangeslider_visible=False,
                )
                st.plotly_chart(macd_fig, use_container_width=True)
            else:
                st.warning("इस symbol के लिए OHLC chart columns उपलब्ध नहीं हैं।")

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
