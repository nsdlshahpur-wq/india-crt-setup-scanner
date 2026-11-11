# India CRT Setup Scanner (Python)

A Streamlit dashboard for the Monthly (1M) → Daily (1D) CRT strategy.

Strategy sequence:
1. M1 is the previous completed month's High–Low range.
2. M2 must sweep exactly one side of M1 and close back inside the full M1 range.
3. M3 Daily candles are used for CHoCH and entry-zone analysis.
4. After CHoCH, entry may use a retest in ANY ONE of FVG, IFVG, OB or BOB.
5. A directional Daily confirmation close is required after the retest.
6. SL is the actual M2 sweep candle extreme. Target is opposite M1 liquidity.
7. Active BUY/SELL rows have a triggered entry and target still pending. Waiting, target-hit, stop-hit and ambiguous states are separate.

## Market universe

The main scanner keeps the user-facing choice to two options:

- **All Stocks:** NSE main-board cash-market EQ series from the official NSE EQUITY_L.csv master. BSE duplicate listings and SME scrips are intentionally excluded from this fast default universe to avoid thousands of overlapping or thinly traded instruments.
- **All Index:** only Indian equity/market indices that have an explicit Yahoo Finance ticker mapping. Unmapped catalogue names are not sent to the downloader.
- NSE main-board symbols are cached from the official exchange master locally for up to 24 hours. An exchange listing does not guarantee Yahoo Finance has historical OHLC data for every symbol.
- The universe.py module retains BSE/SME master parsers for possible future use, but the fast All Stocks scan does not invoke those additional lists.
- Downloaded OHLC data is reused within the current Streamlit session when the universe and history period have not changed. Changing strategy settings or display filters alone does not trigger a full redownload.

## Data source and limitations

The project uses **Yahoo Finance through yfinance** for daily OHLC history. It does **not** connect to Dhan, place orders, or use broker credentials. Yahoo Finance is an unofficial data source and is not an exchange-grade guaranteed real-time feed. Data may be delayed, missing, adjusted, throttled, or unavailable for some symbols. The displayed LTP is the latest downloaded daily close, not a live tick quote.

Large-universe downloads are batched. For broad scans, the downloader does not issue a separate retry request for every missing ticker; missing rows are reported rather than letting thousands of serial retry calls make the scan appear stuck. Small targeted requests still use individual retries. Yahoo Finance may rate-limit broad scans.

## Run on Windows

```powershell
py -m venv .venv
.venv\\Scripts\\activate
py -m pip install -r requirements.txt
py -m streamlit run app.py
```

Or double-click `run_windows.bat`.

## Run on macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

The dashboard normally opens at `http://localhost:8501`.

## Streamlit Community Cloud

1. Open Streamlit Community Cloud and deploy this repository.
2. Select `main` as the branch and `app.py` as the main file.
3. Deploy the app. No broker token or secret is needed.

## GitHub validation

Pushes to `main` run:
- Python compilation and offline unit/UI tests.
- A non-blocking live-data smoke test for NIFTY 50 and RELIANCE, because external Yahoo Finance availability can vary.

## Strategy notes

- The active strategy uses only Monthly and Daily context. Weekly, 4H, 1H and intraday entry pairs are not part of the active scanner UI.
- The scanner excludes today's still-forming Daily candle before 15:40 IST.
- FVG, IFVG, OB and BOB are mechanical OHLC definitions in scanner.py. They are an explicit implementation convention and should be checked against the chart.
- CHoCH is approximated by a completed Daily close beyond the most recently confirmed pivot in the Monthly sweep direction. Discretionary CHoCH labels can differ.
- Target/stop outcomes are checked from Daily OHLC after the confirmation close. If both levels are touched in one later Daily candle, the result is marked ambiguous.
- Automated tests check code and synthetic examples; they do not prove live signal accuracy or profitability. Verify every setup in TradingView or a broker chart before trading.

## Added dashboard modules

The Streamlit navigation also includes:

- **Backtesting & Performance** — replays the Monthly-Daily CRT scanner on one selected symbol and includes FVG / IFVG / OB / BOB zone type. Signals are known at completed daily close and simulated entries occur at the next session open. If stop and target are both touched within the same daily candle, the backtest assumes stop first. It applies a configurable transaction-cost/slippage estimate, risk-based sizing and reports win rate, profit factor, average R, realized-equity maximum drawdown and trade count. The backtest uses the same scanner signal logic and simulates entry at the next session open after confirmation.
- **Watchlist & Alerts** — stores a local watchlist, manually scans up to 10 symbols per run for valid Monthly-Daily CRT states, and records new in-app alerts. It does not send browser push, SMS, WhatsApp or email notifications.
- **Trade Journal** — records manual entries and exits, costs, realized P&L and R multiple. It never sends broker orders.
- **AI Market Assistant** — optional OpenAI, Gemini or Groq connector. It explains the selected symbol's scanner result and recent daily OHLC; it does not independently scan every exchange, guarantee live data, execute trades or replace the market-data feed.
- **Multiple Broker Connections** — read-only profile checks for Zerodha Kite, Upstox and DhanHQ. This does not yet switch the scanner to broker candle feeds and does not place or modify orders.

## Optional AI setup

Create an API key with OpenAI, Google AI Studio or Groq, then add it in Streamlit app settings → **Secrets**. Example:

\`\`\`toml
[ai]
openai_api_key = "YOUR_OPENAI_API_KEY"
gemini_api_key = "YOUR_GEMINI_API_KEY"
groq_api_key = "YOUR_GROQ_API_KEY"
\`\`\`

The AI page uses Gemini \`gemini-3.5-flash-lite\` or Groq \`openai/gpt-oss-20b\` by default; model IDs can be edited in the page. Free-tier quotas, eligible models and data-use terms are controlled by each provider and can change. Gemini's current free-tier terms state that submitted content may be used to improve Google products. Do not send account identifiers, broker credentials, holdings or private financial information to an AI provider.

## Optional broker profile connections

Add only the broker sections you use to Streamlit Secrets. Never put API keys or access tokens in Python source files or commit them to GitHub.

\`\`\`toml
[brokers.zerodha]
api_key = "YOUR_KITE_API_KEY"
access_token = "YOUR_KITE_ACCESS_TOKEN"

[brokers.upstox]
access_token = "YOUR_UPSTOX_ACCESS_TOKEN"

[brokers.dhan]
client_id = "YOUR_DHAN_CLIENT_ID"
access_token = "YOUR_DHAN_ACCESS_TOKEN"
\`\`\`

The broker page calls only read-only profile endpoints. Access tokens must be generated/renewed through each broker's official authentication process. Current scanner candles still come from Yahoo Finance, not from those broker connections. For reference: [Kite Connect pricing](https://zerodha.com/products/api), [Upstox OAuth docs](https://upstox.com/developer/api-documentation/authentication/), and [DhanHQ authentication](https://dhanhq.co/docs/v2/authentication/).

## Local journal / watchlist storage

Watchlist items, alert history and journal trades use SQLite at \`data/crt_dashboard.sqlite3\` by default. You can change the path with the \`CRT_APP_DB\` environment variable. The database file is excluded from Git. SQLite persists on a machine with persistent disk; some hosted app environments may reset local files during redeploy/restart. Export journal and alert CSV backups regularly. For a public or multi-user deployment, add authenticated users and a managed database with per-user access controls before storing real financial records.

## Project files

- `app.py` — Streamlit dashboard and universe selection.
- `scanner.py` — Monthly CRT sweep/reclaim, Daily CHoCH, FVG / IFVG / OB / BOB zones, retest, entry and target outcome.
- `data_fetch.py` — batched Yahoo Finance daily OHLC downloader.
- `universe.py` — NSE/BSE stock masters and Nifty equity-index catalogue.
- `test_scanner.py`, `test_crt_strategy_rules.py`, `test_app.py` — offline unit, synthetic CRT-zone and dashboard tests.
- `live_smoke_test.py` — small external market-data smoke test.
