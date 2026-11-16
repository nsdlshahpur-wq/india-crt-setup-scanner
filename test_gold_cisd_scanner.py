import io
import pytest

from gold_cisd_scanner import load_gold_ohlc_csv


def test_load_tradingview_style_csv():
    csv = """time,open,high,low,close,volume
2026-01-01 09:00:00,10,12,9,11,100
2026-01-01 09:15:00,11,13,10,12,120
"""
    frame, report = load_gold_ohlc_csv(io.StringIO(csv))
    assert list(frame.columns) == ["Open", "High", "Low", "Close"]
    assert len(frame) == 2
    assert report["rows"] == 2


def test_invalid_ohlc_rejected():
    csv = """time,open,high,low,close
2026-01-01 09:00:00,10,8,9,11
"""
    with pytest.raises(ValueError, match="valid OHLC candles"):
        load_gold_ohlc_csv(io.StringIO(csv))


def test_missing_columns_rejected():
    csv = """time,open,high
2026-01-01 09:00:00,10,12
"""
    with pytest.raises(ValueError, match="columns chahiye"):
        load_gold_ohlc_csv(io.StringIO(csv))
