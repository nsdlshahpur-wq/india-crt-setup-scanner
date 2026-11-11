"""Hard deterministic checks for AI-reviewed active CRT candidates."""
from ai_assistant import _candidate_crt_errors


def _valid_buy_candidate():
    return {
        "Symbol": "TEST.NS",
        "Setup": "BUY",
        "Stage": 3,
        "Entry Status": "TRIGGERED",
        "Target Status": "TARGET PENDING",
        "Monthly Status": "VALID_BULLISH_SWEEP",
        "Sweep Date": "2026-10-12",
        "CHoCH Date": "2026-11-03",
        "Retest Date": "2026-11-05",
        "Entry Date": "2026-11-06",
        "Entry Zone Type": "BOB",
        "Entry": 110.0,
        "SL": 78.0,
        "Target (M1 Monthly H/L)": 120.0,
        "M1 High": 120.0,
        "M1 Low": 80.0,
        "M2 Close": 100.0,
        "Sweep Candle High": 105.0,
        "Sweep Candle Low": 78.0,
        "Zone Low": 104.0,
        "Zone High": 108.0,
    }


def test_ai_guard_accepts_complete_valid_bullish_crt_candidate():
    assert _candidate_crt_errors(_valid_buy_candidate()) == []


def test_ai_guard_rejects_entry_without_post_choch_retest_sequence():
    row = _valid_buy_candidate()
    row["Retest Date"] = "2026-10-31"
    errors = _candidate_crt_errors(row)
    assert any("Date sequence" in error for error in errors)


def test_ai_guard_rejects_wrong_sweep_extreme_for_buy():
    row = _valid_buy_candidate()
    row["Sweep Candle Low"] = 82.0
    errors = _candidate_crt_errors(row)
    assert any("did not pierce M1 low" in error for error in errors)
    assert any("SL does not match" in error for error in errors)


def test_ai_guard_rejects_zone_type_outside_the_four_allowed_types():
    row = _valid_buy_candidate()
    row["Entry Zone Type"] = "ORDERBLOCK_PLUS_EMA"
    errors = _candidate_crt_errors(row)
    assert any("Entry Zone Type" in error for error in errors)


def test_ai_guard_rejects_sell_candidate_with_wrong_liquidity_target():
    row = _valid_buy_candidate()
    row.update({
        "Setup": "SELL",
        "Monthly Status": "VALID_BEARISH_SWEEP",
        "Sweep Candle High": 122.0,
        "Sweep Candle Low": 95.0,
        "SL": 122.0,
        "Entry": 90.0,
        "Target (M1 Monthly H/L)": 81.0,
        "Entry Zone Type": "IFVG",
        "Zone Low": 92.0,
        "Zone High": 96.0,
    })
    errors = _candidate_crt_errors(row)
    assert any("SELL target does not match M1 low" in error for error in errors)
