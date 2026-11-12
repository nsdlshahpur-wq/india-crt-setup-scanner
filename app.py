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
st.caption("3-Month CRT: M1 liquidity range → M2 sweep/reclaim → M3 Daily CHoCH → directional FVG retest")

with st.sidebar:
    st.header("Scanner Settings")
    universe_mode = st.selectbox(
        "Market universe",
        ["All Stocks", "All Index"],
        index=0,
        help="All Stocks: NSE main-board EQ shares. BSE duplicate listings and SME scrips are excluded to keep the scan fast. All Index: only indices with a Yahoo Finance ticker mapping.",
    )
    history_period = st.selectbox("Daily history", ["1y", "2y", "3y", "5y"], index=0)
    st.divider()
    st.subheader("Strategy")
    pivot_left = st.number_input("Pivot Left", min_value=1, max_value=15, value=3)
    pivot_right = st.number_input("Pivot Right", min_value=1, max_value=15, value=3)
    entry_valid_days = st.number_input("Entry valid (daily candles)", min_value=1, max_value=10, value=3)
    only_setup = st.checkbox("Show only active, confirmed entries (target not hit)", value=False, help="बंद रखने पर Waiting CHoCH, Waiting FVG/Retest और completed setups भी दिखेंगे।")
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
def _load_universe(mode: str) -> pd.DataFrame:
    source_mode = {
        "All Stocks": "All NSE EQ stocks",
        "All Index": "All Indian indices",
    }[mode]
    return make_universe(source_mode)


if refresh:
    try:
        with st.spinner(f"Loading {universe_mode} universe..."):
            universe = _load_universe(universe_mode)
        if universe.empty:
            st.error("इस चयन के लिए कोई symbol नहीं मिला। NSE/BSE master या symbol spelling जाँचें।")
            st.stop()

        downloadable = universe[universe["Symbol"].fillna("").astype(str).str.strip().ne("")].copy()
        st.info(
            f"Selected universe में {len(downloadable):,} symbols हैं। "
            "जिन symbols का Yahoo Finance OHLC data उपलब्ध नहीं होगा, वे Data Errors में दिखेंगे."
        )
        progress = st.progress(0.0, text="Preparing data download...")
        status = st.empty()

        def update_progress(done: int, total: int, last_symbol: str):
            pct = done / max(total, 1)
            progress.progress(pct, text=f"Data download: {done:,}/{total:,}")
            status.caption(f"Last processed: {last_symbol}")

        cfg = ScanConfig(
            pivot_left=int(pivot_left),
            pivot_right=int(pivot_right),
            entry_valid_days=int(entry_valid_days),
        )

        # Keep the downloaded OHLC cache in this Streamlit session. Re-running
        # the same universe/history after changing filters or strategy settings
        # should not download thousands of candles again.
        requested_symbols = downloadable["Symbol"].drop_duplicates().tolist()
        download_key = (universe_mode, history_period, tuple(requested_symbols))
        cached_download = st.session_state.get("_market_download_cache")
        if cached_download and cached_download.get("key") == download_key:
            price_map = cached_download["price_map"]
            errors = cached_download["errors"]
            progress.progress(1.0, text=f"Reusing {len(price_map):,} cached symbols")
            status.caption("Using the previously downloaded market data in this session.")
        else:
            price_map, errors = download_market_data(
                requested_symbols,
                period=history_period,
                batch_size=80,
                progress_callback=update_progress,
            )
            st.session_state["_market_download_cache"] = {
                "key": download_key,
                "price_map": price_map,
                "errors": errors,
            }
        rows = []
        scan_progress = st.progress(0.0, text="Calculating CRT setups...")
        # Only process symbols for which OHLC data was actually downloaded.
        scan_rows = downloadable[
            downloadable["Symbol"].isin(price_map)
        ].drop_duplicates(subset=["Symbol", "Name", "Exchange"])
        total_scan_rows = max(len(scan_rows), 1)
        for i, item in enumerate(scan_rows.itertuples(index=False), start=1):
            prices = price_map[item.Symbol]
            result = scan_symbol(item.Symbol, item.Name, prices, cfg)
            if result:
                result["Exchange"] = item.Exchange
                result["Category"] = item.Category
                rows.append(result)
            scan_progress.progress(i / total_scan_rows, text=f"Scanning {i:,}/{len(scan_rows):,}")

        result_df = pd.DataFrame(rows)
        if not result_df.empty:
            stage_order = {3: 0, 2: 1, 1: 2, 4: 3, 5: 4, 6: 5, 7: 6, 0: 7}
            result_df["_order"] = result_df["Stage"].map(stage_order).fillna(8)
            result_df = result_df.sort_values(["_order", "Symbol"]).drop(columns="_order")
            # Keep every CRT stage in session state; apply display filters below.

        st.session_state["scan_results"] = result_df
        st.session_state["scan_price_map"] = price_map
        st.session_state["scan_symbol_names"] = dict(zip(scan_rows["Symbol"], scan_rows["Name"]))
        st.session_state["scan_universe_count"] = len(universe)
        st.session_state["scan_data_count"] = len(price_map)
        st.session_state["scan_error_count"] = len(errors)
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
    scan_time = st.session_state.get("scan_time", "")
    buy_count = int((results["Setup"] == "BUY").sum()) if not results.empty else 0
    sell_count = int((results["Setup"] == "SELL").sum()) if not results.empty else 0
    wait_choch_count = int((results["Stage"] == 1).sum()) if not results.empty else 0
    wait_retest_count = int((results["Setup"] == "Wait Retest").sum()) if not results.empty else 0
    wait_zone_count = int((results["Setup"] == "Wait FVG/IFVG/OB/BOB").sum()) if not results.empty else 0
    active_count = int((results["Stage"] == 3).sum()) if not results.empty else 0
    target_hit_count = int((results["Stage"] == 4).sum()) if not results.empty else 0
    stop_hit_count = int((results["Stage"] == 5).sum()) if not results.empty else 0
    target_passed_count = int((results["Stage"] == 7).sum()) if not results.empty else 0
    stop_before_entry_count = int((results["Stage"] == 8).sum()) if not results.empty else 0
    ambiguous_count = int((results["Stage"] == 6).sum()) if not results.empty else 0
    missed_entry_count = int((results["Stage"] == 9).sum()) if not results.empty else 0

    st.header("📊 Dashboard")
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Universe entries", f"{total_universe:,}")
    m2.metric("Data received", f"{data_count:,}")
    m3.metric("Waiting CHoCH", f"{wait_choch_count:,}")
    m4.metric("Waiting Zones", f"{wait_zone_count:,}")
    m5.metric("Active Entry · Target Pending", f"{active_count:,}")
    n1, n2, n3, n4, n5, n6 = st.columns(6)
    n1.metric("BUY active", f"{buy_count:,}")
    n2.metric("SELL active", f"{sell_count:,}")
    n3.metric("Target Hit", f"{target_hit_count:,}")
    n4.metric("Stop Loss Hit", f"{stop_hit_count:,}")
    n5.metric("Target Hit Before Entry", f"{target_passed_count:,}")
    n6.metric("SL Hit Before Entry / Ambiguous", f"{stop_before_entry_count + ambiguous_count:,}")
    st.metric("Missed / Stale Entry (not a fresh signal)", f"{missed_entry_count:,}")
    st.caption(f"Source: Yahoo Finance · Last scan: {scan_time} · Data errors / unavailable tickers: {error_count:,}")
    latest_daily_date = (
        pd.to_datetime(results["Last Candle"], errors="coerce").max()
        if not results.empty and "Last Candle" in results.columns else pd.NaT
    )
    latest_daily_label = (
        latest_daily_date.date().isoformat()
        if pd.notna(latest_daily_date) else "not available"
    )
    st.caption(
        f"Latest received Daily candle: {latest_daily_label} · "
        "LTP is the latest downloaded Daily close, not a live intraday quote. "
        "Compare the Last Candle date with TradingView before interpreting a setup."
    )

    if results.empty:
        st.warning("डेटा मिला, लेकिन उपलब्ध Monthly/Daily candles में अभी कोई CRT चरण नहीं पहचाना गया। Daily history 2y/3y करके फिर Scan करें।")
    else:
        stage_filter = st.multiselect(
            "Show stages",
            ["BUY", "SELL", "Missed Entry - No Fresh Entry", "Wait Retest", "Wait CHoCH", "Wait FVG/IFVG/OB/BOB", "Target Hit", "Stop Loss Hit", "Target Hit Before Entry", "Stop Loss Hit Before Entry", "Ambiguous", "No Valid Monthly Sweep"],
            default=["BUY", "SELL", "Missed Entry - No Fresh Entry", "Wait Retest", "Wait CHoCH", "Wait FVG/IFVG/OB/BOB", "Target Hit", "Stop Loss Hit", "Target Hit Before Entry", "Stop Loss Hit Before Entry", "Ambiguous", "No Valid Monthly Sweep"],
        )
        view = results[results["Setup"].isin(stage_filter)].copy()
        if only_setup:
            view = view[(view["Stage"] == 3) & view["Setup"].isin(["BUY", "SELL"])]
        preferred = [
            "Name", "Exchange", "Category", "Bias", "Setup", "LTP", "Entry", "SL", "T1 (2R)",
            "Target (M1 Monthly H/L)", "Target Status", "Entry Status", "Invalidation", "M1 High", "M1 Low", "M2 High", "M2 Low",
            "M2 Close", "M3 Month", "Sweep Type", "Sweep Date", "CHoCH Pivot Date", "CHoCH Reference Level",
            "CHoCH Date", "CHoCH Rule", "Entry Date", "Entry Confirmation Rule", "Entry Zone Type",
            "Zone Low", "Zone High", "Setup Reason", "Last Candle",
        ]
        view = view[[c for c in preferred if c in view.columns]].copy()

        # Make the displayed company/index name itself a direct TradingView link.
        # Keep Symbol in the underlying results for internal selection/chart logic only.
        def _tv_url_for_row(row):
            raw_symbol = str(row.get("Symbol", "")).strip()
            exchange = str(row.get("Exchange", "NSE")).upper()
            if raw_symbol.startswith("^"):
                index_map = {"^NSEI": "NSE:NIFTY", "^NSEBANK": "NSE:BANKNIFTY", "^BSESN": "BSE:SENSEX"}
                tv_symbol = index_map.get(raw_symbol, raw_symbol.lstrip("^"))
            elif raw_symbol.endswith(".NS"):
                tv_symbol = "NSE:" + raw_symbol[:-3]
            elif raw_symbol.endswith(".BO"):
                tv_symbol = "BSE:" + raw_symbol[:-3]
            else:
                tv_symbol = ("BSE:" if "BSE" in exchange else "NSE:") + raw_symbol
            display_name = str(row.get("Name", raw_symbol)).strip().replace(" ", "%20")
            return (
                "https://www.tradingview.com/chart/?symbol="
                + tv_symbol.replace(" ", "%20")
                + "&display="
                + display_name
            )

        view["Name"] = [
            _tv_url_for_row(row)
            for row in results.loc[view.index].to_dict("records")
        ]
        st.caption("केवल आज की latest completed Daily candle पर confirm हुआ BUY/SELL fresh signal है। पुरानी confirmation, जिसमें SL/Target अभी नहीं लगा, को Missed Entry दिखाया जाता है—उस पर नया trade न लें। Waiting CHoCH/FVG/Retest को Entry नहीं माना जाता। कंपनी के Name पर क्लिक करके TradingView chart खोलें।")
        st.dataframe(
            view,
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="setup_results_table",
            column_config={
                "Name": st.column_config.LinkColumn("Name", display_text=r".*[&?]display=([^&]+).*"),
                "LTP": st.column_config.NumberColumn(format="₹%.2f"),
                "Entry": st.column_config.NumberColumn(format="₹%.2f"),
                "SL": st.column_config.NumberColumn(format="₹%.2f"),
                "Target (M1 Monthly H/L)": st.column_config.NumberColumn(format="₹%.2f"),
                "Invalidation": st.column_config.NumberColumn(format="₹%.2f"),
            },
        )
        selected_rows_for_tv = st.session_state.get("setup_results_table", {}).get("selection", {}).get("rows", [])
        if selected_rows_for_tv:
            try:
                selected_view_index = view.index[int(selected_rows_for_tv[0])]
                selected_tv_row = results.loc[selected_view_index]
                raw_tv_symbol = str(selected_tv_row["Symbol"]).strip()
                tv_exchange = str(selected_tv_row.get("Exchange", "NSE")).upper()
                if raw_tv_symbol.startswith("^"):
                    tv_index_map = {
                        "^NSEI": "NSE:NIFTY",
                        "^NSEBANK": "NSE:BANKNIFTY",
                        "^BSESN": "BSE:SENSEX",
                    }
                    tv_symbol = tv_index_map.get(raw_tv_symbol, raw_tv_symbol.lstrip("^"))
                elif raw_tv_symbol.endswith(".NS"):
                    tv_symbol = "NSE:" + raw_tv_symbol[:-3]
                elif raw_tv_symbol.endswith(".BO"):
                    tv_symbol = "BSE:" + raw_tv_symbol[:-3]
                else:
                    tv_symbol = ("BSE:" if "BSE" in tv_exchange else "NSE:") + raw_tv_symbol
                tv_url = "https://www.tradingview.com/chart/?symbol=" + tv_symbol.replace(" ", "%20")
                st.link_button(f"📉 Open {tv_symbol} on TradingView", tv_url, type="primary")

                # Pine Script overlay for the selected setup's static CRT levels.
                def pine_level(value):
                    try:
                        number = float(value)
                        return f"{number:.6f}" if pd.notna(number) else "na"
                    except (TypeError, ValueError):
                        return "na"

                pine_lines = [
                    "//@version=5",
                    f'indicator("India CRT Levels — {raw_tv_symbol}", overlay=true)',
                    f'm1High = {pine_level(selected_tv_row.get("M1 High"))}',
                    f'm1Low = {pine_level(selected_tv_row.get("M1 Low"))}',
                    f'm2High = {pine_level(selected_tv_row.get("M2 High"))}',
                    f'm2Low = {pine_level(selected_tv_row.get("M2 Low"))}',
                    f'entryPrice = {pine_level(selected_tv_row.get("Entry"))}',
                    f'stopPrice = {pine_level(selected_tv_row.get("SL"))}',
                    f'target2R = {pine_level(selected_tv_row.get("T1 (2R)"))}',
                    f'm1Target = {pine_level(selected_tv_row.get("Target (M1 Monthly H/L)"))}',
                    'plot(m1High, "M1 High", color=color.gray, linewidth=2)',
                    'plot(m1Low, "M1 Low", color=color.gray, linewidth=2)',
                    'plot(m2High, "M2 High", color=color.blue, style=plot.style_linebr)',
                    'plot(m2Low, "M2 Low", color=color.blue, style=plot.style_linebr)',
                    'plot(entryPrice, "Entry", color=color.green, linewidth=2)',
                    'plot(stopPrice, "Stop Loss", color=color.red, linewidth=2)',
                    'plot(target2R, "Target 2R", color=color.lime, linewidth=2)',
                    'plot(m1Target, "M1 Full-Month Target", color=color.purple, linewidth=2)',
                ]
                with st.expander("🧩 TradingView पर CRT Entry / SL / Target lines लगाएँ"):
                    st.write("नीचे Pine Script copy करें, TradingView के Pine Editor में paste करके **Add to chart** दबाएँ। यह चुने हुए setup के levels दिखाएगा।")
                    st.code("\\n".join(pine_lines), language="pine")
            except (IndexError, KeyError, ValueError):
                st.info("TradingView link बनाने के लिए पहले setup row select करें।")
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
                selected_view_index = view.index[int(selected_rows[0])]
                selected_setup_symbol = str(results.loc[selected_view_index, "Symbol"])
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

        # TradingView live chart embedded directly in the scanner.
        tv_index_map = {"^NSEI": "NSE:NIFTY", "^NSEBANK": "NSE:BANKNIFTY", "^BSESN": "BSE:SENSEX"}
        if chart_symbol.startswith("^"):
            tv_chart_symbol = tv_index_map.get(chart_symbol, "NSE:" + chart_symbol.lstrip("^"))
        elif chart_symbol.endswith(".NS"):
            tv_chart_symbol = "NSE:" + chart_symbol[:-3]
        elif chart_symbol.endswith(".BO"):
            tv_chart_symbol = "BSE:" + chart_symbol[:-3]
        else:
            tv_chart_symbol = "NSE:" + chart_symbol

        st.divider()
        st.subheader("🧭 Monthly (1M) → Daily (1D) CRT")
        st.caption(
            "यह Scanner केवल Monthly liquidity context और Daily CHoCH / FVG / IFVG / OB / BOB retest "
            "पर काम करता है। Weekly, 4H, 1H या intraday entry timeframe इस strategy में उपयोग नहीं होते।"
        )

        # Keep the original in-app Plotly CRT/indicator chart; TradingView opens directly via links above.
        chart_data = price_map.get(chart_symbol)
        if chart_data is not None and not chart_data.empty:
            chart_data = chart_data.copy()
            if isinstance(chart_data.columns, pd.MultiIndex):
                chart_data.columns = [str(c[-1] if str(c[-1]).lower() in {"open", "high", "low", "close", "volume"} else c[0]).title() for c in chart_data.columns]
            chart_data.columns = [str(c).title() for c in chart_data.columns]
            required_chart_cols = ["Open", "High", "Low", "Close"]
            if all(col in chart_data.columns for col in required_chart_cols):
                chart_data = chart_data.dropna(subset=required_chart_cols).tail(250)
                fig = go.Figure(
                    data=[
                        go.Candlestick(
                            x=chart_data.index,
                            open=chart_data["Open"],
                            high=chart_data["High"],
                            low=chart_data["Low"],
                            close=chart_data["Close"],
                            name=chart_symbol,
                        )
                    ]
                )
                match = results[results["Symbol"] == chart_symbol] if not results.empty else pd.DataFrame()
                if not match.empty:
                    setup_row = match.iloc[0]
                    with st.expander("🧠 यह CRT Setup क्यों बना?"):
                        st.write(f"**Monthly Status:** {setup_row.get('Monthly Status', 'N/A')}")
                        st.write(f"**Liquidity Sweep:** {setup_row.get('Sweep Type', 'N/A')} · {setup_row.get('Sweep Date', 'N/A')}")
                        st.write(f"**CHoCH:** {setup_row.get('CHoCH Rule', 'N/A')} · {setup_row.get('CHoCH Date', 'N/A')}")
                        st.write(f"**Entry Logic:** {setup_row.get('Entry Confirmation Rule', 'N/A')}")
                        st.write(f"**Reason:** {setup_row.get('Setup Reason', 'N/A')}")
                        st.caption("यह नियम-आधारित OHLC व्याख्या है; TradingView के discretionary markings से हर स्थिति में समान होना जरूरी नहीं।")
                    levels = [
                        ("M1 High", setup_row.get("M1 High"), "gray", "dash"),
                        ("M1 Low", setup_row.get("M1 Low"), "gray", "dash"),
                        ("M2 High", setup_row.get("M2 High"), "royalblue", "dot"),
                        ("M2 Low", setup_row.get("M2 Low"), "royalblue", "dot"),
                        ("Daily CHoCH Reference", setup_row.get("CHoCH Reference Level"), "orange", "dot"),
                        ("Entry", setup_row.get("Entry"), "green", "solid"),
                        ("Stop Loss", setup_row.get("SL"), "red", "solid"),
                        ("Opposite M1 Liquidity Target", setup_row.get("Target (M1 Monthly H/L)"), "purple", "dash"),
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
                    # CRT structure markers: liquidity sweep, CHoCH and the selected retest zone.
                    direction_label = str(setup_row.get("Bias", ""))
                    sweep_date_value = setup_row.get("Sweep Date")
                    sweep_price_value = (
                        setup_row.get("Sweep Candle Low")
                        if direction_label == "Bullish"
                        else setup_row.get("Sweep Candle High")
                    )
                    if pd.notna(sweep_date_value) and pd.notna(sweep_price_value):
                        sweep_x = pd.to_datetime(sweep_date_value)
                        sweep_label = "SSS · Sell-Side Sweep" if direction_label == "Bullish" else "BSL · Buy-Side Sweep"
                        fig.add_trace(go.Scatter(
                            x=[sweep_x], y=[float(sweep_price_value)],
                            mode="markers+text",
                            text=[sweep_label], textposition="bottom center",
                            marker=dict(symbol="triangle-up" if direction_label == "Bullish" else "triangle-down", size=13, color="#16a34a" if direction_label == "Bullish" else "#dc2626"),
                            name="Liquidity Sweep",
                            hovertemplate="%{text}<br>%{x|%d %b %Y}<br>Price: %{y:.2f}<extra></extra>",
                        ))
                        fig.add_vline(x=sweep_x, line_dash="dot", line_color="#16a34a" if direction_label == "Bullish" else "#dc2626", opacity=0.55)

                    choch_date_value = setup_row.get("CHoCH Date")
                    choch_level_value = setup_row.get("CHoCH Reference Level")
                    if pd.notna(choch_date_value) and pd.notna(choch_level_value):
                        choch_x = pd.to_datetime(choch_date_value)
                        fig.add_trace(go.Scatter(
                            x=[choch_x], y=[float(choch_level_value)],
                            mode="markers+text",
                            text=["CHoCH"], textposition="top center",
                            marker=dict(symbol="diamond", size=11, color="#0891b2"),
                            name="Daily CHoCH",
                            hovertemplate="CHoCH<br>%{x|%d %b %Y}<br>Break level: %{y:.2f}<extra></extra>",
                        ))
                        fig.add_vline(x=choch_x, line_dash="dash", line_color="#0891b2", opacity=0.45)

                    zone_low = setup_row.get("Zone Low")
                    zone_high = setup_row.get("Zone High")
                    if pd.notna(zone_low) and pd.notna(zone_high):
                        zone_type = str(setup_row.get("Entry Zone Type", "Entry Zone"))
                        zone_label = "Advance OB" if zone_type == "OB" else ("Breaker OB" if zone_type == "BOB" else f"{zone_type} Retest Zone")
                        fig.add_hrect(
                            y0=float(zone_low),
                            y1=float(zone_high),
                            opacity=0.20,
                            fillcolor="#22c55e" if direction_label == "Bullish" else "#ef4444",
                            line_width=1,
                            line_color="#16a34a" if direction_label == "Bullish" else "#dc2626",
                            annotation_text=f"{zone_label}: {float(zone_low):.2f}–{float(zone_high):.2f}",
                            annotation_position="top left",
                        )
                    st.caption(
                        f"Bias: {setup_row.get('Bias', '-')} · Setup: {setup_row.get('Setup', '-')} · "
                        f"CHoCH ref: {setup_row.get('CHoCH Reference Level', '-')} "
                        f"(pivot {setup_row.get('CHoCH Pivot Date', '-')}) · "
                        f"Zone: {setup_row.get('Entry Zone Type', '-')} · "
                        f"Target: {setup_row.get('Target Status', '-')} · "
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
        "**Strategy flow**  \n"
        "- **M1 / M2:** Monthly range, one-side liquidity sweep और full-range reclaim.  \n"
        "- **Daily:** CHoCH के बाद FVG / IFVG / OB / BOB में से किसी एक का retest.  \n"
        "- **Entry:** Retest के बाद उसी दिशा में confirming Daily close.  \n"
        "- **Active:** Sweep-candle SL और opposite M1 liquidity target बाकी."
    )

st.divider()
st.caption(
    "Read-only technical scanner: कोई order place नहीं होता और यह investment advice नहीं है। "
    "Yahoo Finance data unofficial है; Entry/SL/Targets को broker chart पर verify करें।"
)
