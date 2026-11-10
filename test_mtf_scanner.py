"""Offline tests for multi-timeframe CRT validity marking."""
import pandas as pd

from mtf_scanner import _find_sweep


def _ohlc(rows):
    index = pd.date_range("2026-10-01", periods=len(rows), freq="D", tz="Asia/Kolkata")
    return pd.DataFrame(rows, index=index, columns=["Open", "High", "Low", "Close"])


def test_valid_sell_side_sweep_is_detected():
    frame = _ohlc([
        [105, 110, 100, 106],
        [106, 111, 101, 107],
        [107, 112, 102, 108],
        [103, 109, 98, 104],  # sweeps prior low 102 and closes back above it
    ])
    result = _find_sweep(frame, "Daily")
    assert result is not None
    assert result["direction"] == 1
    assert result["invalidated"] is False


def test_sweep_closed_through_later_is_invalid():
    frame = _ohlc([
        [105, 110, 100, 106],
        [106, 111, 101, 107],
        [107, 112, 100, 108],
        [103, 109, 98, 102],  # valid bullish sweep of previous low 100
        [97, 107, 96, 97],    # later close below sweep low invalidates it
    ])
    result = _find_sweep(frame, "Daily")
    assert result is not None
    assert result["direction"] == 1
    assert result["invalidated"] is True


def test_no_sweep_returns_none():
    frame = _ohlc([
        [100, 105, 99, 104],
        [104, 106, 100, 105],
        [105, 107, 101, 106],
        [106, 108, 102, 107],
    ])
    assert _find_sweep(frame, "Daily") is None
