"""Tests for post-sweep M2/M3 Daily CHoCH reference and visible waiting state."""
import numpy as np
import pandas as pd

from scanner import ScanConfig, _find_m3_choch, scan_symbol


def _rows():
    dates = pd.to_datetime([
        "2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29",
        "2026-10-30", "2026-11-02", "2026-11-03", "2026-11-04",
    ])
    return pd.DataFrame(
        [
            [92, 96, 80, 91],    # M2 sweep candle
            [92, 100, 90, 97],
            [97, 112, 96, 110],  # post-sweep swing high
            [105, 108, 99, 102],  # confirms pivot high at prior bar
            [100, 106, 98, 104],
            [108, 115, 107, 113], # M3 daily close breaks 112
            [112, 116, 110, 114],
            [114, 117, 112, 115],
        ],
        index=dates,
        columns=["Open", "High", "Low", "Close"],
        dtype=float,
    )


def test_m3_choch_can_break_confirmed_post_sweep_pivot_formed_in_m2():
    data = _rows()
    result = _find_m3_choch(
        data, m3_start=5, sweep_index=0, last_index=7,
        direction=1, config=ScanConfig(pivot_left=1, pivot_right=1),
    )
    assert result["index"] == 5
    assert result["reference_level"] == 112.0
    assert result["pivot_date"] == "2026-10-28"


def test_waiting_choch_exposes_latest_reference_pivot_without_future_lookahead():
    data = _rows()
    data.loc[data.index[5], "Close"] = 110.0
    data.loc[data.index[6], "Close"] = 111.0
    data.loc[data.index[7], "Close"] = 109.0
    result = _find_m3_choch(
        data, m3_start=5, sweep_index=0, last_index=7,
        direction=1, config=ScanConfig(pivot_left=1, pivot_right=1),
    )
    assert result["index"] is None
    assert result["reference_level"] == 112.0
    assert result["pivot_date"] == "2026-10-28"


def test_pivot_confirmed_before_sweep_is_not_used_for_m3_choch():
    dates = pd.to_datetime([
        "2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29",
        "2026-10-30", "2026-11-02", "2026-11-03", "2026-11-04",
    ])
    data = pd.DataFrame(
        [
            [100, 105, 99, 102],
            [102, 112, 100, 110], # pivot high is before the sweep
            [108, 109, 101, 105],
            [100, 103, 98, 99],   # sweep candle
            [99, 102, 97, 100],
            [100, 111, 99, 108],
            [108, 110, 100, 107],
            [107, 109, 101, 108],
        ],
        index=dates,
        columns=["Open", "High", "Low", "Close"],
        dtype=float,
    )
    result = _find_m3_choch(
        data, m3_start=5, sweep_index=3, last_index=7,
        direction=1, config=ScanConfig(pivot_left=1, pivot_right=1),
    )
    assert result["index"] is None
    assert np.isnan(result["reference_level"])


def test_sweep_date_is_present_even_when_choch_is_still_waiting():
    dates = pd.bdate_range("2026-07-01", "2026-11-09")
    data = pd.DataFrame(
        {"Open": 99.0, "High": 105.0, "Low": 95.0, "Close": 100.0},
        index=dates,
    )
    september = data.index[data.index.month == 9]
    data.loc[september[0], "High"] = 110.0
    data.loc[september[1], "Low"] = 90.0

    october = data.index[data.index.month == 10]
    sweep_day = october[7]
    data.loc[sweep_day, ["Open", "High", "Low", "Close"]] = [96.0, 101.0, 85.0, 98.0]

    result = scan_symbol("TEST.NS", "Test", data, ScanConfig())
    assert result is not None
    assert result["Bias"] == "Bullish"
    assert result["Setup"] == "Wait CHoCH"
    assert result["Sweep Date"] == sweep_day.date().isoformat()
    assert result["CHoCH Reference Level"] is not None
