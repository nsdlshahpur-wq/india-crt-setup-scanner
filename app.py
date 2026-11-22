from __future__ import annotations

from datetime import datetime
from urllib.parse import quote
import time
import json
import sys
import subprocess
import tempfile
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

from data_fetch import download_market_data
from scanner import ScanConfig, scan_symbol
from backtest import BacktestConfig, run_backtest
from universe import make_universe
from mtf_analysis import analyze_mtf_symbol
from multi_symbol_scanner import scan_symbols

st.set_page_config(page_title="India CRT Setup Scanner", page_icon="📈", layout="wide")
st.title("🇮🇳 India CRT Setup Scanner")
st.caption("3-Month CRT: M1 liquidity range → M2 sweep/reclaim → M3 Daily CHoCH → directional FVG retest")

with st.sidebar:
    st.header("Scanner Settings")
    universe_mode = st.selectbox(
        "Market universe",
        ["All India stocks + indices", "All Stocks", "All Index"],
        index=0,
        help="All India stocks + indices: NSE EQ/SME + BSE listed equities and mapped Indian indices. All Stocks: NSE EQ only. All Index: mapped indices only. Large scans can take several minutes and some Yahoo tickers may be unavailable.",
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

scanner_tab, backtest_tab, mtf_tab, screener_tab, scanner50_tab = st.tabs(["📊 Dashboard", "📈 Backtest", "🧭 CRT MTF Analysis", "🔎 Multi-Symbol Screener", "🚀 Scanner 5.0"]) 

with scanner_tab:
    col_a, col_b = st.columns([1, 4])
    with col_a:
        refresh = st.button("🔄 Scan market", type="primary", use_container_width=True)
    with col_b:
        st.caption("Daily strategy checks completed candles. For the cleanest daily scan, run after the NSE cash-market close.")
    
    
    @st.cache_data(ttl=1800, show_spinner=False)
    def _load_universe(mode: str) -> pd.DataFrame:
        source_mode = {
            "All India stocks + indices": "All India stocks + indices",
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
                        st.code("\n".join(pine_lines), language="pine")
                except (IndexError, KeyError, ValueError):
                    st.info("TradingView link बनाने के लिए पहले setup row select करें।")
            csv = view.to_csv(index=False).encode("utf-8-sig")
            st.download_button("⬇️ Download CSV", csv, file_name="india_crt_scan_results.csv", mime="text/csv")
    
        # Interactive CRT chart: uses the same daily OHLC data as the scanner.
        price_map = st.session_state.get("scan_price_map", {})
        if price_map:
            st.divider()
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
            st.subheader("📈 TradingView Advanced Chart")
            st.caption(
                f"{tv_chart_symbol} · Daily timeframe · TradingView chart widget. "
                "Chart quotes and the scanner's Yahoo Finance Daily data may differ."
            )
            # Official TradingView Advanced Chart widget embedded in the app.
            import json
            tv_widget_symbol = json.dumps(tv_chart_symbol)
            tv_widget_html = f"""
            <div class="tradingview-widget-container" style="height:620px;width:100%">
              <div id="tradingview_crt_chart" style="height:580px;width:100%"></div>
              <div class="tradingview-widget-copyright">
                <a href="https://www.tradingview.com/" rel="noopener nofollow" target="_blank">
                  <span>View chart on TradingView</span>
                </a>
              </div>
              <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
              <script type="text/javascript">
                new TradingView.widget({{
                  "autosize": true,
                  "symbol": {tv_widget_symbol},
                  "interval": "D",
                  "timezone": "Asia/Kolkata",
                  "theme": "light",
                  "style": "1",
                  "locale": "en",
                  "enable_publishing": false,
                  "allow_symbol_change": true,
                  "calendar": false,
                  "support_host": "https://www.tradingview.com"
                }});
              </script>
            </div>
            """
            components.html(tv_widget_html, height=630, scrolling=False)

            # Keep the original Plotly CRT/indicator chart below the TradingView widget.
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
    

with backtest_tab:
     st.subheader("📈 Historical CRT Backtest")
     st.caption("All India stock + mapped index universe · 5 years of Yahoo Finance Daily OHLC · Existing Monthly-Daily CRT rules unchanged.")
     st.info(
         "No-look-ahead पद्धति: हर ऐतिहासिक तारीख पर scanner को केवल उस तारीख तक की candles दी जाती हैं। "
         "Entry confirmation के बाद की candles ही SL/Target exit जाँचने में उपयोग होती हैं। "
         "पहले 80 daily bars warm-up हैं; इसलिए उपलब्ध 5-year data में effective test start कुछ महीने बाद होगा।"
     )
     b1, b2, b3, b4 = st.columns(4)
     with b1:
         bt_capital = st.number_input("Starting Capital (₹)", min_value=10000.0, value=100000.0, step=10000.0, key="bt_capital")
     with b2:
         bt_risk = st.number_input("Risk per trade (%)", min_value=0.1, max_value=5.0, value=1.0, step=0.1, key="bt_risk")
     with b3:
         bt_charges = st.number_input("Transaction charges (bps / side)", min_value=0.0, max_value=100.0, value=12.0, step=1.0, key="bt_charges",
             help="Estimated all-in charge per side. Actual BSE, STT, stamp duty, GST and broker charges vary.")
     with b4:
         bt_slippage = st.number_input("Slippage (bps / side)", min_value=0.0, max_value=100.0, value=5.0, step=1.0, key="bt_slippage")
     st.caption("Default cost assumption: 12 bps charges + 5 bps slippage on each side. Adjust these to your broker and execution conditions.")
     run_bt = st.button("▶️ Run 5-Year Full-Market Backtest", type="primary", key="run_bse_backtest")
     if run_bt:
         try:
             with st.spinner("All India stock + index universe लोड हो रहा है..."):
                 bse_universe = make_universe("All India stocks + indices")
             bse_universe = bse_universe[
                 bse_universe["Symbol"].fillna("").astype(str).str.strip().ne("")
             ].drop_duplicates(subset=["Symbol"]).copy()
             if bse_universe.empty:
                 st.error("All India stock/index universe उपलब्ध नहीं है। NSE/BSE security masters जाँचें।")
                 st.stop()
             st.write(f"Current India stock/index symbols in exchange masters: **{len(bse_universe):,}**")
             bt_progress = st.progress(0.0, text="Downloading 5-year daily OHLC...")
             bt_status = st.empty()
             symbols = bse_universe["Symbol"].tolist()
             bt_cache_key = ("ALL_INDIA_STOCKS_INDICES", "5y", tuple(symbols))
             cached = st.session_state.get("_bse_backtest_data")
             if cached and cached.get("key") == bt_cache_key:
                 bt_prices, bt_errors = cached["prices"], cached["errors"]
                 bt_progress.progress(1.0, text=f"Using cached data for {len(bt_prices):,} symbols")
             else:
                 def bt_download_progress(done, total, last_symbol):
                     bt_progress.progress(done / max(total, 1), text=f"OHLC download: {done:,}/{total:,}")
                     bt_status.caption(f"Last batch symbol: {last_symbol}")
                 bt_prices, bt_errors = download_market_data(
                     symbols, period="5y", batch_size=80, progress_callback=bt_download_progress
                 )
                 st.session_state["_all_india_backtest_data"] = {
                     "key": bt_cache_key, "prices": bt_prices, "errors": bt_errors
                 }
             if not bt_prices:
                 st.error("Yahoo Finance से कोई India market OHLC data नहीं मिला।")
                 st.stop()
             st.info(f"Historical OHLC received for **{len(bt_prices):,}** symbols. अब daily as-of CRT simulation चल रहा है।")
             sim_progress = st.progress(0.0, text="Running no-look-ahead simulation...")
             sim_status = st.empty()
             def bt_scan_progress(done, total, last_symbol):
                 sim_progress.progress(done / max(total, 1), text=f"Historical simulation: {done:,}/{total:,} symbols")
                 sim_status.caption(f"Last processed: {last_symbol}")
             name_map = dict(zip(bse_universe["Symbol"], bse_universe["Name"]))
             scan_cfg = ScanConfig(
                 pivot_left=int(pivot_left), pivot_right=int(pivot_right),
                 entry_valid_days=int(entry_valid_days)
             )
             bt_result = run_backtest(
                 bt_prices, names=name_map,
                 config=BacktestConfig(
                     initial_capital=float(bt_capital), risk_pct=float(bt_risk),
                     charges_bps_per_side=float(bt_charges),
                     slippage_bps_per_side=float(bt_slippage)
                 ),
                 scan_config=scan_cfg,
                 progress_callback=bt_scan_progress
             )
             st.session_state["bse_backtest_result"] = bt_result
             st.session_state["bse_backtest_meta"] = {
                 "universe_count": len(bse_universe), "data_count": len(bt_prices),
                 "download_errors": len(bt_errors),
                 "scan_settings": (int(pivot_left), int(pivot_right), int(entry_valid_days)),
             }
             st.rerun()
         except Exception as exc:
             st.exception(exc)

     if "bse_backtest_result" in st.session_state:
         bt = st.session_state["bse_backtest_result"]
         meta = st.session_state.get("bse_backtest_meta", {})
         metrics = bt["metrics"]
         trades = bt["trades"]
         curve = bt["equity_curve"]
         st.divider()
         st.caption(
             f"Universe: {meta.get('universe_count', 0):,} current India stock/index listings · "
             f"Data received: {meta.get('data_count', 0):,} · "
             f"Download errors: {meta.get('download_errors', 0):,} · "
             f"Candidates found: {bt.get('candidate_count', 0):,}"
         )
         if not trades.empty:
             first_entry = pd.to_datetime(trades["Entry Date"], errors="coerce").min()
             last_exit = pd.to_datetime(trades["Exit Date"], errors="coerce").max()
             st.caption(f"Effective trade window: {first_entry.date() if pd.notna(first_entry) else '—'} to {last_exit.date() if pd.notna(last_exit) else '—'}")
         m = st.columns(5)
         m[0].metric("Total trades", f"{metrics['total_trades']:,}")
         m[1].metric("Win rate", f"{metrics['win_rate']:.2f}%")
         m[2].metric("Profit factor", "∞" if metrics["profit_factor"] == float("inf") else f"{metrics['profit_factor']:.2f}")
         m[3].metric("Net P&L", f"₹{metrics['net_pnl']:,.0f}")
         m[4].metric("Max drawdown", f"{metrics['max_drawdown_pct']:.2f}%")
         n = st.columns(5)
         n[0].metric("Wins", f"{metrics['wins']:,}")
         n[1].metric("Losses", f"{metrics['losses']:,}")
         n[2].metric("Ambiguous", f"{metrics['ambiguous']:,}")
         n[3].metric("Open / end-of-data", f"{metrics['open']:,}")
         n[4].metric("Total charges", f"₹{metrics.get('total_charges', 0):,.0f}")
         st.metric("Ending equity (incl. end-of-data marked trades)", f"₹{metrics['ending_equity']:,.0f}",
                   delta=f"{metrics['net_return_pct']:.2f}% net return")
         st.caption("Win rate = wins ÷ (wins + losses); ambiguous/open trades are shown separately. Ambiguous same-day SL/target candles are conservatively priced at SL and excluded from win-rate denominator.")
         if not curve.empty:
             equity_fig = go.Figure()
             equity_fig.add_trace(go.Scatter(x=curve["Date"], y=curve["Equity"], mode="lines", name="Portfolio equity"))
             equity_fig.update_layout(title="Realised portfolio equity curve", xaxis_title="Date", yaxis_title="Equity (₹)",
                                      height=380, template="plotly_white")
             st.plotly_chart(equity_fig, use_container_width=True)
             dd_fig = go.Figure()
             dd_fig.add_trace(go.Scatter(x=curve["Date"], y=curve["Drawdown %"], mode="lines", name="Drawdown %", fill="tozeroy"))
             dd_fig.update_layout(title="Closed-trade drawdown", xaxis_title="Date", yaxis_title="Drawdown (%)",
                                  height=300, template="plotly_white")
             st.plotly_chart(dd_fig, use_container_width=True)
         if trades.empty:
             st.warning("इस अवधि और उपलब्ध India-market symbols में कोई qualifying CRT entry नहीं मिली।")
         else:
             display_cols = [
                 "Symbol", "Name", "Direction", "Entry Date", "Entry Fill", "Stop Loss", "Target",
                 "Exit Date", "Exit Fill", "Outcome", "Quantity", "Gross P&L", "Charges",
                 "Net P&L", "R Multiple", "Entry Zone", "Bars Held"
             ]
             st.subheader("Trade History")
             st.dataframe(trades[[c for c in display_cols if c in trades.columns]],
                          use_container_width=True, hide_index=True)
             st.download_button(
                 "⬇️ Download trade history CSV",
                 trades.to_csv(index=False).encode("utf-8-sig"),
                 file_name="india_full_market_crt_backtest_trades.csv", mime="text/csv"
             )
         if bt["errors"]:
             with st.expander(f"Backtest data / symbol errors ({len(bt['errors']):,})"):
                 err_df = pd.DataFrame([{"Symbol": s, "Reason": e} for s, e in bt["errors"].items()])
                 st.dataframe(err_df, use_container_width=True, hide_index=True)
         st.warning(
             "महत्वपूर्ण सीमाएँ: universe आज के NSE/BSE exchange masters और mapped indices पर आधारित है, इसलिए delisted stocks और historical constituent changes शामिल नहीं हैं (survivorship bias). "
             "Yahoo Finance का कुछ NSE/BSE stock और index data अधूरा/adjusted/अनुपलब्ध हो सकता है। Charges अनुमानित bps हैं, वास्तविक contract-note taxes नहीं। "
             "Equity curve realised exits पर आधारित है; intraday mark-to-market नहीं।"
         )
     else:
         st.info("Backtest चलाने के लिए ऊपर **Run 5-Year Full-Market Backtest** दबाएँ।")


with mtf_tab:
    st.header("🧭 CRT Multiple Time Frame Analysis")
    st.caption(
        "Index और Stocks की सूची से एक या कई symbols चुनकर CRT MTF scan करें. "
        "मौजूदा CRT Scanner और Backtest के नियम इससे नहीं बदलते।"
    )
    mtf_universe_mode = st.radio(
        "किस सूची को स्कैन करना है? (क्लिक करें)",
        ["All Index", "All Stocks", "All India Stocks + Indices"],
        horizontal=True,
        key="crt_mtf_universe_mode",
        help="All Index = mapped Indian indices; All Stocks = NSE EQ stocks; All India Stocks + Indices = NSE, BSE, SME और mapped indices."
    )
    mtf_mode_map = {
        "All Index": "All Indian indices",
        "All Stocks": "All NSE EQ stocks",
        "All India Stocks + Indices": "All India stocks + indices",
    }
    mtf_universe_mode = mtf_mode_map[mtf_universe_mode]

    @st.cache_data(ttl=1800, show_spinner=False)
    def _load_mtf_universe(mode: str) -> pd.DataFrame:
        return make_universe(mode)

    try:
        with st.spinner("Index / Stock list लोड हो रही है..."):
            mtf_universe = _load_mtf_universe(mtf_universe_mode)
        mtf_universe = mtf_universe[
            mtf_universe["Symbol"].fillna("").astype(str).str.strip().ne("")
        ].drop_duplicates(subset=["Symbol", "Name", "Exchange"])
        mtf_labels = {
            f"{row.Name} | {row.Exchange} | {row.Symbol}": row.Symbol
            for row in mtf_universe.itertuples(index=False)
        }
        all_mtf_labels = list(mtf_labels.keys())
        select_col, clear_col = st.columns(2)
        if select_col.button(f"☑️ इस सूची के सभी चुनें ({len(all_mtf_labels):,})", key="mtf_select_all"):
            st.session_state["crt_mtf_selected_symbols"] = all_mtf_labels
        if clear_col.button("चयन हटाएँ", key="mtf_clear_selection"):
            st.session_state["crt_mtf_selected_symbols"] = []
        selected_labels = st.multiselect(
            "Index / Stock चुनें (नाम सर्च करके भी चुन सकते हैं)",
            options=all_mtf_labels,
            key="crt_mtf_selected_symbols",
            placeholder="जैसे NIFTY 50, RELIANCE, HDFC BANK..."
        )
        c1, c2 = st.columns(2)
        c1.metric("इस सूची में उपलब्ध", f"{len(mtf_universe):,}")
        c2.metric("आपने चुने", f"{len(selected_labels):,}")
        st.caption(
            "पहले एक या अधिक नाम चुनें, फिर Scan दबाएँ। बहुत बड़े चयन में Yahoo Finance की "
            "rate limits और data availability के कारण scan में समय लग सकता है।"
        )
        run_mtf = st.button(
            f"🔍 Scan Selected ({len(selected_labels)})",
            type="primary",
            key="run_crt_mtf",
            disabled=not selected_labels,
        )
        if run_mtf:
            selected_symbols = [mtf_labels[label] for label in selected_labels]
            all_rows = []
            all_errors = {}
            progress = st.progress(0.0, text="Starting MTF scan...")
            status = st.empty()
            for i, label in enumerate(selected_labels, start=1):
                symbol = mtf_labels[label]
                status.caption(f"Scanning {i:,}/{len(selected_symbols):,}: {label}")
                try:
                    result_df, symbol_errors = analyze_mtf_symbol(symbol)
                    if not result_df.empty:
                        result_df.insert(0, "Symbol", symbol)
                        result_df.insert(1, "Name", label.split(" | ")[0])
                        all_rows.append(result_df)
                    if symbol_errors:
                        all_errors[symbol] = "; ".join(
                            f"{tf}: {msg}" for tf, msg in symbol_errors.items()
                        )
                except Exception as exc:
                    all_errors[symbol] = str(exc)[:250]
                progress.progress(i / len(selected_symbols), text=f"MTF scan: {i:,}/{len(selected_symbols):,}")
            st.session_state["crt_mtf_results"] = (
                pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame()
            )
            st.session_state["crt_mtf_errors"] = all_errors
            st.session_state["crt_mtf_selected_count"] = len(selected_symbols)
            st.session_state["crt_mtf_scan_time"] = datetime.now().strftime("%d-%b-%Y %I:%M:%S %p")
            status.success("Selected symbols का scan पूरा हुआ।")

        if "crt_mtf_results" in st.session_state:
            results_mtf = st.session_state["crt_mtf_results"].copy()
            st.subheader("MTF Scan Results")
            if not results_mtf.empty:
                signal_filter = st.multiselect(
                    "Signal filter",
                    ["BULL ORDER", "BEAR ORDER", "WAIT"],
                    default=["BULL ORDER", "BEAR ORDER", "WAIT"],
                    key="crt_mtf_signal_filter",
                )
                visible_mtf = results_mtf[results_mtf["Signal"].isin(signal_filter)].copy()

                # Trade-sequence view: HTF confirmation -> LTF confirmation -> zone -> retest.
                def _setup_status(row, prefix):
                    liquidity = str(row.get(f"{prefix} Liquidity", "—"))
                    structure = str(row.get(f"{prefix} MSS", "—"))
                    structure = structure.replace(" MSS", " CHoCH")
                    if liquidity in ("—", "NO DATA", "ERROR"):
                        return f"{liquidity} | {structure}"
                    return f"{liquidity} | {structure}"

                compact_mtf = pd.DataFrame({
                    "Symbol": visible_mtf["Symbol"],
                    "Name": visible_mtf["Name"],
                    "CRT (HTF → LTF)": visible_mtf["HTF → LTF"],
                    "M1 High": visible_mtf["CRT M1 High"],
                    "M1 Low": visible_mtf["CRT M1 Low"],
                    "M2 Sweep": visible_mtf["CRT Sweep"],
                    "Sweep Direction": visible_mtf["Sweep Direction"],
                    "Entry-TF CHoCH": visible_mtf["Entry-TF CHoCH"],
                    "Entry Zone": visible_mtf["Entry Zone"].replace({"—": "NOT FORMED"}),
                    "Retest": visible_mtf["Entry Status"],
                    "Entry": visible_mtf["Entry Price"],
                    "SL": visible_mtf["Stop Loss"],
                    "Target": visible_mtf["Target"],
                    "RR": visible_mtf["RR"],
                    "Signal": visible_mtf["Signal"],
                })
                st.dataframe(compact_mtf, use_container_width=True, hide_index=True)
                csv = compact_mtf.to_csv(index=False).encode("utf-8-sig")
                st.download_button(
                    "⬇️ Download MTF results (CSV)", csv,
                    file_name="crt_mtf_scan_results.csv", mime="text/csv"
                )
            else:
                st.warning("चुने गए symbols के लिए Yahoo Finance से usable MTF data नहीं मिला।")
            errors = st.session_state.get("crt_mtf_errors", {})
            st.caption(
                f"Scanned symbols: {st.session_state.get('crt_mtf_selected_count', 0):,} · "
                f"Data errors: {len(errors):,} · "
                f"Time: {st.session_state.get('crt_mtf_scan_time', '')}"
            )
            if errors:
                with st.expander("Data availability / errors"):
                    st.dataframe(
                        pd.DataFrame([{"Symbol": k, "Error": v} for k, v in errors.items()]),
                        use_container_width=True, hide_index=True
                    )
            st.caption(
                "HTF→LTF pairs: Monthly→Daily, Weekly→4H, Daily→1H, 4H→5m और 1H→5m. "
                "BULL/BEAR ORDER तभी दिखेगा जब दोनों timeframes पर same-direction sweep + MSS के बाद साझा FVG/IFVG/OB/BOB retest और confirmation मिले। "
                "यह confirmation watchlist है; FVG/OB retest, exact entry/SL/target और broker order "
                "execution इसमें शामिल नहीं हैं। Yahoo Finance intraday history सीमित/delayed हो सकती है; "
                "नवीनतम संभावित incomplete candle analysis से हटाई जाती है।"
            )
    except Exception as exc:
        st.error(f"Index / Stock universe लोड नहीं हो सका: {exc}")

with screener_tab:
    st.header("🔎 CRT Multi-Timeframe Multi-Symbol Screener")
    st.caption(
        "हर selected symbol पर सभी पाँच timeframe pairs में एक ही CRT strategy लागू होगी: "
        "HTF M1 range → HTF M2 one-side sweep + full-range reclaim → LTF CHoCH → "
        "FVG / IFVG / OB / BOB retest → directional LTF close."
    )
    st.info(
        "Pairs: Monthly→Daily · Weekly→4H · Daily→1H · 4H→5m · 1H→5m. "
        "SL sweep candle के extreme पर और Target HTF M1 की opposite liquidity boundary पर. "
        "Scanner read-only है; broker orders नहीं देता।"
    )
    @st.cache_data(ttl=1800, show_spinner=False)
    def _load_screener_universe(mode: str) -> pd.DataFrame:
        return make_universe(mode)

    # Two simple choices only; selecting one loads its complete symbol list.
    choice_col1, choice_col2 = st.columns(2)
    if choice_col1.button("📊 All Index", key="crt_choose_all_indices", use_container_width=True):
        st.session_state["crt_screener_choice"] = "All Index"
        st.session_state.pop("crt_multi_screener_results", None)
    if choice_col2.button("📈 All Stocks", key="crt_choose_all_stocks", use_container_width=True):
        st.session_state["crt_screener_choice"] = "All Stocks"
        st.session_state.pop("crt_multi_screener_results", None)

    selected_choice = st.session_state.get("crt_screener_choice")
    mode_map = {"All Index": "All Indian indices", "All Stocks": "All NSE EQ stocks"}
    requested = []
    if selected_choice:
        try:
            with st.spinner(f"{selected_choice} की पूरी सूची लोड हो रही है..."):
                screener_universe = _load_screener_universe(mode_map[selected_choice])
            screener_universe = screener_universe[
                screener_universe["Symbol"].fillna("").astype(str).str.strip().ne("")
            ].drop_duplicates(subset=["Symbol", "Name", "Exchange"])
            requested = screener_universe["Symbol"].drop_duplicates().tolist()
            st.success(f"{selected_choice}: {len(requested):,} symbols चुने गए हैं। Search या individual selection की जरूरत नहीं है।")
        except Exception as exc:
            st.error(f"{selected_choice} की सूची लोड नहीं हो सकी: {exc}")
            requested = []
    else:
        st.info("पहले All Index या All Stocks में से एक चुनें।")
    st.markdown(
        "**Same strategy on every pair:** M1/M2 HTF liquidity sweep & reclaim → "
        "LTF CHoCH → FVG / IFVG / OB / BOB retest → confirming LTF close."
    )
    run_screener = st.button(
        "🔍 Scan All Symbols × All 5 Timeframes",
        type="primary", key="run_crt_multi_screener", disabled=not requested,
    )
    if run_screener:
        progress = st.progress(0.0, text="Starting all-pair CRT scan...")
        status = st.empty()
        try:
            def _screener_progress(done: int, total: int, symbol: str):
                progress.progress(done / max(total, 1), text=f"Scanning {done:,}/{total:,}: {symbol}")
                status.caption(f"Current symbol: {symbol}")

            combined, all_errors = scan_symbols(requested, progress_callback=_screener_progress)
            if not combined.empty:
                symbol_name_map = dict(zip(screener_universe["Symbol"], screener_universe["Name"]))
                combined.insert(1, "Name", combined["Symbol"].map(symbol_name_map).fillna(combined["Symbol"]))
        except Exception as exc:
            combined = pd.DataFrame()
            all_errors = {"ALL": f"{type(exc).__name__}: {str(exc)[:180]}"}
        progress.progress(1.0, text="All selected symbols processed")
        st.session_state["crt_multi_screener_results"] = combined
        st.session_state["crt_multi_screener_errors"] = all_errors
        st.session_state["crt_multi_screener_time"] = datetime.now().strftime("%d-%b-%Y %I:%M:%S %p")
        status.success("हर selected symbol के सभी पाँच timeframe pairs का scan पूरा हुआ।")

    if "crt_multi_screener_results" in st.session_state:
        screener_df = st.session_state["crt_multi_screener_results"].copy()
        if not screener_df.empty:
            preferred = [
                "Symbol", "HTF → LTF", "CRT M1 High", "CRT M1 Low",
                "CRT M2 High", "CRT M2 Low", "CRT M2 Close", "CRT Sweep",
                "Sweep Direction", "Entry-TF CHoCH", "Entry Zone", "Retest Zone",
                "Retest Price", "Entry Price", "Stop Loss", "Target", "RR",
                "Entry Time", "Alignment", "Entry Status", "Signal",
                "CRT M1 Candle", "CRT M2 Candle", "CHoCH Time",
                "CRT Close", "Entry-TF Close",
            ]
            display = screener_df[[c for c in preferred if c in screener_df.columns]].copy()

            # Main view shows CRT marking and entry plan; diagnostic timestamps stay expandable.
            # Keep the primary table narrow and decision-focused.
            # Full CRT levels, candle timestamps, alignment and diagnostics remain
            # available in the Detailed data expander below.
            compact_columns = [
                "HTF → LTF", "CRT Sweep", "Entry-TF CHoCH",
                "Retest Zone", "Entry Price", "Stop Loss", "Target", "Signal",
            ]
            detail_columns = [
                c for c in display.columns
                if c not in ("Symbol", *compact_columns)
            ]

            def _tradingview_symbol(raw_symbol: str) -> str:
                raw = str(raw_symbol).strip().upper()
                # Yahoo Finance index tickers are not TradingView tickers.
                # Map known index aliases explicitly; never prefix NSE: to a caret ticker.
                known_indices = {
                    "^NSEI": "NSE:NIFTY",
                    "^NSEBANK": "NSE:BANKNIFTY",
                    "^BSESN": "BSE:SENSEX",
                    "^INDIAVIX": "NSE:INDIAVIX",
                    "^NSMIDCP": "NSE:NIFTYJR",
                    "^CNX100": "NSE:CNX100",
                    "^CNX200": "NSE:CNX200",
                    "^CRSLDX": "NSE:CNX500",
                    "^NSEMDCP50": "NSE:NIFTYMIDCAP50",
                    "^CNXFIN": "NSE:NIFTYFINSRV25_50",
                    "^CNXIT": "NSE:CNXIT",
                    "^CNXAUTO": "NSE:CNXAUTO",
                    "^CNXFMCG": "NSE:CNXFMCG",
                    "^CNXPHARMA": "NSE:CNXPHARMA",
                    "^CNXMETAL": "NSE:CNXMETAL",
                    "^CNXREALTY": "NSE:CNXREALTY",
                    "^CNXENERGY": "NSE:CNXENERGY",
                    "^CNXMEDIA": "NSE:CNXMEDIA",
                    "^CNXPSUBANK": "NSE:CNXPSUBANK",
                    "^CNXINFRA": "NSE:CNXINFRA",
                    "^CNXMNC": "NSE:CNXMNC",
                    "^CNXSC": "NSE:CNXSMALLCAP",
                    "^CNXCONSUM": "NSE:CNXCONSUM",
                    "^CNXSERVICE": "NSE:CNXSERVICE",
                    "^CNXPSE": "NSE:CNXPSE",
                    "^CNXCMDT": "NSE:CNXCMDT",
                }
                if raw in known_indices:
                    return known_indices[raw]
                if raw.startswith("^"):
                    return ""
                if raw.endswith(".NS"):
                    return "NSE:" + raw[:-3]
                if raw.endswith(".BO"):
                    return "BSE:" + raw[:-3]
                return raw if raw.startswith(("NSE:", "BSE:")) else "NSE:" + raw

            # Symbol is intentionally hidden from the on-screen results and CSV.
            name_lookup = (
                screener_df[["Symbol", "Name"]].drop_duplicates("Symbol").set_index("Symbol")["Name"].to_dict()
                if "Name" in screener_df.columns else {}
            )
            crt_interval_map = {
                "Monthly → Daily": "1M",
                "Weekly → 4H": "1W",
                "Daily → 1H": "1D",
                "4H → 5m": "240",
                "1H → 5m": "60",
            }
            entry_interval_map = {
                "Monthly → Daily": "1D",
                "Weekly → 4H": "240",
                "Daily → 1H": "60",
                "4H → 5m": "5",
                "1H → 5m": "5",
            }
            for group_number, (symbol, symbol_rows) in enumerate(display.groupby("Symbol", sort=False)):
                company_name = name_lookup.get(symbol, "Company / Index")
                with st.expander(f"{company_name} · {len(symbol_rows)} timeframe pairs", expanded=True):
                    summary_columns = [c for c in compact_columns if c in symbol_rows.columns]
                    table_key = f"crt_pair_table_{group_number}"
                    st.caption("CRT की M1/M2 marking CRT timeframe से है; Entry/CHoCH/Zone planning Entry timeframe से है। Row चुनकर संबंधित chart खोलें।")
                    st.dataframe(
                        symbol_rows[summary_columns].reset_index(drop=True),
                        use_container_width=True, hide_index=True,
                        on_select="rerun", selection_mode="single-row", key=table_key,
                    )
                    selected_rows = st.session_state.get(table_key, {}).get("selection", {}).get("rows", [])
                    if selected_rows:
                        selected_position = int(selected_rows[0])
                        if 0 <= selected_position < len(symbol_rows):
                            selected_pair = str(symbol_rows.iloc[selected_position]["HTF → LTF"])
                            crt_interval = crt_interval_map.get(selected_pair, "1D")
                            entry_interval = entry_interval_map.get(selected_pair, "1D")
                            tv_symbol = _tradingview_symbol(symbol)
                            if tv_symbol:
                                crt_url = (
                                    "https://www.tradingview.com/chart/?symbol="
                                    + quote(tv_symbol, safe="")
                                    + "&interval=" + crt_interval
                                )
                                entry_url = (
                                    "https://www.tradingview.com/chart/?symbol="
                                    + quote(tv_symbol, safe="")
                                    + "&interval=" + entry_interval
                                )
                                chart_col1, chart_col2 = st.columns(2)
                                chart_col1.link_button(
                                    f"📊 Open {selected_pair.split(' → ')[0]} CRT Chart",
                                    crt_url, type="primary", use_container_width=True,
                                )
                                chart_col2.link_button(
                                    f"🎯 Open {selected_pair.split(' → ')[1]} Entry Chart",
                                    entry_url, use_container_width=True,
                                )
                            else:
                                st.warning(
                                    "इस Index का TradingView ticker mapping उपलब्ध नहीं है। "
                                    "इसलिए गलत/Invalid chart खोलने के बजाय chart link नहीं बनाया गया।"
                                )
                    if detail_columns:
                        with st.expander("Detailed data (prices, alignment and candles)"):
                            st.dataframe(
                                symbol_rows[detail_columns].reset_index(drop=True),
                                use_container_width=True, hide_index=True,
                            )
            export_df = screener_df.drop(columns=["Symbol"], errors="ignore")
            st.download_button(
                "⬇️ Download All-Timeframe Multi-Scanner CSV",
                export_df.to_csv(index=False).encode("utf-8-sig"),
                file_name="crt_multi_symbol_all_timeframes.csv",
                mime="text/csv", key="download_crt_multi_screener",
            )
            st.caption(
                f"Timeframe rows: {len(screener_df)} · "
                f"Time: {st.session_state.get('crt_multi_screener_time', '')}"
            )
        else:
            st.info("चुने गए symbols के लिए usable timeframe data नहीं मिला।")
        errors = st.session_state.get("crt_multi_screener_errors", {})
        if errors:
            with st.expander("Data availability / errors"):
                st.dataframe(
                    pd.DataFrame([{"Symbol / Pair": k, "Error": v} for k, v in errors.items()]),
                    use_container_width=True, hide_index=True,
                )
    st.caption(
        "Five configured pairs पर समान CRT flow लागू है. Yahoo Finance data availability/interval limits "
        "के कारण किसी pair में data missing हो सकता है; ऐसे pair को error/WAIT के रूप में दिखाया जाएगा. "
        "यह signal-only scanner है, execution system नहीं।"
    )


with scanner50_tab:
    st.header("🚀 Scanner 5.0 · Independent Market Engine")
    st.caption("Standalone NSE / BSE research engine · CRT strategy से पूर्णतः अलग")

    engine_root = Path(__file__).resolve().parent / "scanner5_engine" / "trader-india"
    if not engine_root.exists():
        st.error("Scanner 5.0 engine files नहीं मिले। Repository deployment में scanner5_engine/trader-india मौजूद होना चाहिए।")
    else:
        st.success("Standalone Scanner 5.0 engine loaded · CRT modules / CRT signals का कोई import या dependency नहीं।")
        st.markdown("इस tab में scan वास्तविक Scanner 5.0 के vendored engine scripts से चलता है; केवल JSON upload viewer नहीं है।")

        c1, c2 = st.columns(2)
        with c1:
            market50 = st.selectbox("Exchange", ["NSE", "BSE"], key="s50_exchange")
        with c2:
            mode50 = st.selectbox("Scanner", ["Daily", "Intraday (5-minute + 15-minute ORB)"], key="s50_mode")
        scope50 = st.selectbox("Scan Universe", ["All exchange stocks", "Nifty 50", "Custom symbols"], key="s50_scope")
        symbols50 = st.text_input("Optional symbols (comma separated)", placeholder="RELIANCE,TCS,INFY (Custom symbols चुनने पर)", key="s50_symbols")
        full_universe50 = scope50 == "All exchange stocks"
        nifty50_universe = scope50 == "Nifty 50"
        volume50 = st.number_input("Intraday volume multiple", min_value=1.0, max_value=5.0, value=1.5, step=0.1, key="s50_volume")
        run50 = st.button("▶ Run Scanner 5.0", type="primary", key="run_standalone_scanner50")

        if run50:
            is_intraday = mode50.startswith("Intraday")
            try:
                if (full_universe50 or nifty50_universe) and not is_intraday:
                    # All stocks use the exchange security master; Nifty 50 uses the
                    # official Nifty constituent CSV. Yahoo Finance supplies OHLCV only.
                    if nifty50_universe:
                        if market50 != "NSE":
                            st.warning("Nifty 50 constituents NSE-listed हैं; इस विकल्प में NSE symbols Yahoo Finance से scan होंगे।")
                        @st.cache_data(ttl=86400, show_spinner=False)
                        def _load_nifty50_symbols():
                            url = "https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv"
                            frame = pd.read_csv(url)
                            symbol_col = next((col for col in frame.columns if str(col).strip().upper() == "SYMBOL"), None)
                            if symbol_col is None:
                                raise ValueError("Nifty 50 constituent file में SYMBOL column नहीं मिला")
                            symbols = frame[symbol_col].dropna().astype(str).str.strip().str.upper()
                            return pd.DataFrame({"Symbol": symbols + ".NS", "Name": symbols})
                        with st.spinner("Nifty 50 की वर्तमान constituent सूची लोड हो रही है..."):
                            universe50 = _load_nifty50_symbols()
                        market_scan_label50 = "Nifty 50"
                    else:
                        universe_mode50 = "All NSE EQ stocks" if market50 == "NSE" else "All BSE EQ stocks"
                        with st.spinner(f"Loading complete {market50} equity universe..."):
                            universe50 = make_universe(universe_mode50)
                        universe50 = universe50[
                            universe50["Symbol"].fillna("").astype(str).str.strip().ne("")
                            & universe50["Type"].eq("Stock")
                        ].drop_duplicates(subset=["Symbol"])
                        market_scan_label50 = f"All {market50} stocks"
                    if universe50.empty:
                        st.error(f"{market50} exchange master से कोई equity symbol नहीं मिला।")
                        st.stop()
                    symbols_full50 = universe50["Symbol"].astype(str).tolist()
                    st.info(f"{market_scan_label50} में {len(symbols_full50):,} symbols लोड हुए। Yahoo पर जिनका data उपलब्ध नहीं होगा, वे errors में दिखेंगे।")
                    sys.path.insert(0, str(engine_root))
                    import india as scanner50_india
                    with st.spinner(f"Yahoo Finance से {len(symbols_full50):,} shares का Daily OHLC data डाउनलोड हो रहा है..."):
                        price_map50, errors_map50 = download_market_data(
                            symbols_full50, period="3mo", batch_size=60
                        )
                    result_rows50 = []
                    for ticker50, frame50 in price_map50.items():
                        plain_symbol50 = ticker50[:-3] if ticker50.endswith(".NS") else ticker50[:-3] if ticker50.endswith(".BO") else ticker50
                        bars50 = []
                        for stamp50, row50 in frame50.iterrows():
                            stamp_iso50 = pd.Timestamp(stamp50).isoformat()
                            def _num50(value):
                                try:
                                    value = float(value)
                                    return value if pd.notna(value) else None
                                except (TypeError, ValueError):
                                    return None
                            bars50.append({
                                "time": stamp_iso50, "open": _num50(row50.get("Open")),
                                "high": _num50(row50.get("High")), "low": _num50(row50.get("Low")),
                                "close": _num50(row50.get("Close")), "volume": _num50(row50.get("Volume")) or 0,
                            })
                        if bars50:
                            analysed50 = scanner50_india.analyze_daily(plain_symbol50, bars50)
                            analysed50["exchange"] = market50
                            analysed50["ticker"] = ticker50
                            analysed50["name"] = universe50.loc[universe50["Symbol"].eq(ticker50), "Name"].iloc[0]
                            result_rows50.append(analysed50)
                    payload50 = {
                        "market": market50, "mode": "research_only", "symbols_requested": len(symbols_full50),
                        "symbols_returned": len(price_map50), "failed": len(errors_map50),
                        "results": result_rows50,
                        "errors": [{"symbol": k, "error": v} for k, v in errors_map50.items()],
                        "data_warning": "Yahoo Finance unofficial feed. Full exchange listing is loaded, but Yahoo OHLC coverage is not guaranteed. Daily scan uses 3 months of history.",
                    }
                    st.session_state["scanner50_live_payload"] = payload50
                    st.session_state["scanner50_live_market"] = market50
                    st.session_state["scanner50_live_mode"] = mode50
                else:
                    if (full_universe50 or nifty50_universe) and is_intraday:
                        st.warning("पूरे एक्सचेंज का Intraday scan अभी उपलब्ध नहीं है; Intraday के लिए comma-separated symbols दें। Full-universe Daily scan उपलब्ध है।")
                        st.stop()
                    script_name = (
                        "intraday.py" if market50 == "NSE" and is_intraday else
                        "india.py" if market50 == "NSE" else
                        "bse_intraday.py" if is_intraday else "bse.py"
                    )
                    if not symbols50.strip():
                        st.error("Custom symbols scan के लिए कम से कम एक symbol लिखें।")
                        st.stop()\n                    command = [sys.executable, str(engine_root / script_name), "--symbols", symbols50.strip()]
                    if market50 == "NSE" and is_intraday:
                        command += ["--volume-multiple", str(volume50)]
                    with tempfile.TemporaryDirectory(prefix="scanner50-") as temp_dir:
                        output_file = Path(temp_dir) / "scanner50-results.json"
                        command += ["--output", str(output_file)]
                        with st.spinner(f"Scanner 5.0 {market50} {mode50} scan चल रहा है..."):
                            completed = subprocess.run(command, capture_output=True, text=True, timeout=900, check=False)
                            if completed.stdout:
                                st.text(completed.stdout[-6000:])
                            if completed.stderr:
                                st.warning(completed.stderr[-4000:])
                            if output_file.exists():
                                payload50 = json.loads(output_file.read_text(encoding="utf-8"))
                                st.session_state["scanner50_live_payload"] = payload50
                                st.session_state["scanner50_live_market"] = market50
                                st.session_state["scanner50_live_mode"] = mode50
                            elif completed.returncode != 0:
                                st.error(f"Scanner process failed (exit code {completed.returncode}).")
                            else:
                                st.warning("Scan completed, but no JSON result file was produced.")
            except Exception as exc:
                st.exception(exc)

        payload50 = st.session_state.get("scanner50_live_payload")
        if payload50:
            st.subheader(f"{st.session_state.get('scanner50_live_market', '')} · {st.session_state.get('scanner50_live_mode', '')} results")
            result_rows50 = payload50.get("results", payload50.get("signals", []))
            if isinstance(result_rows50, list) and result_rows50:
                result_df50 = pd.json_normalize(result_rows50, sep=".")
                st.metric("Scanned records", len(result_df50))
                st.dataframe(result_df50, use_container_width=True, hide_index=True)
                st.download_button(
                    "⬇️ Download Scanner 5.0 results (JSON)",
                    json.dumps(payload50, ensure_ascii=False, indent=2).encode("utf-8"),
                    file_name="scanner_5_0_results.json",
                    mime="application/json",
                    key="download_scanner50_live_json",
                )
            else:
                st.info("इस scan में कोई matching result नहीं मिला।")
            if payload50.get("errors"):
                with st.expander(f"Data errors ({len(payload50['errors'])})"):
                    st.dataframe(pd.json_normalize(payload50["errors"]), use_container_width=True, hide_index=True)
            if payload50.get("data_warning"):
                st.warning(payload50["data_warning"])
            if payload50.get("warning"):
                st.warning(payload50["warning"])

        st.divider()
        st.subheader("Scanner 5.0 के अन्य स्वतंत्र tools")
        st.markdown(
            "- **Sector strength:** NSE/BSE sector relative-strength snapshots (sectors.py)"
            "\n- **F&O:** normalized NSE futures bhavcopy CSV से OI buildup analysis (derivatives.py)"
            "\n- **Risk & paper trading:** position sizing, paper ledger, mark-to-market और stop alerts (paper.py, portfolio.py)"
            "\n- **Research:** daily-bar baseline backtesting और local JSON alerts (backtest.py, alerts.py)"
        )
        fo_file50 = st.file_uploader("NSE F&O normalized CSV (optional)", type=["csv"], key="s50_fo_csv")
        if fo_file50 and st.button("Analyze F&O / OI", key="s50_run_fo"):
            with tempfile.TemporaryDirectory(prefix="scanner50-fo-") as temp_dir:
                input_csv = Path(temp_dir) / "fo.csv"
                output_json = Path(temp_dir) / "fo-analysis.json"
                input_csv.write_bytes(fo_file50.getvalue())
                proc = subprocess.run(
                    [sys.executable, str(engine_root / "derivatives.py"), "--csv", str(input_csv), "--output", str(output_json)],
                    capture_output=True, text=True, timeout=120, check=False,
                )
                if output_json.exists():
                    fo_payload = json.loads(output_json.read_text(encoding="utf-8"))
                    st.session_state["scanner50_fo_payload"] = fo_payload
                if proc.stderr:
                    st.warning(proc.stderr[-3000:])
                if proc.returncode:
                    st.error(proc.stdout[-3000:] or "F&O analysis failed.")
        fo_payload = st.session_state.get("scanner50_fo_payload")
        if fo_payload:
            st.json(fo_payload)
            st.download_button("Download F&O analysis JSON", json.dumps(fo_payload, indent=2).encode("utf-8"), "scanner50_fo_analysis.json", "application/json", key="s50_download_fo")

        st.caption(
            "Data feed: Yahoo Finance via yfinance; data delayed/incomplete हो सकता है और सभी NSE/BSE symbols उपलब्ध हों यह guaranteed नहीं है। "
            "यह research/paper workflow है, buy/sell recommendation नहीं। इस integration में कोई broker order route या auto-trading नहीं है।"
        )
