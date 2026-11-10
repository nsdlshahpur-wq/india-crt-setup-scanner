"""Tests for the selected CRT/entry timeframe page analysis."""
import pandas as pd
import pytest

import mtf_scanner


def _flat_ohlc(index):
    return pd.DataFrame(
        {
            "Open": [100.0] * len(index),
            "High": [101.0] * len(index),
            "Low": [99.0] * len(index),
            "Close": [100.0] * len(index),
            "Volume": [1000.0] * len(index),
        },
        index=index,
    )


def test_selected_4h_crt_uses_hourly_source_and_5m_entry(monkeypatch):
    trading_days = pd.bdate_range("2026-10-01", periods=8)
    hourly_index = pd.DatetimeIndex(
        [
            pd.Timestamp(f"{day.date()} {hour:02d}:{minute:02d}", tz="Asia/Kolkata")
            for day in trading_days
            for hour, minute in [(9, 15), (10, 15), (11, 15), (12, 15), (13, 15), (14, 15)]
        ]
    )
    five_min_index = pd.date_range(
        "2026-10-01 09:15",
        periods=8 * 75,
        freq="5min",
        tz="Asia/Kolkata",
    )
    calls = []

    def fake_download_source(ticker, interval, period):
        calls.append((ticker, interval, period))
        if interval == "60m":
            return _flat_ohlc(hourly_index)
        if interval == "5m":
            return _flat_ohlc(five_min_index)
        raise AssertionError(f"Unexpected Yahoo interval: {interval}")

    monkeypatch.setattr(mtf_scanner, "_download_source", fake_download_source)
    result, errors = mtf_scanner.analyze_timeframe_pair("RELIANCE", "4H", "5m")

    assert result["Symbol"] == "RELIANCE"
    assert result["CRT TF"] == "4H"
    assert result["Entry TF"] == "5m"
    assert result["CRT Status"] == "NO SWEEP"
    assert errors == {}
    assert ("RELIANCE.NS", "1h", "730d") in calls
    assert ("RELIANCE.NS", "5m", "60d") in calls


def test_selected_pair_rejects_unsupported_crt_timeframe():
    with pytest.raises(ValueError, match="Unsupported CRT timeframe"):
        mtf_scanner.analyze_timeframe_pair("RELIANCE", "2H", "5m")
