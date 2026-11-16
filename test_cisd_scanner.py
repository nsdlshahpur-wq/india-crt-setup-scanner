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


def test_crt_models_include_all_four_requested_timeframes():
    from cisd_scanner import CRT_MODELS
    assert [x["name"] for x in CRT_MODELS] == ["1H", "4H", "Daily", "Weekly"]


def test_daily_crt_resampling_builds_one_bar_per_session():
    from cisd_scanner import _resample_crt_bars
    idx = pd.date_range("2026-01-05 09:15", periods=12, freq="5min")
    frame = pd.DataFrame({
        "Open": [100] * 12, "High": range(101, 113),
        "Low": [99] * 12, "Close": [100] * 12,
    }, index=idx)
    daily = _resample_crt_bars(frame, "1D")
    assert len(daily) == 1
    assert float(daily.iloc[0].High) == 112.0


def test_new_backtest_returns_metrics_when_history_has_no_setup():
    from cisd_scanner import backtest_crt_cisd
    idx = pd.date_range("2026-01-05 09:15", periods=60, freq="5min")
    frame = pd.DataFrame({
        "Open": [100.0] * len(idx), "High": [101.0] * len(idx),
        "Low": [99.0] * len(idx), "Close": [100.0] * len(idx),
    }, index=idx)
    trades, metrics = backtest_crt_cisd(frame, CISDConfig())
    assert trades.empty
    assert metrics["total_trades"] == 0


def test_crt_entry_timeframe_alignment_matches_user_mapping():
    from cisd_scanner import CRT_MODELS
    mapping = {item["name"]: item["entry_label"] for item in CRT_MODELS}
    assert mapping == {"1H": "5M", "4H": "15M", "Daily": "30M", "Weekly": "1H"}


def test_zone_engine_exposes_all_four_retest_zone_types():
    from cisd_scanner import _zone_candidates
    idx = pd.date_range("2026-01-05 09:15", periods=20, freq="5min")
    # Mixed candle sequence provides opposing FVGs and displacement/OB candidates.
    frame = pd.DataFrame({
        "Open":  [100, 99, 98, 101, 104, 103, 105, 102, 101, 104,
                  106, 105, 108, 107, 110, 109, 111, 108, 107, 110],
        "High":  [101, 100, 99, 103, 106, 105, 107, 104, 103, 106,
                  108, 107, 110, 109, 112, 111, 113, 110, 109, 112],
        "Low":   [98, 97, 96, 100, 103, 102, 104, 100, 99, 103,
                  105, 104, 107, 106, 109, 108, 110, 106, 105, 109],
        "Close": [99, 98, 97, 102, 105, 104, 106, 101, 100, 105,
                  107, 106, 109, 108, 111, 110, 112, 107, 106, 111],
    }, index=idx)
    zones = _zone_candidates(frame, 1, idx[0])
    assert {z["type"] for z in zones}.issubset({"FVG", "IFVG", "OB", "Advanced OB"})
