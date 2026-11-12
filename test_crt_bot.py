"""Offline tests for the scheduled CRT bot universe."""
import pandas as pd

from crt_bot import build_bot_universe


def test_bot_universe_includes_nifty50_index_and_bse_equities():
    nifty = pd.DataFrame([{
        "Symbol": "^NSEI", "Name": "NIFTY 50", "Type": "Index",
        "Exchange": "NSE/BSE", "Category": "Index", "DataAvailable": True,
    }])
    bse = pd.DataFrame([{
        "Symbol": "RELIANCE.BO", "Name": "Reliance Industries", "Type": "Stock",
        "Exchange": "BSE", "Category": "Equity", "DataAvailable": True,
    }])
    universe = build_bot_universe(nifty, bse)
    assert set(universe["Symbol"]) == {"^NSEI", "RELIANCE.BO"}
    assert (universe["Exchange"] == "BSE").any()
    assert universe["Symbol"].is_unique
