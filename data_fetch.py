"""Robust daily OHLC downloader for Yahoo Finance via yfinance.

Bare Indian equity symbols default to NSE (.NS); explicit .NS/.BO symbols and
Yahoo index symbols (^) are preserved. Returned mapping keys stay as requested.
"""
from __future__ import annotations

import time
from typing import Callable

import pandas as pd
import yfinance as yf


def yahoo_ticker(symbol: str) -> str:
    """Resolve a user/catalog symbol to a Yahoo Finance ticker."""
    ticker = str(symbol or "").strip().upper()
    if not ticker:
        return ""
    if ticker.startswith("^") or ticker.endswith((".NS", ".BO")):
        return ticker
    # Yahoo Finance's standard convention for Indian cash equities.
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
    """Use current yfinance download options, preserving multi-ticker column layout."""
    return yf.download(
        tickers=tickers if len(tickers) > 1 else tickers[0],
        period=period,
        interval="1d",
        group_by="ticker",
        auto_adjust=False,
        actions=False,
        threads=len(tickers) > 1,
        progress=False,
        timeout=30,
    )


def download_market_data(
    symbols: list[str],
    period: str = "3y",
    batch_size: int = 40,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    """Download daily OHLC in batches, then retry missing symbols individually.

    This is an unofficial Yahoo Finance adapter, not an exchange-grade feed.
    """
    unique = list(dict.fromkeys(str(s).strip() for s in symbols if str(s).strip()))
    data_map: dict[str, pd.DataFrame] = {}
    errors: dict[str, str] = {}
    total = len(unique)
    size = max(1, int(batch_size))

    for start in range(0, total, size):
        batch = unique[start : start + size]
        resolved = {requested: yahoo_ticker(requested) for requested in batch}
        yahoo_symbols = list(dict.fromkeys(resolved.values()))
        batch_data = pd.DataFrame()
        batch_error = ""
        for attempt in range(2):
            try:
                batch_data = _download(yahoo_symbols, period)
                if batch_data is not None and not batch_data.empty:
                    break
                batch_error = "Yahoo Finance returned an empty response"
            except Exception as exc:
                batch_error = f"{type(exc).__name__}: {str(exc)[:180]}"
            if attempt == 0:
                time.sleep(1)

        missing: list[str] = []
        for requested in batch:
            extracted = _extract_one(batch_data, resolved[requested])
            if extracted.empty and len(yahoo_symbols) == 1:
                # Single-symbol yfinance responses can sometimes carry a
                # different column shape; try extracting with requested key.
                extracted = _extract_one(batch_data, requested)
            if not extracted.empty:
                data_map[requested] = extracted
            else:
                missing.append(requested)

        # Batch endpoints sometimes omit one ticker while others succeed.
        # Retry each missing symbol independently to avoid losing the entire
        # market scan because of Yahoo's changing MultiIndex response shape.
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
                    time.sleep(0.8)
            if last_error:
                errors[requested] = (
                    f"Yahoo ticker {yahoo_symbol}: {last_error}. "
                    "Check ticker mapping or try again later."
                )

        if progress_callback:
            progress_callback(min(start + len(batch), total), total, batch[-1] if batch else "")
        if start + len(batch) < total:
            time.sleep(0.25)

    return data_map, errors
