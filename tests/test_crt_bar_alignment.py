"""Regression tests for NSE-aligned CRT candle boundaries."""
import pandas as pd

from mtf_analysis import _bar_close_time, resample_ohlc


def test_intraday_4h_final_partial_candle_closes_at_nse_close():
    stamp = pd.Timestamp("2026-11-26 13:15:00")
    assert _bar_close_time(stamp, "4H") == pd.Timestamp("2026-11-26 15:30:00")


def test_intraday_4h_first_candle_uses_four_hours():
    stamp = pd.Timestamp("2026-11-26 09:15:00")
    assert _bar_close_time(stamp, "4H") == pd.Timestamp("2026-11-26 13:15:00")


def test_daily_and_weekly_candles_use_nse_session_close():
    daily = pd.Timestamp("2026-11-26 00:00:00")
    weekly = pd.Timestamp("2026-11-23 00:00:00")
    assert _bar_close_time(daily, "Daily") == pd.Timestamp("2026-11-26 15:30:00")
    assert _bar_close_time(weekly, "Weekly") == pd.Timestamp("2026-11-27 15:30:00")


def test_4h_resampling_starts_at_nse_open():
    index = pd.date_range("2026-11-26 09:15", periods=7, freq="1h")
    frame = pd.DataFrame(
        {"Open": range(100, 107), "High": range(101, 108),
         "Low": range(99, 106), "Close": range(100, 107)},
        index=index,
    )
    result = resample_ohlc(frame, "4h")
    assert list(result.index) == [
        pd.Timestamp("2026-11-26 09:15"),
        pd.Timestamp("2026-11-26 13:15"),
    ]
