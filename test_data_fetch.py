"""Unit tests for Yahoo ticker normalization and response extraction."""
import pandas as pd

import data_fetch


def test_yahoo_ticker_resolves_bare_indian_equity():
    assert data_fetch.yahoo_ticker("RELIANCE") == "RELIANCE.NS"
    assert data_fetch.yahoo_ticker("reliance.ns") == "RELIANCE.NS"
    assert data_fetch.yahoo_ticker("500325.BO") == "500325.BO"
    assert data_fetch.yahoo_ticker("^NSEI") == "^NSEI"


def test_download_market_data_returns_requested_key_for_bare_symbol(monkeypatch):
    index = pd.date_range("2026-01-01", periods=3, freq="D")
    frame = pd.DataFrame(
        {"Open": [100, 101, 102], "High": [102, 103, 104],
         "Low": [99, 100, 101], "Close": [101, 102, 103]},
        index=index,
    )
    calls = []

    def fake_download(tickers, period):
        calls.append(tickers)
        return frame.copy()

    monkeypatch.setattr(data_fetch, "_download", fake_download)
    prices, errors = data_fetch.download_market_data(["RELIANCE"], batch_size=1)

    assert "RELIANCE" in prices
    assert prices["RELIANCE"].shape[0] == 3
    assert errors == {}
    assert calls == ["RELIANCE.NS"]


def test_missing_batch_symbol_retries_individually(monkeypatch):
    index = pd.date_range("2026-01-01", periods=2, freq="D")
    def make(ticker):
        cols = pd.MultiIndex.from_product([[ticker], ["Open", "High", "Low", "Close"]])
        return pd.DataFrame([[10, 12, 9, 11], [11, 13, 10, 12]], index=index, columns=cols)

    def fake_download(tickers, period):
        if isinstance(tickers, list):
            return make("GOOD.NS")
        return make(tickers)

    monkeypatch.setattr(data_fetch, "_download", fake_download)
    prices, errors = data_fetch.download_market_data(["GOOD", "OMITTED"], batch_size=2)

    assert "GOOD" in prices
    assert "OMITTED" in prices
    assert errors == {}
