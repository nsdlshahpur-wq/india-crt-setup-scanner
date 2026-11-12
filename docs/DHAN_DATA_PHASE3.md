# DhanHQ Streamlit integration (Phase 3)

## Included

- Sidebar source selector: Yahoo Finance or DhanHQ.
- Dhan credentials are read from Streamlit Secrets or environment variables; no token is stored in code.
- The official Dhan NSE EQ instrument master is downloaded and cached for 24 hours.
- NSE cash-equity daily OHLC is routed through the existing CRT scanner.
- Per-symbol errors are shown in the existing Data Errors section.
- Daily requests are spaced to remain below Dhan's documented 5 Data API requests/second limit.

## Configure Streamlit Secrets

```toml
[brokers.dhan]
access_token = "YOUR_24_HOUR_ACCESS_TOKEN"
```

Alternatively set environment variable `DHAN_ACCESS_TOKEN`. Never commit secrets.

## Limits

- This first UI integration supports NSE cash equities only. Index, BSE, SME and derivatives symbols are rejected rather than guessed.
- Full NSE scans can take several minutes because historical candles are requested per security. Start with a smaller test list if validating the connection.
- Dhan daily candles are historical EOD candles, not a live LTP stream.
- Dhan Data API subscription and a valid, unexpired token are required.
- No order placement, modification or cancellation is implemented.

## Validation

Run `python -m unittest test_dhan_data test_dhan_instruments test_dhan_scanner`.
