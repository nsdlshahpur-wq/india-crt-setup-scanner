"""CRT multi-timeframe status analysis ported from the supplied Pine Script.

This module is informational only. It does not alter scanner.py or backtest.py.
The Pine f_tfStatus() rule is applied to completed candles for 1H, 4H, Daily,
Weekly and Monthly. Yahoo Finance intraday history is limited and may be absent.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd
import yfinance as yf

from data_fetch import yahoo_ticker

TIMEFRAMES = [
    {"label": "1H", "interval": "60m", "period": "60d"},
    {"label": "4H", "interval": "60m", "period": "60d", "resample": "4h"},
    {"label": "Daily", "interval": "1d", "period": "2y"},
    {"label": "Weekly", "interval": "1wk", "period": "5y"},
    {"label": "Monthly", "interval": "1mo", "period": "10y"},
]


def _clean_ohlc(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    data = frame.copy()
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    data.columns = [str(c).title() for c in data.columns]
    required = ["Open", "High", "Low", "Close"]
    if not all(c in data.columns for c in required):
        return pd.DataFrame()
    data = data[required].copy()
    data.index = pd.to_datetime(data.index)
    if getattr(data.index, "tz", None) is not None:
        data.index = data.index.tz_localize(None)
    data = data[~data.index.duplicated(keep="last")].sort_index()
    return data.apply(pd.to_numeric, errors="coerce").dropna()


def _status(frame: pd.DataFrame, label: str) -> dict[str, Any]:
    # Exclude the newest candle: it may still be forming and must not create a signal.
    data = _clean_ohlc(frame)
    if len(data) > 1:
        data = data.iloc[:-1]
    if len(data) < 2:
        return {
            "Timeframe": label, "Liquidity Sweep": "DATA UNAVAILABLE",
            "MSS/MSB": "—", "OB/BB": "—", "Signal": "WAIT",
            "Last Close": None, "Updated": None,
        }

    previous = data.iloc[-2]
    current = data.iloc[-1]
    bull_sweep = current["Low"] < previous["Low"] and current["Close"] > previous["Low"]
    bear_sweep = current["High"] > previous["High"] and current["Close"] < previous["High"]
    sweep = "BULL" if bull_sweep else "BEAR" if bear_sweep else "—"

    # Mirrors the supplied Pine f_tfStatus() expression.
    mss_active = (bull_sweep or bear_sweep) and (
        current["Close"] > previous["High"] or current["Close"] < previous["Low"]
    )
    mss = "YES" if mss_active else "NO"
    zone = ("BULL OB/BB" if bull_sweep else "BEAR OB/BB") if mss_active else "—"
    signal = ("BULL ORDER" if bull_sweep else "BEAR ORDER") if mss_active else "WAIT"
    return {
        "Timeframe": label,
        "Liquidity Sweep": sweep,
        "MSS/MSB": mss,
        "OB/BB": zone,
        "Signal": signal,
        "Last Close": round(float(current["Close"]), 2),
        "Updated": data.index[-1].strftime("%d-%b-%Y %H:%M"),
    }


def analyze_mtf_symbol(symbol: str) -> tuple[pd.DataFrame, dict[str, str]]:
    """Return Pine-style MTF status rows and per-timeframe data errors."""
    ticker = yahoo_ticker(symbol)
    rows: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    daily_cache: pd.DataFrame | None = None
    hourly_cache: pd.DataFrame | None = None

    for spec in TIMEFRAMES:
        label = str(spec["label"])
        try:
            if label == "4H":
                if hourly_cache is None:
                    hourly_cache = _clean_ohlc(yf.download(
                        ticker, period="60d", interval="60m",
                        auto_adjust=False, progress=False, threads=False,
                    ))
                raw = hourly_cache
                if not raw.empty:
                    raw = raw.resample("4h", label="right", closed="right").agg({
                        "Open": "first", "High": "max", "Low": "min", "Close": "last"
                    }).dropna()
            elif label == "1H":
                raw = _clean_ohlc(yf.download(
                    ticker, period="60d", interval="60m",
                    auto_adjust=False, progress=False, threads=False,
                ))
                hourly_cache = raw
            elif label == "Daily":
                raw = _clean_ohlc(yf.download(
                    ticker, period="2y", interval="1d",
                    auto_adjust=False, progress=False, threads=False,
                ))
                daily_cache = raw
            elif label == "Weekly":
                if daily_cache is None:
                    daily_cache = _clean_ohlc(yf.download(
                        ticker, period="5y", interval="1d",
                        auto_adjust=False, progress=False, threads=False,
                    ))
                raw = daily_cache.resample("W-FRI", label="right", closed="right").agg({
                    "Open": "first", "High": "max", "Low": "min", "Close": "last"
                }).dropna()
            else:
                if daily_cache is None:
                    daily_cache = _clean_ohlc(yf.download(
                        ticker, period="10y", interval="1d",
                        auto_adjust=False, progress=False, threads=False,
                    ))
                raw = daily_cache.resample("ME", label="right", closed="right").agg({
                    "Open": "first", "High": "max", "Low": "min", "Close": "last"
                }).dropna()

            if raw.empty:
                errors[label] = "Yahoo Finance से डेटा नहीं मिला"
                rows.append(_status(pd.DataFrame(), label))
            else:
                rows.append(_status(raw, label))
        except Exception as exc:
            errors[label] = str(exc)[:180]
            rows.append(_status(pd.DataFrame(), label))

    return pd.DataFrame(rows), errors
