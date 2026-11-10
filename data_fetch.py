"""Daily OHLC downloader using Yahoo Finance through yfinance."""
from __future__ import annotations

import time
from typing import Callable

import pandas as pd
import yfinance as yf


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
    return data[keep].dropna(subset=needed)


def download_market_data(
    symbols: list[str],
    period: str = "3y",
    batch_size: int = 40,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    """Download daily OHLC in small batches, retrying failed batches once.

    yfinance is an unofficial Yahoo Finance interface intended for personal,
    research and educational use. It is not an exchange-grade live feed.
    """
    unique = list(dict.fromkeys(s for s in symbols if s))
    data_map: dict[str, pd.DataFrame] = {}
    errors: dict[str, str] = {}
    total = len(unique)
    for start in range(0, total, batch_size):
        batch = unique[start : start + batch_size]
        downloaded = pd.DataFrame()
        last_error = ""
        for attempt in range(2):
            try:
                downloaded = yf.download(
                    tickers=batch,
                    period=period,
                    interval="1d",
                    group_by="ticker",
                    auto_adjust=False,
                    actions=False,
                    threads=True,
                    progress=False,
                    timeout=25,
                )
                if downloaded is not None and not downloaded.empty:
                    break
                last_error = "Yahoo Finance returned no data"
            except Exception as exc:
                last_error = str(exc)[:220]
            if attempt == 0:
                time.sleep(1.2)
        for ticker in batch:
            one = _extract_one(downloaded, ticker)
            if one.empty:
                errors[ticker] = last_error or "No OHLC data available for this ticker"
            else:
                data_map[ticker] = one
        if progress_callback:
            progress_callback(min(start + len(batch), total), total, batch[-1] if batch else "")
        time.sleep(0.35)
    return data_map, errors
