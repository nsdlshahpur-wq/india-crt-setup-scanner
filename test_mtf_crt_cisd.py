import pandas as pd

from mtf_analysis import _find_15m_cisd, _find_5m_fvg_retest


def test_bullish_15m_cisd_requires_body_close_above_delivery_open():
    idx = pd.date_range("2026-10-05 09:15", periods=5, freq="15min")
    frame = pd.DataFrame(
        {
            "Open": [105, 104, 103, 104, 106],
            "High": [106, 105, 104, 107, 107],
            "Low": [103, 102, 101, 103, 105],
            "Close": [104, 103, 102, 106, 106.5],
        },
        index=idx,
    )
    result = _find_15m_cisd(frame, 1)
    assert result["confirmed"] is True
    assert result["line"] == 105
    assert result["status"] == "BULLISH CISD"


def test_bearish_15m_cisd_requires_body_close_below_delivery_open():
    idx = pd.date_range("2026-10-05 09:15", periods=5, freq="15min")
    frame = pd.DataFrame(
        {
            "Open": [100, 101, 102, 101, 99],
            "High": [102, 103, 104, 102, 100],
            "Low": [99, 100, 101, 98, 97],
            "Close": [101, 102, 103, 98, 98.5],
        },
        index=idx,
    )
    result = _find_15m_cisd(frame, -1)
    assert result["confirmed"] is True
    assert result["line"] == 100
    assert result["status"] == "BEARISH CISD"


def test_5m_fvg_retest_is_required_after_cisd():
    idx = pd.date_range("2026-10-05 10:15", periods=5, freq="5min")
    frame = pd.DataFrame(
        {
            "Open":  [100, 101, 104, 103, 104],
            "High":  [101, 103, 106, 105, 106],
            "Low":   [99, 100, 104, 102, 103],
            "Close": [100, 102, 105, 104.5, 104.5],
        },
        index=idx,
    )
    result = _find_5m_fvg_retest(frame, 1, idx[0] - pd.Timedelta(minutes=1))
    assert result["confirmed"] is True
    assert result["fvg_low"] == 101
    assert result["fvg_high"] == 104
    assert result["entry"] == 104.5
