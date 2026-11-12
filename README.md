# India CRT Setup Scanner

A single-page Streamlit dashboard for the Monthly (1M) → Daily (1D) CRT strategy.

## Dashboard

The app navigation intentionally contains only **app**. The separate Monthly-Daily rulebook, backtesting, watchlist/alerts, trade journal, AI assistant, broker connections and AI Strong CRT pages have been removed, along with their page-specific Python modules and tests.

## Strategy overview

1. **M1:** Previous completed month's High–Low liquidity range.
2. **M2:** Sweep exactly one side of M1 and close back inside the full M1 range.
3. **M3:** Use current-month completed Daily candles for CHoCH and entry-zone analysis.
4. After CHoCH, look for a retest in one of FVG, IFVG, OB or BOB, followed by a directional Daily confirmation close.
5. **Stop loss:** Actual M2 sweep-candle extreme. **Target:** Opposite M1 liquidity.
6. Only a fresh confirmation on the latest completed Daily candle is labelled BUY/SELL. Older untriggered opportunities are shown as missed/stale, not fresh entries.

These are explicit mechanical OHLC rules. They may differ from discretionary chart interpretations and do not guarantee profitable signals.

## Market data and limitations

- Daily OHLC history is downloaded from Yahoo Finance through `yfinance`.
- Yahoo Finance is an unofficial data source. Prices may be delayed, incomplete, adjusted, throttled or unavailable.
- The displayed LTP is the latest downloaded Daily close, not a live tick quote.
- Verify every candidate on a broker or TradingView chart before making a trading decision.
- The scanner is read-only and does not place, modify or cancel orders.

## Run locally

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## Streamlit Community Cloud

Deploy this repository with branch `main` and main file `app.py`. No broker token or AI API key is required.

## Validation

GitHub Actions runs Python compilation and offline pytest checks on pushes and pull requests. Live market-data smoke checks are non-blocking because the external data provider may be unavailable.

## Main files

- `app.py` — single-page Streamlit dashboard.
- `scanner.py` — Monthly sweep/reclaim, Daily CHoCH, FVG/IFVG/OB/BOB zones, retest, entry and outcome logic.
- `data_fetch.py` — Yahoo Finance daily OHLC downloader.
- `universe.py` — NSE/BSE stock and index universe.
- `test_scanner.py`, `test_crt_strategy_rules.py`, `test_choch_reference.py`, `test_data_fetch.py`, `test_app.py` — core scanner tests.
