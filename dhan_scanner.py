"""DhanHQ daily market-data adapter for scanner universes (read-only)."""
from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Callable

import pandas as pd

from dhan_data import DhanDataError, fetch_dhan_daily_ohlc
from dhan_instruments import DhanInstrumentError, resolve_dhan_nse_equity


def download_dhan_market_data(
    symbols: list[str],
    period: str,
    access_token: str,
    instrument_master: pd.DataFrame,
    progress_callback: Callable[[int, int, str], None] | None = None,
    *,
    min_request_interval: float = 0.22,
) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    """Fetch daily candles sequentially under Dhan's documented 5 req/sec cap."""
    years = {"1y": 1, "2y": 2, "3y": 3, "5y": 5}
    if period not in years:
        raise ValueError("Unsupported Dhan history period. Choose 1y, 2y, 3y or 5y.")
    if not str(access_token or "").strip():
        raise ValueError("Dhan access token is missing. Configure it in Streamlit Secrets.")
    unique = list(dict.fromkeys(str(s).strip() for s in symbols if str(s).strip()))
    price_map: dict[str, pd.DataFrame] = {}
    errors: dict[str, str] = {}
    start = date.today() - timedelta(days=365 * years[period] + 5)
    end = date.today() + timedelta(days=1)
    total = len(unique)
    last_request = 0.0

    for index, symbol in enumerate(unique, start=1):
        try:
            instrument = resolve_dhan_nse_equity(symbol, instrument_master)
            wait = min_request_interval - (time.monotonic() - last_request)
            if last_request and wait > 0:
                time.sleep(wait)
            last_request = time.monotonic()
            prices = fetch_dhan_daily_ohlc(
                instrument["security_id"],
                access_token,
                start,
                end,
                exchange_segment=instrument["exchange_segment"],
                instrument=instrument["instrument"],
            )
            if prices.empty:
                errors[symbol] = "Dhan returned no daily OHLC candles for this instrument."
            else:
                price_map[symbol] = prices
        except (DhanInstrumentError, DhanDataError, ValueError) as exc:
            errors[symbol] = str(exc)
        except Exception as exc:
            errors[symbol] = f"Unexpected data error: {type(exc).__name__}: {str(exc)[:120]}"
        if progress_callback:
            progress_callback(index, total, symbol)
    return price_map, errors
