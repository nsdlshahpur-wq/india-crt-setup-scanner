# DhanHQ market-data integration (Phase 1)

This branch adds a **read-only daily OHLC adapter** for the CRT scanner.

## What is included

- `dhan_data.py` calls DhanHQ v2 `POST /charts/historical`.
- The adapter converts Dhan's OHLC arrays and epoch timestamps into the same
  pandas OHLC DataFrame shape used by the scanner.
- It normalizes timestamps to timezone-naive Asia/Kolkata.
- It validates required credentials, dates, response fields and array lengths.
- It raises safe errors for authentication, timeout and API failures.
- `test_dhan_data.py` contains offline tests using mocked HTTP responses.

## What is not included yet

- The scanner UI does not select Dhan as its data source yet.
- Automatic symbol-to-`securityId` resolution is not implemented yet.
- No streaming/live tick feed is included.
- No order placement, modification or cancellation is included.

## Dhan setup

1. In Dhan Web, open Profile → DhanHQ Trading APIs.
2. Enable/subscribe to Data APIs if required for your account.
3. Generate a valid access token.
4. Store the token only in Streamlit Secrets; never commit it to GitHub.

Example secret:

```toml
[brokers.dhan]
client_id = "YOUR_DHAN_CLIENT_ID"
access_token = "YOUR_DHAN_ACCESS_TOKEN"
```

Dhan access tokens generated directly from Dhan Web are documented as valid for
24 hours. Check the token validity and Data API subscription status before use.

## Next implementation steps

1. Import the official Dhan instrument/security-ID master and build a verified
   NSE EQ symbol → `securityId` mapping.
2. Add a data-source selector: Yahoo Finance / DhanHQ.
3. Add per-symbol Dhan OHLC retrieval with caching, throttling and clear
   missing-mapping/data-error reporting.
4. Compare Dhan and Yahoo candles for a controlled sample before enabling Dhan
   as the default source.
5. Keep broker trading APIs disabled until the read-only market-data path and
   CRT signal validation are proven.

## Safety

This adapter is strictly read-only. Do not put access tokens in source files,
screenshots, issue comments or chat messages. A Dhan data feed is not proof that
a CRT setup is profitable; validate signals against exchange/broker charts.
