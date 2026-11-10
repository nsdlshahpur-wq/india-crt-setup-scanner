"""Small offline checks for calculation helpers."""
import numpy as np
import pandas as pd

from scanner import ScanConfig, _monthly_context, _normalise_ohlc, _wilder_atr


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
