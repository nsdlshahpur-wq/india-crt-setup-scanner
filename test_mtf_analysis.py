"""Unit tests for HTF-to-LTF CRT confirmation logic."""
import pandas as pd

from mtf_analysis import _sweep_mss


def candles(rows):
    return pd.DataFrame(
        rows,
        columns=["Open", "High", "Low", "Close"],
        index=pd.date_range("2026-01-01", periods=len(rows), freq="D"),
    )


def test_bullish_sweep_and_mss_is_confirmed():
    frame = candles([
        [100, 105, 98, 102],
        [102, 106, 97, 106],  # completed bar sweeps low and closes above prior high
        [106, 108, 104, 107],  # newest bar excluded
    ])
    result = _sweep_mss(frame)
    assert result["direction"] == 1
    assert result["sweep"] == "BULL SWEEP"
    assert result["mss"] == "BULL MSS"


def test_bearish_sweep_and_mss_is_confirmed():
    frame = candles([
        [100, 105, 98, 102],
        [102, 106, 97, 97],  # both extremes swept; bearish close below prior low
        [97, 99, 95, 96],
    ])
    result = _sweep_mss(frame)
    assert result["direction"] == -1
    assert result["mss"] == "BEAR MSS"


def test_sweep_without_displacement_is_not_mss():
    frame = candles([
        [100, 105, 98, 102],
        [102, 104, 97, 101],  # reclaims prior low but does not break prior high
        [101, 106, 100, 104],
    ])
    result = _sweep_mss(frame)
    assert result["direction"] == 0
    assert result["sweep"] == "BULL SWEEP"
    assert result["mss"] == "NO"


def test_insufficient_data_is_unavailable():
    result = _sweep_mss(pd.DataFrame())
    assert result["direction"] == 0
    assert result["sweep"] == "NO DATA"
