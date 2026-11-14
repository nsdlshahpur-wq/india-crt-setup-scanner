"""Regression tests for the Monthly CRT -> Daily multi-symbol scanner."""
import pandas as pd
import multi_symbol_scanner as multi


def test_display_row_exposes_monthly_daily_flow_and_trade_levels():
    source = {
        "Bias": "Bullish", "Setup": "BUY", "LTP": 105.0, "Entry": 104.0,
        "SL": 98.0, "Target (M1 Monthly H/L)": 116.0,
        "Sweep Type": "Sell-Side Liquidity Sweep (SSS)",
        "CHoCH Rule": "Daily close above confirmed pivot 102.0",
        "Entry Zone Type": "FVG", "Monthly Status": "VALID_BULLISH_SWEEP",
        "Sweep Date": "2026-10-12", "CHoCH Date": "2026-11-03",
        "Retest Date": "2026-11-06", "Entry Date": "2026-11-07",
        "Entry Status": "TRIGGERED", "Target Status": "TARGET PENDING",
        "Setup Reason": "Daily FVG retest confirmed by bullish close.",
        "M1 High": 116.0, "M1 Low": 98.0,
        "Sweep Candle High": 108.0, "Sweep Candle Low": 98.0,
    }
    row = multi._display_row(source, "TEST.NS", "TEST.NS")
    assert row["Signal"] == "LONG"
    assert row["SL"] == 98.0
    assert row["Target"] == 116.0
    assert row["RR"] == 2.0
    assert row["Zone"] == "FVG"
    assert row["Entry Date"] == "2026-11-07"
    assert "Monthly M1/M2" in row["Strategy"]


def test_scan_symbol_downloads_daily_and_uses_shared_monthly_daily_engine(monkeypatch):
    dates = pd.bdate_range("2025-01-01", periods=100)
    frame = pd.DataFrame({
        "Open": 100.0, "High": 102.0, "Low": 99.0, "Close": 101.0,
    }, index=dates)
    calls = {}
    monkeypatch.setattr(multi.yf, "download", lambda ticker, **kwargs: (
        calls.update({"ticker": ticker, **kwargs}) or frame
    ))
    expected = {
        "Bias": "Bearish", "Setup": "SELL", "LTP": 90.0, "Entry": 91.0,
        "SL": 98.0, "Target (M1 Monthly H/L)": 80.0,
        "Sweep Type": "Buy-Side Liquidity Sweep (BSL)",
        "CHoCH Rule": "Daily close below confirmed pivot 95",
        "Entry Zone Type": "OB", "Entry Status": "TRIGGERED",
        "Monthly Status": "VALID_BEARISH_SWEEP", "Target Status": "TARGET PENDING",
    }
    monkeypatch.setattr(multi, "scan_monthly_daily", lambda *args: expected)
    result = multi.scan_symbol("TEST", timeframe="4H")
    assert calls["interval"] == "1d"
    assert calls["period"] == "10y"
    assert result["Signal"] == "SHORT"
    assert result["SL"] == 98.0
    assert result["Target"] == 80.0
    assert result["Zone"] == "OB"


def test_empty_daily_download_is_reported_as_data_error(monkeypatch):
    monkeypatch.setattr(multi.yf, "download", lambda *args, **kwargs: pd.DataFrame())
    result = multi.scan_symbol("MISSING")
    assert result["Setup"] == "DATA ERROR"
    assert result["Signal"] == "WAIT"
    assert "no usable Daily OHLC" in result["Status"]
