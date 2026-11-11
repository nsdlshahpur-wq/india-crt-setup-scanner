from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from ai_assistant import generate_market_answer
from data_fetch import download_market_data

st.set_page_config(page_title="AI Market Assistant", page_icon="🤖", layout="wide")
st.title("🤖 AI Market Assistant")
st.caption("Optional AI explanation of scanner output and recent OHLC candles. It is not an autonomous market-data or trading engine.")

with st.sidebar:
    provider = st.selectbox("AI provider", ["OpenAI", "Gemini", "Groq"])
    model_default = "gpt-5.5" if provider == "OpenAI" else ("gemini-3.5-flash-lite" if provider == "Gemini" else "openai/gpt-oss-20b")
    model = st.text_input("Model ID", model_default)
    st.markdown(
        "**API key setup**\n\n"
        "OpenAI: [API keys](https://platform.openai.com/api-keys)\n\n"
        "Gemini: [Google AI Studio](https://aistudio.google.com/app/apikey)\n\n"
        "Groq: [Groq Console](https://console.groq.com/keys)"
    )

try:
    secrets_ai = st.secrets.get("ai", {})
    secret_name = "openai_api_key" if provider == "OpenAI" else ("gemini_api_key" if provider == "Gemini" else "groq_api_key")
    api_key = str(secrets_ai.get(secret_name, ""))
except Exception:
    secret_name = "openai_api_key" if provider == "OpenAI" else ("gemini_api_key" if provider == "Gemini" else "groq_api_key")
    api_key = ""

if api_key:
    st.success(f"{provider} API key found in Streamlit secrets.")
else:
    st.warning(
        f"{provider} API key missing. Streamlit → App settings → Secrets में यह जोड़ें:"
    )
    st.code(f'[ai]\n{secret_name} = "YOUR_API_KEY"', language="toml")
    st.caption("API key को chat या GitHub में paste न करें।")

with st.sidebar:
    if st.button("🔌 Test AI connection", key="test_ai_connection", disabled=not bool(api_key.strip())):
        try:
            with st.spinner(f"Testing {provider} connection..."):
                test_answer = generate_market_answer(
                    provider, api_key, "Reply with exactly: AI_CONNECTION_OK", model=model
                )
            st.success("AI connection successful.")
            st.caption(test_answer[:180])
        except Exception as exc:
            detail = str(exc).replace(api_key, "[hidden API key]")[:500]
            st.error(f"{type(exc).__name__}: {detail}")

scan_map = st.session_state.get("scan_price_map", {})
scan_names = st.session_state.get("scan_symbol_names", {})
if scan_map:
    symbol = st.selectbox(
        "Symbol to analyse",
        sorted(scan_map),
        format_func=lambda x: f"{x} — {scan_names.get(x, '')}",
    )
else:
    symbol = st.text_input("Symbol (Yahoo format)", "RELIANCE.NS")

question = st.text_area(
    "Ask about the market / CRT setup",
    "Is symbol ka CRT setup, trend, liquidity sweep, entry confirmation aur risk levels explain kijiye. Missing data aur invalidation bhi batayein.",
    height=110,
)
include_mtf = st.checkbox("Include latest Monthly-Daily CRT matrix from this session", value=True)

if st.button("✨ Analyse with AI", type="primary", disabled=not bool(api_key.strip())):
    try:
        price_frame = scan_map.get(symbol)
        if price_frame is None or price_frame.empty:
            with st.spinner(f"Downloading daily OHLC for {symbol}..."):
                prices, errors = download_market_data([symbol], period="1y", batch_size=1)
            price_frame = prices.get(symbol, pd.DataFrame())
            if price_frame.empty:
                st.error(f"Market data unavailable: {errors.get(symbol, 'No daily candles returned')}")
                st.stop()

        context_parts = [f"SYMBOL: {symbol}", "DATA SOURCE: Yahoo Finance daily OHLC from the scanner."]
        scan_results = st.session_state.get("scan_results")
        if isinstance(scan_results, pd.DataFrame) and not scan_results.empty:
            selected = scan_results[scan_results["Symbol"] == symbol]
            if not selected.empty:
                context_parts.append("MAIN SCANNER RESULT:\n" + selected.iloc[0].to_json(force_ascii=False, indent=2, default_handler=str))

        matrix = st.session_state.get("mtf_rows")
        if include_mtf and st.session_state.get("mtf_symbol") == symbol and matrix:
            context_parts.append("MONTHLY-DAILY CRT MATRIX:\n" + json.dumps(matrix, ensure_ascii=False, default=str))

        bars = price_frame.copy().tail(20)
        if isinstance(bars.columns, pd.MultiIndex):
            bars.columns = [str(c[-1] if str(c[-1]).lower() in {"open", "high", "low", "close", "volume"} else c[0]).title() for c in bars.columns]
        bars.columns = [str(c).title() for c in bars.columns]
        keep = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in bars.columns]
        bars = bars[keep].copy()
        bars.index = bars.index.astype(str)
        context_parts.append("LAST 20 DAILY CANDLES (not guaranteed real-time):\n" + bars.to_json(orient="index", force_ascii=False))
        market_context = "\n\n".join(context_parts)

        with st.spinner(f"{provider} is analysing the supplied scanner context..."):
            answer = generate_market_answer(provider, api_key, question, market_context, model)
        history = st.session_state.get("ai_market_history", [])
        history.append({"Question": question, "Answer": answer, "Symbol": symbol, "Provider": provider})
        st.session_state["ai_market_history"] = history[-10:]
    except Exception as exc:
        detail = str(exc).replace(api_key, "[hidden API key]")[:500]
        st.error(f"AI analysis failed ({type(exc).__name__}): {detail}")

history = st.session_state.get("ai_market_history", [])
if history:
    st.divider()
    st.subheader("Recent AI responses")
    for item in reversed(history):
        with st.expander(f"{item['Symbol']} · {item['Provider']} · {item['Question'][:70]}"):
            st.markdown(item["Answer"])

with st.expander("Security, privacy and limitations"):
    st.markdown(
        "- AI provider API keys are read from Streamlit secrets and are not stored in the database.\n"
        "- The request sends the selected symbol, scanner result (if present), optional Monthly-Daily matrix and up to 20 recent daily OHLC candles to the chosen AI provider.\n"
        "- Broker passwords, API tokens, holdings, funds and order details are not sent.\n"
        "- Gemini free-tier requests may be used to improve Google products under the current free-tier terms; do not send account identifiers or private financial information.\n"
        "- AI can make mistakes and does not provide verified exchange-grade live quotes, news or guaranteed signals.\n"
        "- This page currently explains supplied OHLC/scanner data; it does not independently scan the whole market or analyse chart screenshots.\n"
        "- The assistant only explains and summarises. It cannot place, modify or cancel orders."
    )
