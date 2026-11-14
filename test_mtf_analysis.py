"""Offline tests for the current MTF sweep/MSS helper."""
import pandas as pd
from mtf_analysis import _sweep_and_mss


def candles(rows):
    return pd.DataFrame(
        rows,
        columns=["Open", "High", "Low", "Close"],
        index=pd.date_range("2026-01-01", periods=len(rows), freq="D"),
    )


def test_empty_data_returns_no_data():
    result = _sweep_and_mss(pd.DataFrame())
    assert result["direction"] == 0
    assert result["sweep"] == "NO DATA"
    assert result["mss"] == "—"


def test_insufficient_completed_history_does_not_create_signal():
    frame = candles([[100, 105, 98, 102]] * 10)
    result = _sweep_and_mss(frame)
    assert result["direction"] == 0
    assert result["sweep"] == "NO DATA"
    assert result["mss"] == "—"


def test_latest_potentially_forming_candle_is_excluded():
    rows = [[100, 101, 99, 100] for _ in range(20)]
    rows[-2] = [100, 102, 98, 100]
    rows[-1] = [100, 120, 80, 110]
    result = _sweep_and_mss(candles(rows))
    assert result["close"] == 100.0
    assert result["time"] == "19-Jan-2026 00:00"
    assert result["direction"] == 0


def test_no_sweep_is_reported_without_fabricating_direction():
    frame = candles([[100, 101, 99, 100] for _ in range(24)])
    result = _sweep_and_mss(frame)
    assert result["direction"] == 0
    assert result["sweep"] == "—"
    assert result["mss"] == "NO"
