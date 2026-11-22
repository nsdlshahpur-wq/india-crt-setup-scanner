# Dhan Live Feed + Multi-Agent Paper Mode (research only)

This module is an isolated, opt-in paper-trading foundation. It does not place, modify, or cancel broker orders.

## Dhan credentials
Set `DHAN_ACCESS_TOKEN` as a server-side environment secret. Never commit tokens.
The Dhan Data API subscription is required for live feed / intraday historical endpoints.

## Historical candles
`dhan_feed.get_intraday_candles(security_id, exchange_segment, instrument, interval, from_date, to_date)`
Dhan intraday requests are limited to 90 days per request; fetch and store historical data in chunks. Confirm the exact NIFTY index security ID and segment from Dhan's current instrument master before use. Do not guess security IDs.

## Paper engine
Pass completed 5-minute OHLCV candles to:
```python
from apex_paper.agents import paper_signal
result = paper_signal(candles)
```
PaperLedger is an in-memory example ledger. Production use needs persistent storage, duplicate-signal protection, session reset, stale-feed detection, reconnect handling, and explicit candle-close scheduling.

## Live WebSocket
Dhan's official Python MarketFeed supports WebSocket subscriptions and binary packet parsing. This first patch does not start a persistent WebSocket worker or claim that a live feed is connected. Add it only after credentials, security IDs, deployment runtime and reconnect behavior are verified.

## Limits
The included agents are transparent baseline proxies, not a faithful import of every proprietary CRT rule from the separate CRT repository. FVG/CRT proxies must be validated against your actual strategy rules. No profitability is claimed.
