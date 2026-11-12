"""Offline tests for Dhan NSE equity security-master parsing and lookup."""
import unittest
from unittest.mock import Mock
import requests
from dhan_instruments import DhanInstrumentError, download_dhan_instrument_master, parse_dhan_instrument_master, resolve_dhan_nse_equity

CSV = """SEM_EXM_EXCH_ID,SEM_SEGMENT,SEM_SMST_SECURITY_ID,SEM_INSTRUMENT_NAME,SEM_TRADING_SYMBOL,SEM_SERIES,SEM_CUSTOM_SYMBOL
NSE,E,2885,EQUITY,RELIANCE,EQ,RELIANCE INDUSTRIES
NSE,E,1333,EQUITY,HDFCBANK,EQ,HDFC BANK
BSE,E,500325,EQUITY,RELIANCE,A,RELIANCE BSE
NSE,D,12345,OPTSTK,RELIANCE,XX,RELIANCE OPTION
NSE,E,7777,EQUITY,SMECO,SM,SME COMPANY
"""

class DhanInstrumentTests(unittest.TestCase):
    def test_parser_filters_to_nse_cash_eq(self):
        master = parse_dhan_instrument_master(CSV)
        self.assertEqual(master["SYMBOL"].tolist(), ["HDFCBANK", "RELIANCE"])
        self.assertEqual(resolve_dhan_nse_equity("RELIANCE.NS", master)["security_id"], "2885")
        self.assertEqual(resolve_dhan_nse_equity("NSE:HDFCBANK", master)["security_id"], "1333")

    def test_rejects_unmapped_or_non_nse_symbols(self):
        master = parse_dhan_instrument_master(CSV)
        for symbol in ["UNKNOWN.NS", "^NSEI", "RELIANCE.BO"]:
            with self.subTest(symbol=symbol), self.assertRaises(DhanInstrumentError):
                resolve_dhan_nse_equity(symbol, master)

    def test_rejects_missing_master_columns(self):
        with self.assertRaises(DhanInstrumentError):
            parse_dhan_instrument_master("SYMBOL,SECURITY_ID\nABC,1")

    def test_download_uses_official_master(self):
        session = Mock()
        response = Mock()
        response.content = CSV.encode()
        response.raise_for_status.return_value = None
        session.get.return_value = response
        master = download_dhan_instrument_master(session=session)
        self.assertEqual(resolve_dhan_nse_equity("RELIANCE", master)["security_id"], "2885")
        self.assertIn("api-scrip-master.csv", session.get.call_args.args[0])

    def test_download_timeout_is_safe(self):
        session = Mock()
        session.get.side_effect = requests.Timeout()
        with self.assertRaises(DhanInstrumentError):
            download_dhan_instrument_master(session=session)

if __name__ == "__main__":
    unittest.main()
