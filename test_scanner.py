"""Small offline checks for calculation helpers."""
import numpy as np
import pandas as pd

from scanner import ScanConfig, _monthly_context, _normalise_ohlc, _wilder_atr, scan_symbol
from data_fetch import _extract_one


def sample_data():
    dates = pd.bdate_range("2024-01-01", periods=260)
    close = pd.Series(np.linspace(100, 150, len(dates)), index=dates)
    return pd.DataFrame({
        "Open": close - 0.5,
        "High": close + 1.0,
        "Low": close - 1.0,
        "Close": close,
        "Volume": 100_000,
    }, index=dates)


def test_normalise_and_atr():
    data = _normalise_ohlc(sample_data())
    atr = _wilder_atr(data, 14)
    assert not data.empty
    assert atr.notna().sum() > 100


def test_monthly_context_uses_completed_months():
    ctx = _monthly_context(_normalise_ohlc(sample_data()))
    assert ctx is not None
    assert ctx["m1_period"] < ctx["m2_period"]
    assert ctx["m2_start"] < sample_data().index[-1]


def test_nse_universe_filters_eq_series_only():
    from universe import _read_equity_csv

    raw = (
        b"SYMBOL,SERIES,NAME OF COMPANY\n"
        b"AAA,EQ,Alpha Ltd\n"
        b"BBB,BE,Beta Ltd\n"
        b"CCC,EQ,Gamma Ltd\n"
    )
    frame = _read_equity_csv(raw)
    assert frame["SYMBOL"].tolist() == ["AAA", "CCC"]
    assert set(frame["SERIES"].tolist()) == {"EQ"}


def test_custom_index_aliases_are_not_converted_to_nse_stocks():
    from universe import make_universe

    frame = make_universe("Custom symbols", "RELIANCE, NIFTY 50, NIFTY BANK, SENSEX")
    assert frame["Symbol"].tolist() == ["RELIANCE.NS", "^NSEI", "^NSEBANK", "^BSESN"]


if __name__ == "__main__":
    test_normalise_and_atr()
    test_monthly_context_uses_completed_months()
    print("Offline scanner tests passed")


def test_scan_symbol_returns_complete_row():
    result = scan_symbol("TEST.NS", "Test Company", sample_data(), ScanConfig())
    assert result is not None
    assert result["Symbol"] == "TEST.NS"
    assert result["Bias"] in {"Bullish", "Bearish", "Neutral"}
    assert result["Setup"] in {"BUY", "SELL", "Wait Entry", "Wait Sweep", "-"}


def test_yfinance_multiindex_ticker_price_order():
    dates = pd.bdate_range("2025-01-01", periods=3)
    columns = pd.MultiIndex.from_product([["TEST.NS"], ["Open", "High", "Low", "Close", "Volume"]])
    raw = pd.DataFrame([[10, 12, 9, 11, 100], [11, 13, 10, 12, 200], [12, 14, 11, 13, 300]], index=dates, columns=columns)
    extracted = _extract_one(raw, "TEST.NS")
    assert extracted["Close"].tolist() == [11, 12, 13]


def test_yfinance_multiindex_price_ticker_order():
    dates = pd.bdate_range("2025-01-01", periods=3)
    columns = pd.MultiIndex.from_product([["Open", "High", "Low", "Close", "Volume"], ["TEST.NS"]])
    raw = pd.DataFrame([[10, 11, 9, 10.5, 100], [11, 12, 10, 11.5, 200], [12, 13, 11, 12.5, 300]], index=dates, columns=columns)
    extracted = _extract_one(raw, "TEST.NS")
    assert extracted["Close"].tolist() == [10.5, 11.5, 12.5]
