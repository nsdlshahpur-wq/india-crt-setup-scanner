"""Multi-asset CISD scanner with Yahoo Finance intraday data.

Supported instruments are spot metals, crypto pairs, forex pairs and a US30
futures proxy. No equities/stocks are included. Yahoo symbols are provider
proxies and may differ from broker CFD/spot contracts.
"""
from __future__ import annotations

from io import BytesIO
from typing import Any

import pandas as pd
import yfinance as yf

from cisd_scanner import CISDConfig, backtest_cisd, find_day_setup


INSTRUMENTS = {
    "Metals": {
        "Gold (XAUUSD)": {"ticker": "XAUUSD=X", "label": "Yahoo XAUUSD spot", "unit": "USD per troy ounce"},
        "Silver (XAGUSD)": {"ticker": "XAGUSD=X", "label": "Yahoo XAGUSD spot", "unit": "USD per troy ounce"},
    },
    "Crypto": {
        "Bitcoin (BTCUSD)": {"ticker": "BTC-USD", "label": "Yahoo Bitcoin/USD", "unit": "USD"},
        "Ethereum (ETHUSD)": {"ticker": "ETH-USD", "label": "Yahoo Ethereum/USD", "unit": "USD"},
        "Solana (SOLUSD)": {"ticker": "SOL-USD", "label": "Yahoo Solana/USD", "unit": "USD"},
        "BNB (BNBUSD)": {"ticker": "BNB-USD", "label": "Yahoo BNB/USD", "unit": "USD"},
        "XRP (XRPUSD)": {"ticker": "XRP-USD", "label": "Yahoo XRP/USD", "unit": "USD"},
        "Cardano (ADAUSD)": {"ticker": "ADA-USD", "label": "Yahoo Cardano/USD", "unit": "USD"},
        "Dogecoin (DOGEUSD)": {"ticker": "DOGE-USD", "label": "Yahoo Dogecoin/USD", "unit": "USD"},
        "Litecoin (LTCUSD)": {"ticker": "LTC-USD", "label": "Yahoo Litecoin/USD", "unit": "USD"},
    },
    "Forex": {
        "EURUSD": {"ticker": "EURUSD=X", "label": "Yahoo EUR/USD", "unit": "USD per EUR"},
        "GBPUSD": {"ticker": "GBPUSD=X", "label": "Yahoo GBP/USD", "unit": "USD per GBP"},
        "USDJPY": {"ticker": "USDJPY=X", "label": "Yahoo USD/JPY", "unit": "JPY per USD"},
        "AUDUSD": {"ticker": "AUDUSD=X", "label": "Yahoo AUD/USD", "unit": "USD per AUD"},
        "USDCAD": {"ticker": "USDCAD=X", "label": "Yahoo USD/CAD", "unit": "CAD per USD"},
        "USDCHF": {"ticker": "USDCHF=X", "label": "Yahoo USD/CHF", "unit": "CHF per USD"},
        "NZDUSD": {"ticker": "NZDUSD=X", "label": "Yahoo NZD/USD", "unit": "USD per NZD"},
        "EURJPY": {"ticker": "EURJPY=X", "label": "Yahoo EUR/JPY", "unit": "JPY per EUR"},
        "GBPJPY": {"ticker": "GBPJPY=X", "label": "Yahoo GBP/JPY", "unit": "JPY per GBP"},
        "EURGBP": {"ticker": "EURGBP=X", "label": "Yahoo EUR/GBP", "unit": "GBP per EUR"},
    },
    "Indices / Futures": {
        "US30 (Dow Futures proxy)": {"ticker": "YM=F", "label": "Yahoo E-mini Dow futures proxy for US30", "unit": "index points"},
    },
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


def fetch_yahoo_instrument_data(category: str, instrument: str) -> tuple[pd.DataFrame, dict]:
    """Fetch latest available quote and 5-minute candles for selected Yahoo symbol."""
    try:
        spec = INSTRUMENTS[category][instrument]
    except KeyError as exc:
        raise ValueError("Selected market/instrument Yahoo list mein nahi hai.") from exc
    symbol = spec["ticker"]
    ticker = yf.Ticker(symbol)
    history = _clean_yahoo_history(
        ticker.history(period="60d", interval="5m", auto_adjust=False, prepost=False)
    )
    if history.empty:
        raise RuntimeError(
            f"Yahoo Finance ticker {symbol} ne 5-minute candles nahi diye. "
            "Is instrument ke liye Yahoo intraday feed unavailable ho sakta hai."
        )
    quote = _clean_yahoo_history(
        ticker.history(period="1d", interval="1m", auto_adjust=False, prepost=False)
    )
    quote_interval = "1-minute"
    if quote.empty:
        quote = _clean_yahoo_history(
            ticker.history(period="5d", interval="5m", auto_adjust=False, prepost=False)
        )
        quote_interval = "5-minute"
    latest = quote.iloc[-1] if not quote.empty else history.iloc[-1]
    latest_time = quote.index[-1] if not quote.empty else history.index[-1]
    report = {
        "category": category,
        "instrument": instrument,
        "source": spec["label"],
        "ticker": symbol,
        "unit": spec["unit"],
        "quote_interval": quote_interval,
        "latest_price": float(latest["Close"]),
        "latest_timestamp": str(latest_time),
        "history_rows": int(len(history)),
        "history_start": str(history.index.min()),
        "history_end": str(history.index.max()),
        "history_interval": "5-minute",
        "note": "Yahoo intraday quotes may be delayed, incomplete or unavailable. US30 is represented by YM=F futures, not a broker CFD quote. Verify with your broker before trading.",
    }
    return history, report


ALIASES = {
    "timestamp": "Timestamp", "time": "Timestamp", "date": "Timestamp",
    "datetime": "Timestamp", "open": "Open", "high": "High",
    "low": "Low", "close": "Close",
}


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
        "source": "User-uploaded OHLC CSV",
    }
    return frame, report


__all__ = [
    "CISDConfig", "backtest_cisd", "find_day_setup",
    "load_gold_ohlc_csv", "fetch_yahoo_instrument_data", "INSTRUMENTS",
]
