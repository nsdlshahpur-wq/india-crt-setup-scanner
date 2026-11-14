from __future__ import annotations

import json
import pandas as pd
import streamlit as st

st.set_page_config(page_title="CRT ChatGPT Assistant", page_icon="🤖", layout="wide")
st.title("🤖 CRT ChatGPT Assistant")
st.caption("ChatGPT Go के साथ बिना OpenAI API खर्च के CRT Scanner डेटा का विश्लेषण")

SYSTEM_PROMPT = """आप India CRT Setup Scanner के विशेषज्ञ विश्लेषक हैं।
मुख्यतः सरल हिंदी में उत्तर दें और आवश्यक trading terms अंग्रेज़ी में रखें।
केवल दिए गए Scanner Data के आधार पर वर्तमान setup, price, signal और metrics पर निष्कर्ष दें।
डेटा अनुपलब्ध हो तो स्पष्ट कहें; कोई price, signal या metric न गढ़ें।
Stage-3 के confirmed BUY/SELL को waiting, stale या rejected setup से अलग रखें।
CRT logic: M1 liquidity range, M2 sweep/reclaim, paired-timeframe CHoCH,
FVG/IFVG/OB/BOB retest और confirmation को क्रम से समझाएँ।
Yahoo Finance डेटा delayed/incomplete हो सकता है। यह research/education है,
investment advice नहीं। कोई trade execute न करें और लाभ की गारंटी न दें।
"""

def frame_context(key: str, label: str, limit: int = 250) -> str:
    frame = st.session_state.get(key)
    if not isinstance(frame, pd.DataFrame):
        return f"{label}: इस session में उपलब्ध नहीं।"
    if frame.empty:
        return f"{label}: 0 rows (खाली परिणाम)।"
    sample = frame.head(limit)
    return (
        f"{label}: कुल {len(frame)} rows; नीचे पहले {len(sample)} rows हैं.\n"
        + sample.to_json(orient="records", date_format="iso", force_ascii=False)
    )

def build_context() -> str:
    parts = [
        "DAILY SCAN METADATA: "
        f"scan_time={st.session_state.get('scan_time', 'not available')}; "
        f"universe={st.session_state.get('scan_universe_count', 'not available')}; "
        f"data_received={st.session_state.get('scan_data_count', 'not available')}; "
        f"errors={st.session_state.get('scan_error_count', 'not available')}.",
        frame_context("scan_results", "Daily scanner results", 300),
        frame_context("crt_mtf_results", "Selected-symbol MTF results", 300),
        frame_context("crt_multi_screener_results", "Multi-symbol screener", 400),
    ]
    report = st.session_state.get("crt_ensemble_report")
    if report:
        parts.append("Historical ML validation report: " + json.dumps(report, ensure_ascii=False, default=str)[:10000])
    errors = st.session_state.get("scan_errors", {})
    if errors:
        parts.append("Data errors: " + json.dumps(dict(list(errors.items())[:80]), ensure_ascii=False, default=str))
    try:
        from market_intelligence import build_market_snapshot
        price_map = st.session_state.get("scan_price_map", {})
        daily = st.session_state.get("scan_results")
        snapshot = build_market_snapshot(
            price_map,
            daily if isinstance(daily, pd.DataFrame) else None,
            st.session_state.get("crt_multi_screener_results"),
        )
        parts.append("Rule-based market breadth snapshot: " + str(snapshot)[:12000])
    except Exception as exc:
        parts.append(f"Market breadth snapshot unavailable: {type(exc).__name__}: {str(exc)[:150]}")
    return "\n\n".join(parts)

st.info(
    "यह Free handoff mode है: OpenAI API Key या API billing की जरूरत नहीं। "
    "आपका Scanner डेटा एक prompt में तैयार होगा; ChatGPT में भेजने के लिए आपको स्वयं Copy/Paste करना होगा।"
)

st.markdown(
    "### इस्तेमाल कैसे करें?\n"
    "1. पहले Dashboard में Market Scan चलाएँ। जरूरत हो तो MTF Analysis और Multi-Symbol Screener भी चलाएँ।\n"
    "2. नीचे अपना सवाल लिखें।\n"
    "3. **ChatGPT Prompt तैयार करें** दबाएँ और बने हुए prompt को Copy करें।\n"
    "4. ChatGPT खोलें, prompt Paste करें और भेजें।"
)

question = st.text_area(
    "ChatGPT से क्या विश्लेषण करवाना चाहते हैं?",
    value="आज के सभी confirmed CRT BUY/SELL setups का विश्लेषण करें। प्रत्येक setup का timeframe alignment, entry, SL, target, confirmation और risk बताएं। Waiting या stale setups को अलग रखें।",
    height=110,
    key="crt_chatgpt_question_free",
)

if st.button("🧠 ChatGPT Prompt तैयार करें", type="primary", use_container_width=True):
    context = build_context()
    prompt = (
        SYSTEM_PROMPT
        + "\n\nUSER QUESTION:\n" + question.strip()
        + "\n\nCURRENT CRT SCANNER SESSION DATA:\n" + context
    )
    st.session_state["crt_chatgpt_free_prompt"] = prompt

prompt = st.session_state.get("crt_chatgpt_free_prompt", "")
if prompt:
    st.success("आपका ChatGPT prompt तैयार है। नीचे Copy करें और ChatGPT में भेजें।")
    st.code(prompt, language="text")
    st.download_button(
        "⬇️ Prompt TXT डाउनलोड करें",
        data=prompt.encode("utf-8"),
        file_name="crt_scanner_chatgpt_prompt.txt",
        mime="text/plain",
        use_container_width=True,
    )
    st.link_button("🌐 ChatGPT खोलें", "https://chatgpt.com/", use_container_width=True)

st.divider()
st.caption(
    "नोट: यह तरीका आपके ChatGPT Go खाते का उपयोग करता है, लेकिन ChatGPT का उत्तर इस ऐप के अंदर स्वतः वापस नहीं आएगा। "
    "Scanner डेटा केवल तब prompt में शामिल होगा जब आप इस पेज पर prompt तैयार करेंगे। "
    "डेटा delayed/incomplete हो सकता है; यह निवेश सलाह या trade execution नहीं है।"
)
