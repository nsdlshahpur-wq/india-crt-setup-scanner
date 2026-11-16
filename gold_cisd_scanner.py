"""Multi-asset CISD scanner using futures market data only.

Metals, US index and FX: Yahoo Finance continuous futures symbols (=F).
Crypto: Binance USD-M perpetual futures through CCXT (not spot, not options).
No Deriv options endpoints are used. No orders are placed.
"""
from __future__ import annotations

from io import BytesIO
from typing import Any

import ccxt
import pandas as pd
import yfinance as yf

from cisd_scanner import CISDConfig, backtest_cisd, find_day_setup


INSTRUMENTS = {
    "Metals Futures": {
        "Gold Futures (GC=F)": {"provider": "Yahoo Finance Futures", "ticker": "GC=F", "unit": "USD per troy ounce"},
        "Silver Futures (SI=F)": {"provider": "Yahoo Finance Futures", "ticker": "SI=F", "unit": "USD per troy ounce"},
    },
    "Crypto Perpetual Futures": {
        "Bitcoin USDT-M Perpetual": {"provider": "Binance USD-M Futures", "symbol": "BTC/USDT:USDT", "unit": "USDT"},
        "Ethereum USDT-M Perpetual": {"provider": "Binance USD-M Futures", "symbol": "ETH/USDT:USDT", "unit": "USDT"},
        "Solana USDT-M Perpetual": {"provider": "Binance USD-M Futures", "symbol": "SOL/USDT:USDT", "unit": "USDT"},
        "BNB USDT-M Perpetual": {"provider": "Binance USD-M Futures", "symbol": "BNB/USDT:USDT", "unit": "USDT"},
        "XRP USDT-M Perpetual": {"provider": "Binance USD-M Futures", "symbol": "XRP/USDT:USDT", "unit": "USDT"},
        "ADA USDT-M Perpetual": {"provider": "Binance USD-M Futures", "symbol": "ADA/USDT:USDT", "unit": "USDT"},
        "DOGE USDT-M Perpetual": {"provider": "Binance USD-M Futures", "symbol": "DOGE/USDT:USDT", "unit": "USDT"},
        "LTC USDT-M Perpetual": {"provider": "Binance USD-M Futures", "symbol": "LTC/USDT:USDT", "unit": "USDT"},
    },
    "FX Futures": {
        "Euro FX Futures (6E=F)": {"provider": "Yahoo Finance Futures", "ticker": "6E=F", "unit": "USD per EUR"},
        "British Pound Futures (6B=F)": {"provider": "Yahoo Finance Futures", "ticker": "6B=F", "unit": "USD per GBP"},
        "Japanese Yen Futures (6J=F)": {"provider": "Yahoo Finance Futures", "ticker": "6J=F", "unit": "USD per JPY"},
        "Australian Dollar Futures (6A=F)": {"provider": "Yahoo Finance Futures", "ticker": "6A=F", "unit": "USD per AUD"},
        "Canadian Dollar Futures (6C=F)": {"provider": "Yahoo Finance Futures", "ticker": "6C=F", "unit": "USD per CAD"},
        "Swiss Franc Futures (6S=F)": {"provider": "Yahoo Finance Futures", "ticker": "6S=F", "unit": "USD per CHF"},
        "New Zealand Dollar Futures (6N=F)": {"provider": "Yahoo Finance Futures", "ticker": "6N=F", "unit": "USD per NZD"},
    },
    "Index Futures": {
        "Dow Jones E-mini Futures / US30 proxy (YM=F)": {"provider": "Yahoo Finance Futures", "ticker": "YM=F", "unit": "index points"},
    },
}


def _clean_ohlc(frame: pd.DataFrame) -> pd.DataFrame:
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
    data.index = pd.to_datetime(data.index, utc=True)
    for col in needed:
        data[col] = pd.to_numeric(data[col], errors="coerce")
    data = data.dropna(subset=needed).sort_index()
    data = data[~data.index.duplicated(keep="last")]
    valid = (
        (data["High"] >= data[["Open", "Close", "Low"]].max(axis=1))
        & (data["Low"] <= data[["Open", "Close", "High"]].min(axis=1))
    )
    return data.loc[valid]


def _fetch_yahoo_future(spec: dict) -> tuple[pd.DataFrame, dict]:
    ticker = spec["ticker"]
    instrument = yf.Ticker(ticker)
    # Yahoo intraday history availability depends on the futures contract/feed.
    raw = instrument.history(period="5d", interval="5m", auto_adjust=False, prepost=True)
    frame = _clean_ohlc(raw)
    if frame.empty:
        raise RuntimeError(
            f"Yahoo Finance se {ticker} ka 5-minute futures data nahi mila. "
            "Feed/market-hours limitation ho sakti hai; spot ya option data fallback nahi hoga."
        )
    try:
        fast = instrument.fast_info
        last = fast.get("last_price")
    except Exception:
        last = None
    # Quote snapshot must belong to the same futures ticker. If unavailable,
    # show latest returned 5m candle close and label it accordingly.
    if last is not None and pd.notna(last):
        price = float(last)
        quote_type = "Yahoo latest futures quote"
        stamp = pd.Timestamp.now(tz="UTC")
    else:
        price = float(frame["Close"].iloc[-1])
        quote_type = "latest available 5-minute futures candle close (not a live tick)"
        stamp = frame.index[-1]
    report = {
        "provider": "Yahoo Finance continuous futures feed",
        "ticker": ticker,
        "display_name": ticker,
        "latest_price": price,
        "latest_timestamp": str(stamp),
        "quote_interval": quote_type,
        "history_rows": int(len(frame)),
        "history_start": str(frame.index.min()),
        "history_end": str(frame.index.max()),
        "history_interval": "5-minute",
        "unit": spec["unit"],
        "note": "Continuous futures symbol; Yahoo quotes may be delayed and are not guaranteed real-time. Futures contract roll can affect the continuous series.",
    }
    return frame, report


def _fetch_crypto_future(spec: dict) -> tuple[pd.DataFrame, dict]:
    symbol = spec["symbol"]
    exchange = ccxt.binanceusdm({"enableRateLimit": True, "timeout": 20000})
    try:
        markets = exchange.load_markets()
        market = markets.get(symbol)
        if not market or not (market.get("swap") or market.get("future")):
            raise RuntimeError(f"{symbol} Binance USD-M futures market mein listed nahi mila.")
        candles = exchange.fetch_ohlcv(symbol, timeframe="5m", limit=500)
        ticker = exchange.fetch_ticker(symbol)
        if not candles:
            raise RuntimeError(f"{symbol} ka futures 5-minute OHLCV data nahi mila.")
        frame = pd.DataFrame(candles, columns=["timestamp", "Open", "High", "Low", "Close", "Volume"])
        frame["Timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
        frame = frame.set_index("Timestamp")[["Open", "High", "Low", "Close"]]
        frame = _clean_ohlc(frame)
        report = {
            "provider": "Binance USD-M Futures via CCXT",
            "ticker": symbol,
            "display_name": symbol,
            "latest_price": float(ticker["last"]),
            "latest_timestamp": str(pd.to_datetime(ticker.get("timestamp"), unit="ms", utc=True)) if ticker.get("timestamp") else str(frame.index[-1]),
            "quote_interval": "latest Binance USD-M futures ticker",
            "history_rows": int(len(frame)),
            "history_start": str(frame.index.min()),
            "history_end": str(frame.index.max()),
            "history_interval": "5-minute",
            "unit": spec["unit"],
            "note": "Binance USDT-margined perpetual futures market data, not spot and not options. Exchange price may differ from other venues.",
        }
        return frame, report
    finally:
        try:
            exchange.close()
        except Exception:
            pass


def fetch_market_data(category: str, instrument: str) -> tuple[pd.DataFrame, dict]:
    """Fetch only futures/derivatives markets; never fall back to spot or options."""
    try:
        spec = INSTRUMENTS[category][instrument]
    except KeyError as exc:
        raise ValueError("Selected futures market/pair list mein nahi hai.") from exc
    if category == "Crypto Perpetual Futures":
        return _fetch_crypto_future(spec)
    return _fetch_yahoo_future(spec)


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
    raw["Timestamp"] = pd.to_datetime(raw["Timestamp"], errors="coerce", utc=True)
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
    "load_gold_ohlc_csv", "fetch_market_data", "INSTRUMENTS",
]
