import pandas as pd

from cisd_scanner import (
    CISDConfig, _rr_target, find_day_setup, resample_1m_to_5m
)


def test_rr_filter_requires_previous_liquidity_beyond_three_r():
    target, risk = _rr_target(112.0, 98.0, 160.0, "LONG", 3.0)
    assert risk == 14.0
    assert target == 154.0
    rejected, _ = _rr_target(112.0, 98.0, 130.0, "LONG", 3.0)
    assert rejected is None


def test_bullish_cisd_fvg_retest_entry_uses_next_bar_open():
    idx = pd.date_range("2026-01-05 09:15", periods=8, freq="5min")
    day = pd.DataFrame(
        {
            "Open":  [110, 109, 107, 101, 111, 113, 112, 113],
            "High":  [111, 110, 108, 112, 114, 114, 115, 114],
            "Low":   [108, 106,  99, 101, 112, 110, 111, 112],
            "Close": [109, 107, 101, 111, 113, 112.5, 113, 113.5],
        }, index=idx
    )
    setup = find_day_setup(
        day, previous_high=160, previous_low=100,
        config=CISDConfig(rr=3, stop_buffer_points=1, min_bars_after_open=2)
    )
    assert setup is not None
    assert setup["side"] == "LONG"
    assert setup["cisd_line"] == 110
    assert setup["entry_time"] == idx[7]
    assert setup["entry"] == 113
    assert setup["stop"] == 98
    assert setup["target"] == 158


def test_resample_aligns_to_nse_0915_session():
    idx = pd.date_range("2026-01-05 09:15", periods=10, freq="min")
    one_min = pd.DataFrame(
        {"Open": range(100, 110), "High": range(101, 111),
         "Low": range(99, 109), "Close": range(100, 110)},
        index=idx
    )
    five = resample_1m_to_5m(one_min)
    assert len(five) == 2
    assert five.index[0] == pd.Timestamp("2026-01-05 09:15")
    assert five.index[1] == pd.Timestamp("2026-01-05 09:20")
