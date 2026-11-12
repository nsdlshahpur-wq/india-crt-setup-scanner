"""Offline tests for the read-only Dhan historical-data adapter."""
import unittest
from unittest.mock import Mock

import pandas as pd
import requests

from dhan_data import DhanDataError, fetch_dhan_daily_ohlc


class DhanDailyDataTests(unittest.TestCase):
    def _response(self, body, status=200):
        response = Mock()
        response.json.return_value = body
        response.raise_for_status.side_effect = (
            requests.HTTPError(response=response) if status >= 400 else None
        )
        response.status_code = status
        return response

    def test_converts_daily_candles_to_ist_ohlc(self):
        session = Mock()
        session.post.return_value = self._response({
            "open": [100], "high": [105], "low": [99], "close": [103],
            "volume": [1234], "timestamp": [1794441600],
        })
        result = fetch_dhan_daily_ohlc(
            "1333", "token", "2026-11-01", "2026-11-12", session=session
        )
        self.assertEqual(list(result.columns), ["Open", "High", "Low", "Close", "Volume"])
        self.assertEqual(float(result.iloc[0]["Close"]), 103.0)
        args = session.post.call_args.kwargs
        self.assertEqual(args["headers"]["access-token"], "token")
        self.assertEqual(args["json"]["toDate"], "2026-11-12")

    def test_rejects_missing_credentials_and_invalid_dates(self):
        with self.assertRaises(ValueError):
            fetch_dhan_daily_ohlc("1333", "", "2026-01-01", "2026-02-01")
        with self.assertRaises(ValueError):
            fetch_dhan_daily_ohlc("1333", "token", "2026-02-01", "2026-01-01")

    def test_rejects_mismatched_arrays(self):
        session = Mock()
        session.post.return_value = self._response({
            "open": [1, 2], "high": [1], "low": [1, 2], "close": [1, 2],
            "timestamp": [1, 2],
        })
        with self.assertRaises(DhanDataError):
            fetch_dhan_daily_ohlc(
                "1333", "token", "2026-01-01", "2026-02-01", session=session
            )

    def test_auth_failure_does_not_echo_token(self):
        session = Mock()
        session.post.return_value = self._response({}, status=401)
        with self.assertRaises(DhanDataError) as caught:
            fetch_dhan_daily_ohlc(
                "1333", "secret-token", "2026-01-01", "2026-02-01", session=session
            )
        self.assertNotIn("secret-token", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
