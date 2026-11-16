"""Provider registry and feed-health helpers for the CRT Hybrid Live Data System.

This module deliberately does not pretend that REST polling is a live stream.
Provider adapters are added independently so each market can be validated
without changing the original CRT scanner or its strategy rules.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass(frozen=True)
class FeedSpec:
    market: str
    primary: str
    fallback: str
    instrument_type: str
    live_capability: str
    requires_subscription: bool = False


FEED_REGISTRY = {\n    "MCX_GOLD": FeedSpec("Metals", "DhanHQ MCX WebSocket", "DhanHQ REST quote / historical candles", "MCX Gold futures", "stream", True),\n    "MCX_SILVER": FeedSpec("Metals", "DhanHQ MCX WebSocket", "DhanHQ REST quote / historical candles", "MCX Silver futures", "stream", True),
    "BTC": FeedSpec("Crypto", "CoinDCX Futures WebSocket", "CoinDCX Futures REST / candle history", "USDT-M perpetual futures", "stream"),
    "ETH": FeedSpec("Crypto", "Binance USD-M Futures WebSocket", "Binance USD-M REST / CCXT", "USDT-M perpetual futures", "stream"),
    "SOL": FeedSpec("Crypto", "Binance USD-M Futures WebSocket", "Binance USD-M REST / CCXT", "USDT-M perpetual futures", "stream"),
    "GOLD": FeedSpec("Metals", "Databento / IBKR licensed COMEX feed", "Yahoo Finance GC=F reference", "COMEX Gold futures", "provider-dependent", True),
    "SILVER": FeedSpec("Metals", "Databento / IBKR licensed COMEX feed", "Yahoo Finance SI=F reference", "COMEX Silver futures", "provider-dependent", True),
    "FX_FUTURES": FeedSpec("FX", "Databento / IBKR licensed CME feed", "Yahoo Finance CME futures symbols", "CME currency futures", "provider-dependent", True),
    "US30": FeedSpec("Index", "Databento / IBKR licensed CBOT feed", "Yahoo Finance YM=F reference", "E-mini Dow futures (YM)", "provider-dependent", True),
}


def feed_age_seconds(timestamp: datetime, now: Optional[datetime] = None) -> float:
    """Return non-negative age in seconds; naive timestamps are treated as UTC."""
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return max(0.0, (current - timestamp.astimezone(timezone.utc)).total_seconds())


def feed_health(timestamp: datetime, *, max_age_seconds: int, now: Optional[datetime] = None) -> dict:
    """Classify a feed timestamp without ever labelling stale data as live."""
    age = feed_age_seconds(timestamp, now=now)
    fresh = age <= max_age_seconds
    return {
        "status": "FRESH" if fresh else "STALE",
        "is_fresh": fresh,
        "age_seconds": round(age, 3),
        "max_age_seconds": int(max_age_seconds),
    }


__all__ = ["FeedSpec", "FEED_REGISTRY", "feed_age_seconds", "feed_health"]
