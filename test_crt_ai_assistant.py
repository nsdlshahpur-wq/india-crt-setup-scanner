"""Tests for CRT AI assistant's conservative verification rules."""
from crt_ai_assistant import verify_setup


def test_waiting_setup_is_never_marked_valid():
    row = {
        "Setup": "Wait CHoCH", "Stage": 1,
        "Monthly Status": "VALID_BULLISH_SWEEP",
        "CHoCH Date": None, "Entry Zone Type": "",
        "Entry Date": None, "Entry": float("nan"), "SL": float("nan"),
        "Target (M1 Monthly H/L)": float("nan"),
    }
    result = verify_setup(row)
    assert result["status"] != "VALID — CONFIRMED"
    assert result["passed"] < result["total"]


def test_fully_confirmed_buy_requires_all_crt_checks():
    row = {
        "Setup": "BUY", "Stage": 3,
        "Monthly Status": "VALID_BULLISH_SWEEP",
        "CHoCH Date": "2026-11-10", "CHoCH Rule": "Daily close above pivot",
        "Entry Zone Type": "FVG", "Entry Date": "2026-11-11",
        "Entry Confirmation Rule": "Bullish close above zone",
        "Entry": 100.0, "SL": 95.0, "Target (M1 Monthly H/L)": 110.0,
        "Setup Reason": "Valid sweep, CHoCH and FVG retest",
    }
    result = verify_setup(row)
    assert result["status"] == "VALID — CONFIRMED"
    assert result["passed"] == 5


def test_ambiguous_setup_is_never_trade_valid():
    row = {
        "Setup": "Ambiguous", "Stage": 6,
        "Monthly Status": "AMBIGUOUS_BOTH_SIDES_SWEPT",
        "CHoCH Date": "2026-11-10", "Entry Zone Type": "FVG",
        "Entry Date": "2026-11-11", "Entry": 100.0, "SL": 95.0,
        "Target (M1 Monthly H/L)": 110.0,
    }
    assert verify_setup(row)["status"] == "AMBIGUOUS — NO TRADE"
