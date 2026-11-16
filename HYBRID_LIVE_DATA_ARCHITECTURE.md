# CRT Scanner — Hybrid Live Data System

## Objective

Introduce market-specific providers while preserving the existing CRT and CISD strategy logic. The original scanner remains read-only; no order placement, options endpoints, or spot-market substitution is permitted.

## Provider routing

| Market | Primary route | Fallback / reference | Contract identity |
|---|---|---|---|
| BTC, ETH, SOL and supported crypto symbols | Binance USD-M Futures WebSocket | Binance USD-M REST / CCXT | USDT-margined perpetual futures |
| Gold | Licensed COMEX/CME feed or IBKR API | Yahoo Finance GC=F, clearly marked reference/delayed | COMEX Gold futures |
| Silver | Licensed COMEX/CME feed or IBKR API | Yahoo Finance SI=F, clearly marked reference/delayed | COMEX Silver futures |
| FX futures | Licensed CME feed or IBKR API | Existing Yahoo CME futures symbols, reference only | CME currency futures |
| US30 proxy | Licensed CBOT feed or IBKR API | Yahoo Finance YM=F, reference only | E-mini Dow futures (YM) |

## Mandatory feed-health rules

1. Store provider, exchange, contract/symbol, event timestamp, receive timestamp, interval and quote type with every update.
2. A stale timestamp must be labelled STALE; never silently retain a stale value under a LIVE label.
3. A provider disconnect must trigger a visible degraded/fallback state.
4. REST snapshots, delayed data and last completed candle closes must never be described as streaming live ticks.
5. Do not mix spot, CFD, options or unrelated contracts into a futures series.
6. Keep provider adapters independent from strategy calculations and original CRT scanner files.

## Phased implementation

- **Phase 1 — Crypto streaming:** add Binance USD-M Futures WebSocket adapter, reconnect/heartbeat handling, 5-minute kline completion checks and stale-feed detection. Retain CCXT REST as fallback.
- **Phase 2 — Licensed futures feed:** connect IBKR or another eligible licensed source for COMEX Gold/Silver, CME FX futures and CBOT YM only after account, permissions and market-data entitlements are verified.
- **Phase 3 — Dashboard:** show provider, exchange/contract, LIVE / DELAYED / STALE / FALLBACK status, last event time and connection health. Keep manual refresh as a recovery action.
- **Phase 4 — Validation:** unit tests with mocked messages, feed interruption tests, symbol/contract validation and provider-vs-reference comparison. No strategy rule changes as part of feed integration.

## Current repository state verified before implementation

- Crypto currently uses CCXT REST polling, not a persistent WebSocket stream.
- Metals, FX and index futures currently use Yahoo Finance continuous futures history; Yahoo is not guaranteed real-time.
- The Streamlit page fetches on user action and does not provide a persistent always-on feed.
- GitHub Actions scheduled runs are not a continuous market-data server.
- The latest inspected CI run compiled successfully, but pytest had one failure in `test_bullish_cisd_fvg_retest_entry_uses_next_bar_open`: expected target 154 while the strategy returned 158. This mismatch must be reconciled before declaring the branch green.

## External account decision required

The non-crypto primary feed cannot be selected responsibly until the user confirms whether an Interactive Brokers account exists and whether futures trading permissions and real-time market-data subscriptions are available. Do not buy a subscription until API access and the required contract entitlements are confirmed.
