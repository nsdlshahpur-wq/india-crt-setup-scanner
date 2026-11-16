# DhanHQ Live Data Integration

The CRT MTF page can optionally test a DhanHQ v2 live ticker connection.

## Streamlit App Secrets

Set these keys in the Streamlit app's Secrets (not in source code, GitHub commits, screenshots, or chat):

```toml
DHAN_CLIENT_ID = "your-client-id"
DHAN_ACCESS_TOKEN = "your-current-access-token"
```

The API key/secret are used in Dhan's authentication flow to generate an access token. The WebSocket connector itself uses Client ID + Access Token. Dhan v2 access tokens have limited validity; refresh/rotate them according to Dhan's current authentication flow.

## Instrument mapping required

The user must supply the correct Dhan exchange segment and numeric Security ID for the exact futures expiry/contract. Do not guess a Security ID or substitute spot/underlying instruments. MCX contracts use the exchange segment and security ID from Dhan's instrument master.

## Data API entitlement

A valid token alone is not sufficient. The Dhan account must have an active Data APIs subscription and required segment access. The connector is read-only and calls no order endpoints.

## Current implementation scope

- Uses DhanHQ v2 WebSocket endpoint.
- Subscribes to one selected instrument in Ticker mode.
- Parses binary ticker packet to LTP and last-trade timestamp.
- Displays a live-verified quote only when a matching packet arrives.
- Does not yet build 1m/5m/15m/1H/4H/Daily/Weekly OHLC candles from the continuous stream.
- The CRT/CISD analysis still uses the existing Yahoo historical candle source until a tested Dhan historical candle and aggregation pipeline is completed.
- No API Secret or Access Token is committed to GitHub.
