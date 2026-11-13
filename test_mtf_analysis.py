"""Unit tests for the Pine-style MTF dashboard status calculation."""
import pandas as pd

from mtf_analysis import _status


def candles(rows):
    return pd.DataFrame(
        rows,
        columns=["Open", "High", "Low", "Close"],
        index=pd.date_range("2026-01-01", periods=len(rows), freq="D"),
    )


def test_bullish_liquidity_sweep_is_reported():
    frame = candles([
        [100, 105, 98, 102],
        [102, 104, 97, 103],  # completed candle sweeps prior low and reclaims
        [103, 106, 101, 105],  # newest candle excluded as potentially incomplete
    ])
    result = _status(frame, "Daily")
    assert result["Liquidity Sweep"] == "BULL"
    assert result["MSS/MSB"] == "NO"
    assert result["Signal"] == "WAIT"


def test_no_sweep_is_waiting():
    frame = candles([
        [100, 105, 98, 102],
        [102, 106, 99, 104],
        [104, 107, 100, 105],
    ])
    result = _status(frame, "1H")
    assert result["Liquidity Sweep"] == "—"
    assert result["Signal"] == "WAIT"


def test_insufficient_data_is_unavailable():
    result = _status(pd.DataFrame(), "Monthly")
    assert result["Liquidity Sweep"] == "DATA UNAVAILABLE"
