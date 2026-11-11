from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from storage import add_trade, close_trade, list_trades

st.set_page_config(page_title="CRT Trade Journal", page_icon="📓", layout="wide")
st.title("📓 Trade Journal")
st.caption("Record Entry, SL, Target, Exit, realized P&L and R multiple. The journal does not place orders.")

with st.expander("＋ Record a new trade", expanded=True):
    with st.form("new_journal_trade", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        symbol = c1.text_input("Symbol", "RELIANCE.NS")
        side = c2.selectbox("Side", ["BUY", "SELL"])
        setup = c3.selectbox("Setup", ["Monthly-Daily CRT", "FVG Retest", "IFVG Retest", "OB Retest", "BOB Retest", "Other"])
        c4, c5, c6 = st.columns(3)
        timeframe = c4.selectbox("Timeframe", ["Monthly (1M) → Daily (1D)"])
        entry_date = c5.date_input("Entry date", value=date.today())
        quantity = c6.number_input("Quantity", min_value=1, value=1, step=1)
        c7, c8, c9 = st.columns(3)
        entry = c7.number_input("Entry price (₹)", min_value=0.01, value=100.0, step=0.05)
        sl = c8.number_input("Stop loss (₹; 0 if not set)", min_value=0.0, value=98.0, step=0.05)
        target = c9.number_input("Target (₹; 0 if not set)", min_value=0.0, value=104.0, step=0.05)
        costs = st.number_input("Estimated entry costs (₹)", min_value=0.0, value=0.0, step=1.0)
        notes = st.text_area("Setup notes / reason")
        save = st.form_submit_button("Save trade", type="primary")
        if save:
            try:
                if side == "BUY" and sl and sl >= entry:
                    st.error("BUY trade के लिए SL, entry से नीचे होना चाहिए।")
                elif side == "SELL" and sl and sl <= entry:
                    st.error("SELL trade के लिए SL, entry से ऊपर होना चाहिए।")
                else:
                    trade_id = add_trade(
                        symbol, side, setup, timeframe, entry_date.isoformat(),
                        float(entry), float(sl) if sl else None,
                        float(target) if target else None, int(quantity),
                        float(costs), notes,
                    )
                    st.success(f"Trade #{trade_id} saved.")
                    st.rerun()
            except Exception as exc:
                st.error(str(exc))

trades = list_trades()
open_trades = trades[trades["Status"] == "OPEN"] if not trades.empty else pd.DataFrame()
closed_trades = trades[trades["Status"] == "CLOSED"] if not trades.empty else pd.DataFrame()

st.divider()
st.subheader("Journal overview")
total = len(trades)
wins = int((pd.to_numeric(closed_trades["PnL"], errors="coerce") > 0).sum()) if not closed_trades.empty else 0
net = float(pd.to_numeric(closed_trades["PnL"], errors="coerce").fillna(0).sum()) if not closed_trades.empty else 0.0
m1, m2, m3, m4 = st.columns(4)
m1.metric("Total trades", f"{total:,}")
m2.metric("Open trades", f"{len(open_trades):,}")
m3.metric("Closed trades", f"{len(closed_trades):,}")
m4.metric("Realized P&L", f"₹{net:,.2f}")

if not open_trades.empty:
    st.subheader("Open trades")
    st.dataframe(open_trades, use_container_width=True, hide_index=True)
    st.subheader("Close a trade")
    choices = open_trades["ID"].astype(int).tolist()
    with st.form("close_journal_trade"):
        trade_id = st.selectbox(
            "Select open trade",
            choices,
            format_func=lambda value: (
                f"#{value} · "
                + str(open_trades.loc[open_trades["ID"] == value, "Symbol"].iloc[0])
                + " · "
                + str(open_trades.loc[open_trades["ID"] == value, "Side"].iloc[0])
            ),
        )
        exit_date = st.date_input("Exit date", value=date.today())
        exit_price = st.number_input("Exit price (₹)", min_value=0.01, value=100.0, step=0.05)
        exit_costs = st.number_input("Additional exit costs (₹)", min_value=0.0, value=0.0, step=1.0)
        close = st.form_submit_button("Save exit & calculate P&L")
        if close:
            try:
                outcome = close_trade(int(trade_id), exit_date.isoformat(), float(exit_price), float(exit_costs))
                st.success(
                    f"Closed trade #{trade_id}: Net P&L ₹{outcome['pnl']:,.2f} · "
                    f"{outcome['r_multiple']:.2f}R"
                )
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
else:
    st.info("कोई open trade नहीं है। ऊपर नया trade record करें।")

if not closed_trades.empty:
    st.subheader("Closed trades")
    st.dataframe(closed_trades, use_container_width=True, hide_index=True)
    st.download_button(
        "⬇ Download journal CSV",
        trades.to_csv(index=False).encode("utf-8-sig"),
        file_name="crt_trade_journal.csv",
        mime="text/csv",
    )
elif trades.empty:
    st.info("Trade journal अभी खाली है।")
