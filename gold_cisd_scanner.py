"""Gold (XAUUSD) CISD scanner with Yahoo Finance data support.

The strategy sequence is based on the two uploaded videos. Yahoo Finance
provides the available XAUUSD spot feed (XAUUSD=X) and 5-minute history.
If spot data is unavailable, GC=F futures is used and explicitly labelled.
Yahoo intraday history is limited and may be delayed; this is not a broker feed.
"""
from __future__ import annotations

from io import BytesIO
from typing import Any

import pandas as pd
import yfinance as yf

from cisd_scanner import CISDConfig, backtest_cisd, find_day_setup


ALIASES = {
    "timestamp": "Timestamp", "time": "Timestamp", "date": "Timestamp",
    "datetime": "Timestamp", "open": "Open", "high": "High",
    "low": "Low", "close": "Close",
}


def _clean_yahoo_history(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close"])
    data = frame.copy()
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    data.columns = [str(c).title() for c in data.columns]
    needed = ["Open", "High", "Low", "Close"]
    if not all(c in data.columns for c in needed):
        return pd.DataFrame(columns=needed)
    data = data[needed].copy()
    data.index = pd.to_datetime(data.index)
    data = data.dropna(subset=needed).sort_index()
    data = data[~data.index.duplicated(keep="last")]
    valid = (
        (data["High"] >= data[["Open", "Close", "Low"]].max(axis=1))
        & (data["Low"] <= data[["Open", "Close", "High"]].min(axis=1))
    )
    return data.loc[valid]


def fetch_yahoo_gold_data() -> tuple[pd.DataFrame, dict]:
    """Fetch XAUUSD 5-minute history and latest available quote from Yahoo."""
    failures = []
    for symbol, label in (("XAUUSD=X", "Yahoo Finance XAUUSD spot"), ("GC=F", "Yahoo Finance Gold futures fallback")):
        try:
            ticker = yf.Ticker(symbol)
            history = _clean_yahoo_history(ticker.history(period="60d", interval="5m", auto_adjust=False, prepost=False))
            if history.empty:
                failures.append(f"{symbol}: no 5-minute candles")
                continue
            quote = _clean_yahoo_history(ticker.history(period="1d", interval="1m", auto_adjust=False, prepost=False))
            quote_interval = "1-minute"
            if quote.empty:
                quote = _clean_yahoo_history(ticker.history(period="5d", interval="5m", auto_adjust=False, prepost=False))
                quote_interval = "5-minute"
            latest = quote.iloc[-1] if not quote.empty else history.iloc[-1]
            latest_time = quote.index[-1] if not quote.empty else history.index[-1]
            report = {
                "source": label,
                "ticker": symbol,
                "quote_interval": quote_interval,
                "latest_price": float(latest["Close"]),
                "latest_timestamp": str(latest_time),
                "history_rows": int(len(history)),
                "history_start": str(history.index.min()),
                "history_end": str(history.index.max()),
                "history_interval": "5-minute",
                "note": "Yahoo Finance intraday data can be delayed, incomplete or unavailable. Verify with your broker before trading.",
            }
            return history, report
        except Exception as exc:
            failures.append(f"{symbol}: {type(exc).__name__}: {str(exc)[:160]}")
    raise RuntimeError("Yahoo Finance se Gold data nahi mila. " + " | ".join(failures))


def load_gold_ohlc_csv(file: Any) -> tuple[pd.DataFrame, dict]:
    """Read TradingView-style OHLC CSV and return a clean datetime-indexed frame."""
    raw = pd.read_csv(file if hasattr(file, "read") else BytesIO(file))
    rename = {}
    for col in raw.columns:
        key = str(col).strip().lower().replace("<", "").replace(">", "")
        if key in ALIASES:
            rename[col] = ALIASES[key]
    raw = raw.rename(columns=rename)
    required = {"Timestamp", "Open", "High", "Low", "Close"}
    missing = sorted(required - set(raw.columns))
    if missing:
        raise ValueError(
            "CSV mein Date/Time/Timestamp aur Open, High, Low, Close columns chahiye. "
            f"Missing: {', '.join(missing)}"
        )
    raw["Timestamp"] = pd.to_datetime(raw["Timestamp"], errors="coerce")
    for col in ("Open", "High", "Low", "Close"):
        raw[col] = pd.to_numeric(raw[col], errors="coerce")
    frame = raw.dropna(subset=["Timestamp", "Open", "High", "Low", "Close"])
    frame = frame.set_index("Timestamp")[["Open", "High", "Low", "Close"]].sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    valid = (
        (frame["High"] >= frame[["Open", "Close", "Low"]].max(axis=1))
        & (frame["Low"] <= frame[["Open", "Close", "High"]].min(axis=1))
    )
    frame = frame.loc[valid]
    if frame.empty:
        raise ValueError("CSV se valid OHLC candles nahi mile.")
    report = {
        "rows": int(len(frame)),
        "start": str(frame.index.min()),
        "end": str(frame.index.max()),
        "source": "User-uploaded XAUUSD OHLC CSV",
    }
    return frame, report


__all__ = [
    "CISDConfig", "backtest_cisd", "find_day_setup",
    "load_gold_ohlc_csv", "fetch_yahoo_gold_data",
]
