from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Monthly-Daily CRT Rulebook", page_icon="🧭", layout="wide")
st.title("🧭 Monthly (1M) → Daily (1D) CRT Rulebook")
st.caption("यह strategy केवल दो timeframes पर आधारित है। अन्य timeframe pairs इस Scanner में disabled हैं।")

st.subheader("1. Monthly CRT Context")
st.markdown(
    "- **M1:** Previous completed month का High और Low।\n"
    "- **M2:** M1 High या Low में से केवल एक तरफ liquidity sweep हो।\n"
    "- Sweep candle वापस M1 की पूरी High–Low range के अंदर close हो।\n"
    "- यदि M2 में दोनों तरफ sweep हो, तो उसे Ambiguous माना जाएगा।\n"
    "- **M3:** Current month के Daily candles पर structure और entry खोजी जाएगी।"
)

st.subheader("2. Daily Entry Model")
st.markdown(
    "M2 के valid sweep/reclaim direction में Daily CHoCH की पुष्टि के बाद Entry Zones खोजे जाएँगे। "
    "FVG, IFVG, OB या BOB में से किसी एक का retest पर्याप्त हो सकता है। सभी चार zones का एक साथ होना जरूरी नहीं है।"
)
st.markdown(
    "- **FVG:** Directional three-candle imbalance।\n"
    "- **IFVG:** Opposite FVG का close-through के बाद directional flip।\n"
    "- **OB:** CHoCH break से पहले का nearest opposite-colour candle।\n"
    "- **BOB:** पुराना opposing block पहले टूटे और फिर उसकी दूसरी boundary के पार close देकर breaker बने।"
)

st.subheader("3. Entry, Stop Loss और Target")
st.markdown(
    "- Zone के retest के बाद उसी direction में confirming Daily candle close आवश्यक है।\n"
    "- **BUY SL:** वास्तविक Monthly sweep candle का Low।\n"
    "- **SELL SL:** वास्तविक Monthly sweep candle का High।\n"
    "- **BUY Target:** M1 High liquidity।\n"
    "- **SELL Target:** M1 Low liquidity।\n"
    "- Active Entry तभी है जब Entry trigger हो चुकी हो और Target अभी बाकी हो।\\n"
    "- **Fresh Entry:** केवल latest completed Daily candle पर confirm हुआ setup BUY/SELL रहेगा।\\n"
    "- यदि Entry किसी पुरानी Daily candle पर confirm हुई थी और उसके बाद SL/Target नहीं लगा, तो उसे **Missed Entry - No Fresh Entry** दिखाएँगे; उस पुराने भाव पर नया trade signal नहीं देंगे।"
)

st.subheader("4. Scanner Status")
st.markdown(
    "- **Wait CHoCH:** Monthly sweep सही है, Daily structure break बाकी है।\n"
    "- **Wait FVG/IFVG/OB/BOB:** CHoCH मिला, usable entry zone अभी नहीं मिला।\n"
    "- **Wait Retest:** Zone मिला, retest/confirmation बाकी है।\n"
    "- **BUY / SELL:** Entry trigger हुई है, Target pending है।\n"
    "- **Target Hit / Stop Loss Hit:** Entry के बाद संबंधित level hit हुआ।\n"
    "- **Ambiguous:** एक Daily candle में SL और Target दोनों touch हुए या Monthly दोनों तरफ sweep हुआ।\n"
    "- **Target Passed Before Entry:** confirmation के समय ही target पीछे छूट चुका था।"
)

st.warning(
    "FVG/IFVG/OB/BOB की mechanical OHLC definitions code में स्पष्ट की गई हैं। "
    "Trading से पहले अपने chart पर zones और candle sequence verify करें। Yahoo Finance data delayed या incomplete हो सकता है।"
)
