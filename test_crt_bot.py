"""Offline tests for the scheduled CRT bot universe."""
from crt_bot import build_bot_universe


def test_bot_universe_includes_nifty50_index_and_bse_equities():
    universe = build_bot_universe()
    assert not universe.empty
    nifty = universe[universe["Symbol"] == "^NSEI"]
    assert len(nifty) == 1
    assert "NIFTY 50" in str(nifty.iloc[0]["Name"]).upper()
    assert (universe["Exchange"] == "BSE").any()
    assert universe["Symbol"].is_unique
