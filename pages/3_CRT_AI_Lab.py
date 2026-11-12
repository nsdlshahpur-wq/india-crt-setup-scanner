from __future__ import annotations
import pandas as pd
import streamlit as st
import plotly.express as px
from backtest import BacktestConfig, run_backtest
from crt_ai import predict_crt_probability, train_crt_model
from nifty50_history import load_full_nifty50_1m
from scanner import ScanConfig, scan_symbol

st.set_page_config(page_title="CRT Daily AI Lab", page_icon="🧠", layout="wide")
st.title("🧠 Nifty 50 — Daily CRT Hybrid AI")
st.caption("Historical Daily CRT outcomes → chronological model validation → current confirmed CRT setup probability.")
st.info("यह AI केवल Daily CRT setup की ऐतिहासिक सफलता का अनुमान लगाता है। यह price forecast या live tick feed नहीं है और कोई order place नहीं करता।")

with st.sidebar:
    st.header("AI Lab Settings")
    capital = st.number_input("Backtest starting capital (₹)", min_value=10000.0, value=100000.0, step=10000.0)
    risk_pct = st.number_input("Risk per trade (%)", min_value=0.1, max_value=5.0, value=1.0, step=0.1)
    charges = st.number_input("Charges (bps / side)", min_value=0.0, max_value=100.0, value=12.0, step=1.0)
    slippage = st.number_input("Slippage (bps / side)", min_value=0.0, max_value=100.0, value=5.0, step=1.0)
    force_refresh = st.checkbox("Force refresh GitHub history", value=False)

st.markdown("### 1. Nifty 50 historical data")
st.write("Source: technovusin/nifty50-historical-data — 1-minute OHLC. Daily candles are reconstructed from intraday bars.")
if st.button("Download history + build Daily CRT training set", type="primary"):
    try:
        with st.spinner("GitHub से Nifty 50 1-minute history डाउनलोड/लोड हो रही है..."):
            intraday, source_report = load_full_nifty50_1m(force_refresh=force_refresh)
        daily = intraday.resample("1D").agg({"Open":"first","High":"max","Low":"min","Close":"last"}).dropna()
        daily = daily[daily.index.dayofweek < 5]
        if len(daily) < 100:
            st.error(f"Daily candles अपर्याप्त हैं: {len(daily)}")
            st.stop()
        progress = st.progress(0.0, text="Daily CRT walk-forward backtest...")
        status = st.empty()
        def progress_cb(done, total, symbol):
            progress.progress(done / max(total, 1), text=f"CRT backtest: {done}/{total}")
            status.caption(f"Symbol: {symbol}")
        result = run_backtest({"^NSEI":daily}, names={"^NSEI":"NIFTY 50"},
            config=BacktestConfig(initial_capital=float(capital), risk_pct=float(risk_pct),
                charges_bps_per_side=float(charges), slippage_bps_per_side=float(slippage)),
            scan_config=ScanConfig(), progress_callback=progress_cb)
        model_result = train_crt_model(result["trades"])
        latest_signal = scan_symbol("^NSEI", "NIFTY 50", daily, ScanConfig())
        st.session_state["crt_daily_ai_result"] = result
        st.session_state["crt_daily_ai_model"] = model_result
        st.session_state["crt_daily_ai_signal"] = latest_signal
        st.session_state["crt_daily_ai_source"] = source_report
        st.rerun()
    except Exception as exc:
        st.exception(exc)

if "crt_daily_ai_result" in st.session_state:
    result = st.session_state["crt_daily_ai_result"]
    fitted = st.session_state["crt_daily_ai_model"]
    signal = st.session_state.get("crt_daily_ai_signal")
    source = st.session_state.get("crt_daily_ai_source", {})
    metrics, trades = result["metrics"], result["trades"]
    st.divider()
    st.markdown("### 2. Historical CRT backtest")
    cols = st.columns(5)
    cols[0].metric("CRT trades", f"{metrics['total_trades']:,}")
    cols[1].metric("Win rate", f"{metrics['win_rate']:.1f}%")
    cols[2].metric("Profit factor", f"{metrics['profit_factor']:.2f}" if metrics["profit_factor"] != float("inf") else "∞")
    cols[3].metric("Net P&L", f"₹{metrics['net_pnl']:,.0f}")
    cols[4].metric("Max drawdown", f"{metrics['max_drawdown_pct']:.1f}%")
    st.caption(f"Candidates: {result.get('candidate_count',0)} · Intraday rows: {source.get('total_rows',0):,} · Data end: {source.get('end','—')}")
    if not trades.empty:
        st.dataframe(trades, use_container_width=True, hide_index=True)
        st.download_button("Download Nifty CRT trade history CSV", trades.to_csv(index=False).encode("utf-8-sig"), "nifty50_daily_crt_trades.csv", "text/csv")
    st.divider()
    st.markdown("### 3. AI chronological validation")
    report = fitted.report
    if fitted.model is None:
        st.warning(report.get("message", "Training data is insufficient."))
        st.write(f"Decisive labelled trades: {report.get('sample_count',0)} · Wins: {report.get('wins',0)} · Losses: {report.get('losses',0)}")
    else:
        m = st.columns(4)
        m[0].metric("Training samples", f"{report['train_count']:,}")
        m[1].metric("Unseen test samples", f"{report['test_count']:,}")
        m[2].metric("Holdout accuracy", f"{report['accuracy']*100:.1f}%")
        m[3].metric("Balanced accuracy", f"{report['balanced_accuracy']*100:.1f}%")
        st.write(f"Out-of-sample period: **{report['test_start']} to {report['test_end']}** · Brier score: **{report['brier_score']:.3f}**")
        st.caption(report["label_definition"])
        fig = px.bar(pd.DataFrame(report["feature_importance"]).head(10), x="importance", y="feature", orientation="h", title="Model feature importance")
        st.plotly_chart(fig, use_container_width=True)
    st.divider()
    st.markdown("### 4. Latest Nifty 50 Daily CRT setup")
    if not signal:
        st.info("Latest available Daily candles में कोई CRT context नहीं मिला।")
    else:
        st.write(f"**Setup:** {signal.get('Setup')} · **Bias:** {signal.get('Bias')} · **Last candle:** {signal.get('Last Candle')}")
        st.write(f"**Monthly status:** {signal.get('Monthly Status')} · **Entry status:** {signal.get('Entry Status')}")
        if signal.get("Stage") == 3 and fitted.model is not None:
            probability = predict_crt_probability(fitted.model, signal)
            st.metric("AI estimated probability of positive net outcome", f"{probability*100:.1f}%")
            st.caption("यह historical closed CRT trades से सीखी गई model estimate है, calibrated guarantee नहीं। Holdout score और sample count भी देखें।")
        elif signal.get("Stage") == 3:
            st.warning("Fresh CRT entry है, लेकिन labelled historical trades पर्याप्त नहीं हैं; AI probability नहीं दिखाई जा सकती।")
        else:
            st.info("Stage 3 का fresh confirmed BUY/SELL entry नहीं है; waiting या stale setup पर probability नहीं दिखाई जाती।")
        keys = ["Setup","Bias","Entry","SL","Target (M1 Monthly H/L)","Entry Zone Type","CHoCH Rule","Setup Reason","Last Candle"]
        st.dataframe(pd.DataFrame([{"Field":k,"Value":signal.get(k)} for k in keys]), hide_index=True, use_container_width=True)
    with st.expander("Data source report"):
        st.write(source)
    st.warning("Research-only model: data gaps, approximate OHLC fills, small-sample overfitting और market regime changes बने रहते हैं। पहले paper trading में validate करें।")
else:
    st.info("शुरू करने के लिए ऊपर Download history + build Daily CRT training set दबाएँ।")
