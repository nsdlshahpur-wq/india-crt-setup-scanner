"""Small offline checks for calculation helpers."""
import numpy as np
import pandas as pd

from scanner import ScanConfig, _monthly_context, _normalise_ohlc, _wilder_atr, _zones, scan_symbol
from data_fetch import _extract_one
import universe


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
    raw = (
        b"SYMBOL,SERIES,NAME OF COMPANY\n"
        b"AAA,EQ,Alpha Ltd\n"
        b"BBB,BE,Beta Ltd\n"
        b"CCC,EQ,Gamma Ltd\n"
    )
    frame = universe._read_nse_equity_csv(raw)
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
    assert result["Setup"] in {"BUY", "SELL", "Wait Retest", "Wait CHoCH", "Wait FVG/IFVG/OB/BOB", "No Valid Monthly Sweep"}


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



def test_bse_master_headered_csv_eq_filter():
    raw = pd.DataFrame({
        "Scrip Code": ["500001", "500002", "500003"],
        "Instrument Code": ["AAA", "BBB", "CCC"],
        "Group Name": ["A", "B", "A"],
        "Scrip Name": ["Alpha Ltd", "Beta Bond", "Gamma Ltd"],
        "ISIN CODE": ["INE000A01000", "INE000B01000", "INE000C01000"],
        "Market Lot": ["1", "1", "1"],
        "Face Value": ["10", "10", "10"],
        "Security Type Flag": ["EQ", "DB", "EQ"],
    })
    parsed = universe._parse_bse_frame(raw)
    assert parsed["SYMBOL"].tolist() == ["AAA", "CCC"]
    assert parsed["NAME"].tolist() == ["Alpha Ltd", "Gamma Ltd"]


def test_official_nifty_equity_index_catalog_is_comprehensive():
    names = [name for name, _category in universe.NIFTY_EQUITY_INDEX_CATALOG]
    assert len(names) >= 140
    assert "NIFTY 50" in names
    assert "NIFTY BANK" in names
    assert "NIFTY INDIA DEFENCE" in names
    assert "NIFTY200 MOMENTUM 30" in names
    assert len(names) == len(set(name.upper() for name in names))
    all_indices = universe._index_rows()
    all_names = [row["Name"].upper() for row in all_indices]
    assert len(all_indices) >= 10
    assert len(all_names) == len(set(all_names))
    assert all(row["DataAvailable"] for row in all_indices)
    assert any(row["Name"] == "S&P BSE SENSEX" for row in all_indices)
    assert not any(row["Name"] == "S&P BSE 500" for row in all_indices)
    assert universe.YAHOO_INDEX_SYMBOLS["NIFTY 200"] == "^CNX200"
    assert universe.YAHOO_INDEX_SYMBOLS["NIFTY MNC"] == "^CNXMNC"
    assert universe.YAHOO_INDEX_SYMBOLS["NIFTY PSE"] == "^CNXPSE"
    assert universe.YAHOO_INDEX_SYMBOLS["NIFTY CONSUMPTION"] == "^CNXCONSUM"
    assert universe.YAHOO_INDEX_SYMBOLS["NIFTY MIDCAP 150"] == "NIFTYMIDCAP150.NS"
    assert universe.YAHOO_INDEX_SYMBOLS["NIFTY 500"] == "^CRSLDX"
    assert universe.YAHOO_INDEX_SYMBOLS["NIFTY TOTAL MARKET"] == "NIFTY_TOTAL_MKT.NS"
    assert universe.YAHOO_INDEX_SYMBOLS["NIFTY FINANCIAL SERVICES"] == "NIFTY_FIN_SERVICE.NS"
    assert "NIFTY MIDCAP 100" not in universe.YAHOO_INDEX_SYMBOLS


def test_legacy_all_india_universe_keeps_stocks_but_only_mapped_indices(monkeypatch):
    nse = pd.DataFrame([{"SYMBOL": "RELIANCE", "NAME": "Reliance Industries", "SERIES": "EQ"}])
    bse = pd.DataFrame([{"SYMBOL": "TCS", "NAME": "Tata Consultancy Services"}])
    sme = pd.DataFrame([{"SYMBOL": "ABC", "NAME": "ABC SME Ltd"}])
    monkeypatch.setattr(universe, "get_nse_equity_universe", lambda: nse)
    monkeypatch.setattr(universe, "get_nse_sme_universe", lambda: sme)
    monkeypatch.setattr(universe, "get_bse_equity_universe", lambda: (bse, "test BSE master"))
    frame = universe.make_universe("All NSE + BSE stocks + all indices")
    assert "RELIANCE.NS" in frame["Symbol"].tolist()
    assert "ABC.NS" in frame["Symbol"].tolist()
    assert "TCS.BO" in frame["Symbol"].tolist()
    assert (frame["Exchange"] == "NSE-SME").sum() == 1
    index_rows = frame[frame["Type"] == "Index"]
    assert len(index_rows) >= 10
    assert index_rows["DataAvailable"].all()
    assert index_rows["Symbol"].fillna("").astype(str).str.strip().ne("").all()

    stock_only = universe.make_universe("All NSE + BSE stocks + SME")
    assert "RELIANCE.NS" in stock_only["Symbol"].tolist()
    assert "ABC.NS" in stock_only["Symbol"].tolist()
    assert "TCS.BO" in stock_only["Symbol"].tolist()
    assert not (stock_only["Type"] == "Index").any()



def test_nse_sme_csv_parser():
    raw = (
        b"SYMBOL,NAME OF COMPANY\n"
        b"SMEONE,SME One Limited\n"
        b"SMETWO,SME Two Limited\n"
    )
    frame = universe._read_nse_sme_csv(raw)
    assert frame["SYMBOL"].tolist() == ["SMEONE", "SMETWO"]


def test_zone_orderblock_uses_configured_atr_displacement():
    dates = pd.bdate_range("2026-01-01", periods=30)
    frame = pd.DataFrame({
        "Open": [100.0] * 30,
        "High": [101.0] * 30,
        "Low": [99.0] * 30,
        "Close": [100.0] * 30,
    }, index=dates)
    frame.iloc[28, frame.columns.get_loc("Open")] = 101.0
    frame.iloc[28, frame.columns.get_loc("High")] = 102.0
    frame.iloc[28, frame.columns.get_loc("Low")] = 99.0
    frame.iloc[28, frame.columns.get_loc("Close")] = 99.0
    frame.iloc[29, frame.columns.get_loc("Open")] = 99.0
    frame.iloc[29, frame.columns.get_loc("High")] = 104.0
    frame.iloc[29, frame.columns.get_loc("Low")] = 98.0
    frame.iloc[29, frame.columns.get_loc("Close")] = 103.0

    permissive = ScanConfig(atr_length=2, displacement_atr=0.5)
    strict = ScanConfig(atr_length=2, displacement_atr=1.0)
    permissive_ob = _zones(frame, 0, 29, 1, permissive)[2]
    strict_ob = _zones(frame, 0, 29, 1, strict)[2]

    assert permissive_ob
    assert not strict_ob
