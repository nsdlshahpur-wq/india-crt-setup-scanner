"""Read-only DhanHQ daily OHLC adapter for the CRT scanner.

Credentials are supplied by the caller and should come from Streamlit secrets.
This module never places, modifies, or cancels orders.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import requests

DHAN_DAILY_CHART_URL = "https://api.dhan.co/v2/charts/historical"
_REQUIRED_FIELDS = ("open", "high", "low", "close", "timestamp")


class DhanDataError(RuntimeError):
    """Safe, actionable error from the Dhan historical-data adapter."""


def fetch_dhan_daily_ohlc(
    security_id: str,
    access_token: str,
    from_date: date | str,
    to_date: date | str,
    *,
    exchange_segment: str = "NSE_EQ",
    instrument: str = "EQUITY",
    timeout: int = 20,
    session: Any = requests,
) -> pd.DataFrame:
    """Fetch daily candles for one Dhan instrument.

    Dhan's `toDate` is non-inclusive. The returned DatetimeIndex is
    timezone-naive Asia/Kolkata to match the scanner's existing OHLC pipeline.
    """
    clean_id = str(security_id or "").strip()
    token = str(access_token or "").strip()
    if not clean_id:
        raise ValueError("Dhan security_id is required.")
    if not token:
        raise ValueError("Dhan access token is required.")

    start = pd.Timestamp(from_date).date()
    end = pd.Timestamp(to_date).date()
    if start >= end:
        raise ValueError("from_date must be earlier than the non-inclusive to_date.")

    payload = {
        "securityId": clean_id,
        "exchangeSegment": exchange_segment,
        "instrument": instrument,
        "expiryCode": 0,
        "oi": False,
        "fromDate": start.isoformat(),
        "toDate": end.isoformat(),
    }
    try:
        response = session.post(
            DHAN_DAILY_CHART_URL,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "access-token": token,
            },
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        body = response.json()
    except requests.Timeout:
        raise DhanDataError("Dhan historical-data request timed out.") from None
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "HTTP"
        if status in (401, 403):
            raise DhanDataError(
                f"Dhan rejected the access token (HTTP {status}); check token validity and Data API access."
            ) from None
        raise DhanDataError(f"Dhan historical-data API returned HTTP {status}.") from None
    except requests.RequestException:
        raise DhanDataError("Could not connect to Dhan historical-data API.") from None
    except ValueError:
        raise DhanDataError("Dhan returned invalid JSON.") from None

    if not isinstance(body, dict):
        raise DhanDataError("Dhan returned an unexpected response format.")
    if not body or not any(body.get(key) for key in _REQUIRED_FIELDS):
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

    missing = [key for key in _REQUIRED_FIELDS if key not in body]
    if missing:
        raise DhanDataError("Dhan response is missing required candle fields.")

    lengths = {len(body.get(key, [])) for key in _REQUIRED_FIELDS}
    if len(lengths) != 1:
        raise DhanDataError("Dhan returned candle arrays with inconsistent lengths.")

    try:
        frame = pd.DataFrame({
            "Open": body["open"],
            "High": body["high"],
            "Low": body["low"],
            "Close": body["close"],
            "Volume": body.get("volume", [0] * len(body["timestamp"])),
        })
        timestamps = pd.to_datetime(body["timestamp"], unit="s", utc=True)
        frame.index = timestamps.tz_convert("Asia/Kolkata").tz_localize(None)
        frame.index.name = "Date"
        frame = frame.astype({
            "Open": "float64", "High": "float64", "Low": "float64",
            "Close": "float64", "Volume": "float64",
        })
    except (TypeError, ValueError, OverflowError):
        raise DhanDataError("Dhan candle data could not be converted to OHLC format.") from None

    frame = frame.dropna(subset=["Open", "High", "Low", "Close"]).sort_index()
    return frame[~frame.index.duplicated(keep="last")]
