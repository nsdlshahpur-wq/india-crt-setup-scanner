"""Robust daily OHLC downloader for Yahoo Finance via yfinance.

Large-market scans use batched requests and deliberately avoid thousands of
individual fallbacks. Small targeted requests retain individual retries.
"""
from __future__ import annotations

import time
from typing import Callable

import pandas as pd
import yfinance as yf

INDIVIDUAL_RETRY_LIMIT = 100


def yahoo_ticker(symbol: str) -> str:
    """Resolve a user/catalog symbol to a Yahoo Finance ticker."""
    ticker = str(symbol or "").strip().upper()
    if not ticker:
        return ""
    index_aliases = {
        "NIFTY": "^NSEI",
        "NIFTY 50": "^NSEI",
        "NIFTY50": "^NSEI",
        "NIFTY BANK": "^NSEBANK",
        "BANK NIFTY": "^NSEBANK",
        "BANKNIFTY": "^NSEBANK",
        "SENSEX": "^BSESN",
        "BSE SENSEX": "^BSESN",
        "INDIA VIX": "^INDIAVIX",
    }
    if ticker in index_aliases:
        return index_aliases[ticker]
    if ticker.startswith("^") or ticker.endswith((".NS", ".BO")):
        return ticker
    return f"{ticker}.NS"


def _extract_one(downloaded: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if downloaded is None or downloaded.empty:
        return pd.DataFrame()
    data = downloaded
    if isinstance(data.columns, pd.MultiIndex):
        level0 = data.columns.get_level_values(0)
        level1 = data.columns.get_level_values(1)
        if ticker in level0:
            data = data[ticker]
        elif ticker in level1:
            data = data.xs(ticker, axis=1, level=1)
        else:
            match0 = next((v for v in level0.unique() if str(v).upper() == ticker.upper()), None)
            match1 = next((v for v in level1.unique() if str(v).upper() == ticker.upper()), None)
            if match0 is not None:
                data = data[match0]
            elif match1 is not None:
                data = data.xs(match1, axis=1, level=1)
            else:
                return pd.DataFrame()
    data = data.copy()
    data.columns = [str(c).title() for c in data.columns]
    needed = ["Open", "High", "Low", "Close"]
    if not all(c in data.columns for c in needed):
        return pd.DataFrame()
    keep = needed + (["Volume"] if "Volume" in data.columns else [])
    data = data[keep].copy()
    data.index = pd.to_datetime(data.index)
    return data.dropna(subset=needed)


def _download(tickers: list[str], period: str) -> pd.DataFrame:
    """Download one bounded ticker batch from Yahoo Finance."""
    return yf.download(
        tickers=tickers if len(tickers) > 1 else tickers[0],
        period=period,
        interval="1d",
        group_by="ticker",
        auto_adjust=False,
        actions=False,
        # Sequential ticker handling avoids yfinance's internal thread fan-out.
        threads=False,
        progress=False,
        timeout=35,
    )


def download_market_data(
    symbols: list[str],
    period: str = "3y",
    batch_size: int = 20,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    """Download daily OHLC in batches.

    For >100 symbols, a failed/missing ticker is reported rather than triggering
    a serial request per ticker. This avoids thousands of slow Yahoo requests.
    Small targeted lists still get an individual retry for missing symbols.
    """
    unique = list(dict.fromkeys(str(s).strip() for s in symbols if str(s).strip()))
    data_map: dict[str, pd.DataFrame] = {}
    errors: dict[str, str] = {}
    total = len(unique)
    if not total:
        return data_map, errors

    size = max(1, int(batch_size))
    large_universe = total > INDIVIDUAL_RETRY_LIMIT

    for start in range(0, total, size):
        batch = unique[start : start + size]
        resolved = {requested: yahoo_ticker(requested) for requested in batch}
        yahoo_symbols = list(dict.fromkeys(resolved.values()))
        batch_data = pd.DataFrame()
        batch_error = ""

        # Retry transient Yahoo throttling with exponential backoff. For a
        # broad universe, never fan out into thousands of individual retries.
        attempts = 4 if large_universe else 2
        rate_limited = False
        for attempt in range(attempts):
            try:
                batch_data = _download(yahoo_symbols, period)
                if batch_data is not None and not batch_data.empty:
                    break
                batch_error = "Yahoo Finance returned an empty batch response"
            except Exception as exc:
                batch_error = f"{type(exc).__name__}: {str(exc)[:180]}"
            rate_limited = rate_limited or any(
                token in batch_error.lower()
                for token in ("429", "too many requests", "rate limit", "ratelimit")
            )
            if attempt + 1 < attempts:
                time.sleep(min(30, 3 * (2 ** attempt)) if large_universe else 1.5)

        missing: list[str] = []
        for requested in batch:
            yahoo_symbol = resolved[requested]
            extracted = _extract_one(batch_data, yahoo_symbol)
            if extracted.empty and len(yahoo_symbols) == 1:
                extracted = _extract_one(batch_data, requested)
            if not extracted.empty:
                data_map[requested] = extracted
            else:
                missing.append(requested)

        if large_universe:
            # Stop after a likely Yahoo throttle instead of continuing to hammer it.
            if rate_limited or (batch_data is None or batch_data.empty):
                stop_reason = "Yahoo Finance rate limit suspected (HTTP 429 / empty batch). Scan paused; retry after cooldown or scan a smaller group."
                for requested in missing:
                    errors[requested] = f"Yahoo ticker {resolved[requested]}: {stop_reason}"
                for remaining in unique[start + len(batch):]:
                    errors[remaining] = stop_reason
                if progress_callback:
                    progress_callback(total, total, batch[-1] if batch else "")
                break
            for requested in missing:
                errors[requested] = (
                    f"Yahoo ticker {resolved[requested]} was not present in its batch response. "
                    "Individual retry skipped for the large-universe scan; use a smaller watchlist "
                    "or run a targeted scan for this symbol."
                )
        else:
            for requested in missing:
                yahoo_symbol = resolved[requested]
                last_error = batch_error or "Yahoo Finance returned no OHLC rows"
                for attempt in range(2):
                    try:
                        single = _download([yahoo_symbol], period)
                        extracted = _extract_one(single, yahoo_symbol)
                        if extracted.empty:
                            extracted = _extract_one(single, requested)
                        if not extracted.empty:
                            data_map[requested] = extracted
                            last_error = ""
                            break
                        last_error = "Yahoo Finance returned no OHLC rows for this symbol"
                    except Exception as exc:
                        last_error = f"{type(exc).__name__}: {str(exc)[:180]}"
                    if attempt == 0:
                        time.sleep(0.4)
                if last_error:
                    errors[requested] = (
                        f"Yahoo ticker {yahoo_symbol}: {last_error}. "
                        "Check ticker mapping or try again later."
                    )

        if progress_callback:
            progress_callback(min(start + len(batch), total), total, batch[-1] if batch else "")
        # A small inter-batch pause helps avoid hammering Yahoo without adding
        # a large fixed delay across the 100+ batches of a full-market scan.
        if start + len(batch) < total:
            time.sleep(1.0)

    return data_map, errors
