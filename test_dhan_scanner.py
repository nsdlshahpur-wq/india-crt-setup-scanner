"""Offline tests for the Dhan scanner market-data adapter."""
import unittest
from unittest.mock import patch
import pandas as pd

from dhan_scanner import download_dhan_market_data

MASTER = pd.DataFrame([
    {"SYMBOL":"RELIANCE","SECURITY_ID":"2885","EXCHANGE_SEGMENT":"NSE_EQ","INSTRUMENT":"EQUITY"},
    {"SYMBOL":"HDFCBANK","SECURITY_ID":"1333","EXCHANGE_SEGMENT":"NSE_EQ","INSTRUMENT":"EQUITY"},
])

class DhanScannerTests(unittest.TestCase):
    @patch("dhan_scanner.fetch_dhan_daily_ohlc")
    @patch("dhan_scanner.time.sleep")
    def test_downloads_resolved_symbols_and_reports_unsupported(self, sleep, fetch):
        fetch.return_value = pd.DataFrame({"Open":[1],"High":[2],"Low":[1],"Close":[2],"Volume":[10]}, index=pd.to_datetime(["2026-11-11"]))
        progress=[]
        prices, errors = download_dhan_market_data(
            ["RELIANCE.NS","HDFCBANK","^NSEI"], "1y", "token", MASTER,
            lambda done,total,symbol: progress.append((done,total,symbol)),
        )
        self.assertEqual(set(prices), {"RELIANCE.NS","HDFCBANK"})
        self.assertIn("^NSEI", errors)
        self.assertEqual(len(progress),3)
        self.assertEqual(fetch.call_count,2)

    def test_requires_valid_period_and_token(self):
        with self.assertRaises(ValueError):
            download_dhan_market_data(["RELIANCE"],"10y","token",MASTER)
        with self.assertRaises(ValueError):
            download_dhan_market_data(["RELIANCE"],"1y","",MASTER)

if __name__ == "__main__":
    unittest.main()
