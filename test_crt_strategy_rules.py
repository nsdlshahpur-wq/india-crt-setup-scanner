"""Deterministic tests for Monthly-Daily CRT rules and the four permitted entry zones."""
import numpy as np
import pandas as pd

from scanner import (
    ScanConfig,
    _collect_entry_zones,
    _find_entry_in_zones,
    _three_month_context,
    _zone,
    _zone_is_active,
)


def _monthly_fixture():
    dates = pd.bdate_range("2026-01-01", "2026-03-31")
    frame = pd.DataFrame(
        {"Open": 100.0, "High": 105.0, "Low": 95.0, "Close": 100.0},
        index=dates,
    )
    jan = frame.index.month == 1
    feb = frame.index.month == 2
    # M1 range.
    frame.loc[frame.index[jan][0], "High"] = 110.0
    frame.loc[frame.index[jan][1], "Low"] = 90.0
    # One bullish M2 sweep; close returns to the full M1 range.
    sweep_date = frame.index[feb][5]
    frame.loc[sweep_date, ["Open", "High", "Low", "Close"]] = [96.0, 101.0, 85.0, 98.0]
    return frame, sweep_date


def _ohlc(rows):
    return pd.DataFrame(
        rows,
        columns=["Open", "High", "Low", "Close"],
        index=pd.bdate_range("2026-04-01", periods=len(rows)),
        dtype=float,
    )


def test_monthly_context_accepts_one_side_sweep_and_full_range_reclaim():
    frame, sweep_date = _monthly_fixture()
    result = _three_month_context(frame)
    assert result is not None
    assert result["monthly_status"] == "VALID_BULLISH_SWEEP"
    assert result["bias"] == 1
    assert result["m1_high"] == 110.0
    assert result["m1_low"] == 90.0
    assert result["sweep_date"] == sweep_date
    assert 90.0 < result["m2_close"] < 110.0


def test_monthly_context_rejects_m2_close_outside_full_m1_range():
    frame, _ = _monthly_fixture()
    feb_last = frame.index[frame.index.month == 2][-1]
    frame.loc[feb_last, "Close"] = 89.0
    result = _three_month_context(frame)
    assert result is not None
    assert result["monthly_status"] == "INVALID_M2_CLOSE_OUTSIDE_M1_RANGE"
    assert result["bias"] == 0


def test_monthly_context_marks_two_sided_sweep_ambiguous():
    frame, _ = _monthly_fixture()
    feb = frame.index[frame.index.month == 2]
    frame.loc[feb[8], ["Open", "High", "Low", "Close"]] = [104.0, 116.0, 100.0, 105.0]
    result = _three_month_context(frame)
    assert result is not None
    assert result["monthly_status"] == "AMBIGUOUS_BOTH_SIDES_SWEPT"
    assert result["bias"] == 0


def test_fvg_zone_is_detected_after_choch_and_retest_confirmation():
    frame = _ohlc([
        [100, 103, 99, 101],
        [101, 108, 100, 102],
        [102, 104, 101, 103],  # bullish CHoCH
        [104, 107, 103, 105],
        [105, 109, 106, 108],  # bullish FVG: Low[4] > High[2]
        [106, 109, 105, 108],  # retest + bullish close above zone
    ])
    zones = _collect_entry_zones(frame, 0, 2, 5, 1, ScanConfig())
    fvg = [zone for zone in zones if zone["type"] == "FVG"]
    assert fvg
    assert fvg[-1]["available_index"] == 4
    result = _find_entry_in_zones(frame, fvg, 1, 3)
    assert result is not None
    assert result["entry_index"] == 5
    assert result["retest_index"] == 5


def test_ifvg_flips_opposite_gap_and_waits_for_later_retest():
    frame = _ohlc([
        [101, 103, 100, 101],  # Low[0] = 100
        [100, 101, 95, 97],
        [96, 98, 92, 94],      # bearish FVG: High[2] < Low[0]
        [99, 103, 98, 102],    # bullish CHoCH and closes through gap
        [99, 104, 97, 103],    # retest zone [94, 100] and confirm above
    ])
    zones = _collect_entry_zones(frame, 0, 3, 4, 1, ScanConfig())
    ifvgs = [zone for zone in zones if zone["type"] == "IFVG"]
    assert ifvgs
    assert ifvgs[0]["available_index"] == 3
    result = _find_entry_in_zones(frame, ifvgs, 1, 3)
    assert result is not None
    assert result["entry_index"] == 4


def test_ob_uses_nearest_opposite_candle_before_choch():
    frame = _ohlc([
        [100, 103, 98, 101],
        [101, 104, 99, 102],
        [103, 105, 98, 99],   # nearest bearish candle
        [99, 108, 98, 107],   # bullish CHoCH
        [106, 109, 104, 108],
    ])
    zones = _collect_entry_zones(frame, 0, 3, 4, 1, ScanConfig())
    obs = [zone for zone in zones if zone["type"] == "OB"]
    assert len(obs) == 1
    assert obs[0]["origin_index"] == 2
    assert obs[0]["available_index"] == 3


def test_bob_requires_older_block_break_close_and_subsequent_retest():
    frame = _ohlc([
        [100, 103, 98, 101],
        [103, 105, 96, 97],   # older bearish breaker-origin candle
        [100, 103, 97, 98],   # nearest bearish candle; treated as OB, not BOB
        [98, 108, 97, 107],   # bullish CHoCH, closes above old candle high
        [106, 109, 104, 108], # later retest of old BOB range
    ])
    zones = _collect_entry_zones(frame, 0, 3, 4, 1, ScanConfig())
    bobs = [zone for zone in zones if zone["type"] == "BOB"]
    assert bobs
    assert bobs[0]["origin_index"] == 1
    assert bobs[0]["available_index"] == 3
    result = _find_entry_in_zones(frame, bobs, 1, 3)
    assert result is not None
    assert result["entry_index"] == 4


def test_entry_requires_zone_touch_then_directional_confirmation():
    frame = _ohlc([
        [100, 104, 99, 102],
        [102, 106, 101, 104],
        [104, 107, 103, 106],
        [103, 106, 102, 104],  # touch only; no close above zone high 105
        [104, 108, 103, 107],  # confirming close
    ])
    zone = _zone("FVG", 100, 105, 1, 2)
    result = _find_entry_in_zones(frame, [zone], 1, 3)
    assert result is not None
    assert result["retest_index"] == 3
    assert result["entry_index"] == 4


def test_close_through_far_edge_invalidates_zone():
    frame = _ohlc([
        [100, 105, 99, 103],
        [103, 106, 101, 104],
        [104, 107, 100, 101],
        [99, 102, 94, 98],  # closes below bullish zone low
    ])
    zone = _zone("OB", 100, 105, 1, 2)
    assert _zone_is_active(frame, zone, 1) is False
