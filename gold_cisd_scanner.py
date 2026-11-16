"""Multi-asset CISD scanner using public market-data APIs.

Crypto: CCXT public exchange APIs (Binance, then KuCoin fallback).
Forex/metals/US30: Deriv public WebSocket market-data API, resolved dynamically
from active_symbols. No account login or trading permissions are used.

Provider symbols can differ from a broker's CFD/spot contract. Deriv only
returns symbols active on its platform. No stock/equity instruments are listed.
"""
from __future__ import annotations

import json
import re
from io import BytesIO
from typing import Any

import ccxt
import pandas as pd
import websocket

from cisd_scanner import CISDConfig, backtest_cisd, find_day_setup


INSTRUMENTS = {
    "Metals": {
        "Gold (XAUUSD)": {"provider": "Deriv", "aliases": ["XAUUSD", "GOLD", "GOLD/USD"], "unit": "USD per troy ounce"},
        "Silver (XAGUSD)": {"provider": "Deriv", "aliases": ["XAGUSD", "SILVER", "SILVER/USD"], "unit": "USD per troy ounce"},
    },
    "Crypto": {
        "Bitcoin (BTCUSD)": {"provider": "CCXT", "symbol": "BTC/USDT", "unit": "USDT"},
        "Ethereum (ETHUSD)": {"provider": "CCXT", "symbol": "ETH/USDT", "unit": "USDT"},
        "Solana (SOLUSD)": {"provider": "CCXT", "symbol": "SOL/USDT", "unit": "USDT"},
        "BNB (BNBUSD)": {"provider": "CCXT", "symbol": "BNB/USDT", "unit": "USDT"},
        "XRP (XRPUSD)": {"provider": "CCXT", "symbol": "XRP/USDT", "unit": "USDT"},
        "Cardano (ADAUSD)": {"provider": "CCXT", "symbol": "ADA/USDT", "unit": "USDT"},
        "Dogecoin (DOGEUSD)": {"provider": "CCXT", "symbol": "DOGE/USDT", "unit": "USDT"},
        "Litecoin (LTCUSD)": {"provider": "CCXT", "symbol": "LTC/USDT", "unit": "USDT"},
    },
    "Forex": {
        "EURUSD": {"provider": "Deriv", "aliases": ["EURUSD"], "unit": "USD per EUR"},
        "GBPUSD": {"provider": "Deriv", "aliases": ["GBPUSD"], "unit": "USD per GBP"},
        "USDJPY": {"provider": "Deriv", "aliases": ["USDJPY"], "unit": "JPY per USD"},
        "AUDUSD": {"provider": "Deriv", "aliases": ["AUDUSD"], "unit": "USD per AUD"},
        "USDCAD": {"provider": "Deriv", "aliases": ["USDCAD"], "unit": "CAD per USD"},
        "USDCHF": {"provider": "Deriv", "aliases": ["USDCHF"], "unit": "CHF per USD"},
        "NZDUSD": {"provider": "Deriv", "aliases": ["NZDUSD"], "unit": "USD per NZD"},
        "EURJPY": {"provider": "Deriv", "aliases": ["EURJPY"], "unit": "JPY per EUR"},
        "GBPJPY": {"provider": "Deriv", "aliases": ["GBPJPY"], "unit": "JPY per GBP"},
        "EURGBP": {"provider": "Deriv", "aliases": ["EURGBP"], "unit": "GBP per EUR"},
    },
    "Indices / Futures": {
        "US30": {"provider": "Deriv", "aliases": ["US30", "WALL STREET 30", "US WALL STREET", "DOW JONES"], "unit": "index points"},
    },
}

DERIV_WS_URL = "wss://api.derivws.com/trading/v1/options/ws/public"


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
    data = data.dropna(subset=needed).sort_index()
    data = data[~data.index.duplicated(keep="last")]
    valid = (
        (data["High"] >= data[["Open", "Close", "Low"]].max(axis=1))
        & (data["Low"] <= data[["Open", "Close", "High"]].min(axis=1))
    )
    return data.loc[valid]


def _deriv_request(ws, payload: dict, req_id: int) -> dict:
    payload["req_id"] = req_id
    ws.send(json.dumps(payload))
    for _ in range(12):
        raw = ws.recv()
        message = json.loads(raw)
        if message.get("req_id") == req_id:
            if message.get("error"):
                raise RuntimeError(message["error"].get("message", "Deriv API error"))
            return message
    raise TimeoutError(f"Deriv response timeout for request {req_id}")


def _resolve_deriv_symbol(symbols: list[dict], aliases: list[str]) -> dict:
    terms = [re.sub(r"[^A-Z0-9]", "", a.upper()) for a in aliases]
    # Prefer a direct symbol/display-name match; exclude OTC synthetic lookalikes
    # when a conventional FX/metals symbol is requested.
    for item in symbols:
        code = re.sub(r"[^A-Z0-9]", "", str(item.get("symbol", "")).upper())
        name = re.sub(r"[^A-Z0-9]", "", str(item.get("display_name", "")).upper())
        for term in terms:
            if term and (code == term or name == term or term in code or term in name):
                return item
    raise RuntimeError(
        "Deriv ke active market list mein is pair ka exact/recognisable symbol nahi mila. "
        "Kisi doosre instrument ka price use nahi kiya gaya."
    )


def _fetch_deriv_data(spec: dict) -> tuple[pd.DataFrame, dict]:
    ws = websocket.create_connection(DERIV_WS_URL, timeout=15)
    try:
        active = _deriv_request(ws, {"active_symbols": "brief"}, 1)
        available = active.get("active_symbols", [])
        market = _resolve_deriv_symbol(available, spec["aliases"])
        code = market["symbol"]
        history = _deriv_request(
            ws,
            {
                "ticks_history": code,
                "count": 500,
                "end": "latest",
                "style": "candles",
                "granularity": 300,
            },
            2,
        )
        candles = history.get("candles", [])
        if not candles:
            raise RuntimeError(f"Deriv ne {code} ke 5-minute historical candles nahi diye.")
        frame = pd.DataFrame(candles)
        frame["Timestamp"] = pd.to_datetime(frame["epoch"], unit="s", utc=True)
        frame = frame.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close"})
        frame = frame.set_index("Timestamp")[["Open", "High", "Low", "Close"]]
        frame = _clean_ohlc(frame)
        tick = _deriv_request(ws, {"ticks": code, "subscribe": 1}, 3)
        tick_data = tick.get("tick", {})
        price = float(tick_data.get("quote", frame["Close"].iloc[-1]))
        tick_epoch = tick_data.get("epoch")
        stamp = pd.to_datetime(tick_epoch, unit="s", utc=True) if tick_epoch else frame.index[-1]
        report = {
            "provider": "Deriv public WebSocket",
            "ticker": code,
            "display_name": market.get("display_name", code),
            "latest_price": price,
            "latest_timestamp": str(stamp),
            "quote_interval": "live tick snapshot",
            "history_rows": int(len(frame)),
            "history_start": str(frame.index.min()),
            "history_end": str(frame.index.max()),
            "history_interval": "5-minute",
            "unit": spec["unit"],
            "note": "Deriv public-platform quote; may differ from your broker's XAUUSD/FX/US30 CFD price and execution.",
        }
        return frame, report
    finally:
        ws.close()


def _fetch_crypto_data(spec: dict) -> tuple[pd.DataFrame, dict]:
    symbol = spec["symbol"]
    failures = []
    for exchange_class in (ccxt.binance, ccxt.kucoin):
        exchange = exchange_class({"enableRateLimit": True, "timeout": 15000})
        try:
            markets = exchange.load_markets()
            if symbol not in markets:
                failures.append(f"{exchange.id}: {symbol} not listed")
                continue
            candles = exchange.fetch_ohlcv(symbol, timeframe="5m", limit=500)
            ticker = exchange.fetch_ticker(symbol)
            if not candles:
                failures.append(f"{exchange.id}: no 5m candles")
                continue
            frame = pd.DataFrame(candles, columns=["timestamp", "Open", "High", "Low", "Close", "Volume"])
            frame["Timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
            frame = frame.set_index("Timestamp")[["Open", "High", "Low", "Close"]]
            frame = _clean_ohlc(frame)
            report = {
                "provider": f"{exchange.id.title()} public market API via CCXT",
                "ticker": symbol,
                "display_name": symbol,
                "latest_price": float(ticker["last"]),
                "latest_timestamp": str(pd.to_datetime(ticker.get("timestamp"), unit="ms", utc=True)) if ticker.get("timestamp") else str(frame.index[-1]),
                "quote_interval": "latest exchange ticker",
                "history_rows": int(len(frame)),
                "history_start": str(frame.index.min()),
                "history_end": str(frame.index.max()),
                "history_interval": "5-minute",
                "unit": spec["unit"],
                "note": "Crypto quote is from the named exchange. Exchange prices can differ slightly across venues.",
            }
            return frame, report
        except Exception as exc:
            failures.append(f"{exchange.id}: {type(exc).__name__}: {str(exc)[:120]}")
        finally:
            try:
                exchange.close()
            except Exception:
                pass
    raise RuntimeError("CCXT crypto data providers unavailable. " + " | ".join(failures))


def fetch_market_data(category: str, instrument: str) -> tuple[pd.DataFrame, dict]:
    """Fetch selected pair from live public data providers, never Yahoo fallback."""
    try:
        spec = INSTRUMENTS[category][instrument]
    except KeyError as exc:
        raise ValueError("Selected market/pair list mein nahi hai.") from exc
    if spec["provider"] == "CCXT":
        return _fetch_crypto_data(spec)
    return _fetch_deriv_data(spec)


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
