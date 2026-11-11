from __future__ import annotations

import pandas as pd
import streamlit as st

from ai_assistant import filter_strong_crt_setups, generate_market_answer

st.set_page_config(page_title="AI Strong CRT Filter", page_icon="🧠", layout="wide")
st.title("🧠 AI Strong CRT Filter")
st.caption("AI validates scanner candidates using only your CRT checklist. Monthly (1M) liquidity context + Daily (1D) structure only.")

with st.sidebar:
    provider = st.selectbox("AI provider", ["OpenAI", "Gemini", "Groq"])
    model_default = "gpt-5.5" if provider == "OpenAI" else ("gemini-2.5-flash" if provider == "Gemini" else "openai/gpt-oss-20b")
    model = st.text_input("Model ID", model_default)
try:
    secrets_ai = st.secrets.get("ai", {})
    secret_name = "openai_api_key" if provider == "OpenAI" else ("gemini_api_key" if provider == "Gemini" else "groq_api_key")
    api_key = str(secrets_ai.get(secret_name, ""))
except Exception:
    secret_name = "openai_api_key" if provider == "OpenAI" else ("gemini_api_key" if provider == "Gemini" else "groq_api_key")
    api_key = ""

if not api_key:
    st.warning(f"{provider} API key नहीं मिली। Streamlit App settings → Secrets में यह जोड़ें:")
    st.code(f'[ai]\n{secret_name} = "YOUR_API_KEY"', language="toml")
else:
    st.success(f"{provider} API key found in Streamlit secrets.")

with st.sidebar:
    if st.button("🔌 Test AI connection", key="test_crt_ai_connection", disabled=not bool(api_key.strip())):
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

results = st.session_state.get("scan_results")
if not isinstance(results, pd.DataFrame) or results.empty:
    st.info("पहले मुख्य Scanner में Scan market चलाएँ। उसके बाद यहाँ AI CRT filter चलाएँ।")
    st.stop()

stage = results["Stage"] if "Stage" in results else pd.Series(0, index=results.index)
setup = results["Setup"] if "Setup" in results else pd.Series("", index=results.index)
candidates_df = results[(stage == 3) & setup.isin(["BUY", "SELL"])].copy()

st.metric("Scanner-confirmed CRT candidates", len(candidates_df))
st.markdown(
    "**AI की जाँच:** Monthly (1M) liquidity sweep/reclaim → Daily (1D) CHoCH → "
    "same-direction FVG retest → sweep-candle SL → opposite Monthly liquidity target. "
    "IFVG, OB, RSI, MACD, EMA या कोई अन्य अतिरिक्त filter नहीं।"
)
if candidates_df.empty:
    st.warning("अभी कोई Stage 3 BUY/SELL candidate नहीं है। अधूरे setups को Strong CRT नहीं माना जाएगा।")
else:
    st.dataframe(candidates_df, use_container_width=True, hide_index=True)
    if st.button("🧠 AI से Strong Bullish / Bearish CRT छँटवाएँ", type="primary", disabled=not bool(api_key)):
        cols = [
            "Symbol", "Name", "Bias", "Stage", "Setup", "LTP", "Entry", "SL",
            "Target (M1 Monthly H/L)", "M1 High", "M1 Low", "M2 High", "M2 Low",
            "M2 Close", "Sweep Date", "Sweep Candle High", "Sweep Candle Low",
            "CHoCH Date", "Entry Date", "Zone Low", "Zone High", "Last Candle",
        ]
        rows = candidates_df[[col for col in cols if col in candidates_df.columns]].astype(object).where(pd.notna(candidates_df[[col for col in cols if col in candidates_df.columns]]), None).to_dict("records")
        try:
            with st.spinner(f"{provider} आपके CRT नियमों से {len(rows)} candidates validate कर रहा है..."):
                result = filter_strong_crt_setups(provider, api_key, rows, model)
            st.session_state["ai_crt_filter_result"] = result
            st.session_state["ai_crt_filter_run_symbols"] = [row["Symbol"] for row in rows]
        except Exception as exc:
            detail = str(exc).replace(api_key, "[hidden API key]")[:500]
            st.error(f"AI CRT filtering failed ({type(exc).__name__}): {detail}")

filtered = st.session_state.get("ai_crt_filter_result")
if filtered:
    st.divider()
    st.subheader("AI validated Strong CRT setups")
    st.write(filtered.get("summary", ""))
    approved = filtered.get("approved", [])
    if approved:
        st.success(f"{len(approved)} Strong CRT setup(s) approved by AI.")
        st.dataframe(pd.DataFrame(approved), use_container_width=True, hide_index=True)
    else:
        st.info("AI ने कोई setup Strong CRT के रूप में approve नहीं किया।")
    rejected = filtered.get("rejected", [])
    if rejected:
        with st.expander(f"Rejected / incomplete CRT ({len(rejected)})"):
            st.dataframe(pd.DataFrame(rejected), use_container_width=True, hide_index=True)

with st.expander("महत्वपूर्ण सीमा"):
    st.write(
        "AI केवल scanner के Stage 3 BUY/SELL candidates validate करता है; यह पूरे बाजार को अपने-आप scan नहीं करता। "
        "AI की राय गलत हो सकती है; यह guaranteed signal या order execution नहीं है। "
        "Yahoo Finance OHLC data को TradingView / broker chart पर verify करें।"
    )
