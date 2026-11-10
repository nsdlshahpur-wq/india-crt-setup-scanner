from __future__ import annotations

import streamlit as st

from broker_connect import broker_is_configured, check_broker_profile

st.set_page_config(page_title="Multiple Broker Connections", page_icon="🔌", layout="wide")
st.title("🔌 Multiple Broker Connections")
st.caption("Connect and verify several broker profiles from one dashboard. This module is read-only: it does not send, modify or cancel orders.")

BROKERS = [
    ("zerodha", "Zerodha Kite", "https://developers.kite.trade/signup", "api_key + access_token"),
    ("upstox", "Upstox", "https://upstox.com/developer/apps", "OAuth access_token"),
    ("dhan", "DhanHQ", "https://web.dhan.co/", "client_id + access_token"),
]

st.info(
    "Credentials are read only from Streamlit Secrets. They are not saved in the app database and are never printed on screen. "
    "Never commit secrets.toml or API tokens to GitHub."
)

results = st.session_state.get("broker_profile_results", {})
cols = st.columns(3)
for idx, (key, label, setup_url, fields) in enumerate(BROKERS):
    with cols[idx]:
        configured = broker_is_configured(key)
        st.subheader(label)
        st.caption(fields)
        if configured:
            st.success("Credentials configured")
        else:
            st.warning("Not configured")
        if st.button(f"Test {label} profile", key=f"test_{key}"):
            ok, message = check_broker_profile(key)
            results[key] = {"ok": ok, "message": message}
            st.session_state["broker_profile_results"] = results
        current = results.get(key)
        if current:
            if current["ok"]:
                st.success(current["message"])
            else:
                st.error(current["message"])
        st.link_button("Open broker developer portal", setup_url)

st.divider()
st.subheader("Secrets configuration")
st.write("Streamlit app → Settings → Secrets में अपने broker के लिए केवल वही sections भरें जिन्हें connect करना है.")
st.code(
    '''[brokers.zerodha]
api_key = "YOUR_KITE_API_KEY"
access_token = "YOUR_KITE_ACCESS_TOKEN"

[brokers.upstox]
access_token = "YOUR_UPSTOX_ACCESS_TOKEN"

[brokers.dhan]
client_id = "YOUR_DHAN_CLIENT_ID"
access_token = "YOUR_DHAN_ACCESS_TOKEN"''',
    language="toml",
)

with st.expander("Supported scope and limitations"):
    st.markdown(
        "- Zerodha, Upstox और DhanHQ के लिए read-only profile verification उपलब्ध है.\n"
        "- Upstox uses OAuth access tokens; generate them from the broker's official login flow.\n"
        "- Dhan tokens may expire and need renewal from the broker's official process.\n"
        "- Angel One SmartAPI और FYERS के cards अगली integration phase में जोड़े जा सकते हैं; इस build में उनके API calls active नहीं हैं.\n"
        "- Scanner अभी Yahoo Finance candles पर चलता है. Broker profile connected दिखने का अर्थ यह नहीं कि live/historical broker data scanner में switch हो गया है.\n"
        "- कोई order execution, position modification, funds transfer या automated trading implemented नहीं है."
    )

st.caption("Choose broker access only for your own accounts. Use read-only access unless you deliberately authorise additional capabilities in a later version.")
