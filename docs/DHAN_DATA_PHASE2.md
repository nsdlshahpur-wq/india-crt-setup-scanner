# DhanHQ market-data integration (Phase 2)

## What this phase adds

- Downloads the official Dhan compact instrument master CSV.
- Parses only NSE cash-equity rows (NSE, equity segment E, instrument EQUITY, and EQ/blank series where supplied).
- Resolves symbols such as RELIANCE, RELIANCE.NS, and NSE:RELIANCE to a verified Dhan securityId.
- Rejects BSE tickers, index tickers, missing matches, ambiguous matches, and malformed masters instead of guessing.
- Adds offline mocked tests.

Official source: https://images.dhan.co/api-data/api-scrip-master.csv

## Scope and limitations

This is a resolver library, not yet a user-facing Dhan data-source selector. The scanner UI still uses Yahoo Finance until the next integration phase. The parser intentionally limits this first pass to NSE main-board cash equities; index instruments and BSE listings need their own explicit segment mappings. The master should be refreshed daily and cached by the app rather than committed as a static CSV.

## Security

The instrument master is public and requires no access token. Dhan access tokens remain exclusively in Streamlit Secrets. This phase is read-only and has no order-placement capability.
