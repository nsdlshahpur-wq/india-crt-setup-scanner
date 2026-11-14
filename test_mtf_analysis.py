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



def _ohlc(rows, dates):
    return pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"], index=pd.to_datetime(dates))


def test_crt_m1_m2_are_marked_on_crt_timeframe_and_bull_sweep_reclaim():
    from mtf_analysis import _analyze_pair_with_monthly_crt_rules

    higher = _ohlc(
        [
            [100, 108, 96, 103],
            [101, 110, 95, 104],  # M1 CRT range
            [102, 106, 90, 100],  # M2 sweeps M1 low and closes inside range
            [100, 105, 98, 102],  # current/forming next CRT candle
        ],
        ["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01"],
    )
    dates = pd.date_range("2026-04-01", periods=45, freq="D")
    lower = _ohlc([[100, 101, 99, 100]] * len(dates), dates)
    result = _analyze_pair_with_monthly_crt_rules(higher, lower)

    assert result["m1_high"] == 110.0
    assert result["m1_low"] == 95.0
    assert result["m2_low"] == 90.0
    assert result["htf_sweep"] == "BULL SWEEP"
    assert result["sweep_direction"] == "BULLISH"
    assert result["stop_loss"] == 90.0
    assert result["target"] == 110.0
    assert result["entry_status"] == "WAIT CHoCH"


def test_crt_rejects_m2_close_outside_full_m1_range():
    from mtf_analysis import _analyze_pair_with_monthly_crt_rules

    higher = _ohlc(
        [
            [100, 108, 96, 103],
            [101, 110, 95, 104],
            [102, 106, 90, 92],  # swept low but did not reclaim inside range
            [100, 105, 98, 102],
        ],
        ["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01"],
    )
    dates = pd.date_range("2026-04-01", periods=45, freq="D")
    lower = _ohlc([[100, 101, 99, 100]] * len(dates), dates)
    result = _analyze_pair_with_monthly_crt_rules(higher, lower)

    assert result["htf_sweep"] == "SWEEP WITHOUT FULL-RANGE RECLAIM"
    assert result["entry_status"] == "WAIT"


def test_crt_rejects_m2_double_sweep():
    from mtf_analysis import _analyze_pair_with_monthly_crt_rules

    higher = _ohlc(
        [
            [100, 108, 96, 103],
            [101, 110, 95, 104],
            [102, 112, 90, 100],  # both M1 sides swept
            [100, 105, 98, 102],
        ],
        ["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01"],
    )
    dates = pd.date_range("2026-04-01", periods=45, freq="D")
    lower = _ohlc([[100, 101, 99, 100]] * len(dates), dates)
    result = _analyze_pair_with_monthly_crt_rules(higher, lower)

    assert result["htf_sweep"] == "DOUBLE SWEEP — REJECTED"
    assert result["entry_status"] == "REJECTED"
