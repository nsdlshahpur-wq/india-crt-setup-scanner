# India CRT Setup Scanner (Python)

A Streamlit dashboard that ports the supplied Pine Script CRT workflow into Python:

1. **Monthly CRT bias:** the latest completed month sweeps the previous completed month's high/low and closes back inside.
2. **Daily liquidity sweep:** a daily candle runs a prior rolling high/low and closes back across it.
3. **Displacement entry:** a recent candle closes beyond a confirmed pivot (or fallback five-candle level) with a body at least `Displacement × ATR`.
4. **Risk levels:** stop at the sweep candle extreme, T1 at 2R, and T2 at the previous completed month's opposite extreme.

## Market universe

The default selection is **All NSE + BSE stocks + all indices**.

- **NSE mainboard stocks:** active securities in the official NSE cash-market `EQ` series, refreshed from NSE's `EQUITY_L.csv` and cached locally for up to 24 hours.
- **NSE SME stocks:** loaded separately from the official NSE `SME_EQUITY_L.csv` list and cached locally for up to 24 hours.
- **BSE stocks:** the app attempts to load BSE's official `SCRIP.ZIP` equity master. If that cannot be accessed, it falls back to symbols found in a recent BSE daily equity bhavcopy. That fallback only represents securities appearing in the downloaded bhavcopy; it is not a guarantee of every BSE-listed scrip.
- **Indian equity indices:** the catalogue includes Nifty broad-market, sectoral, thematic and strategy/factor equity indices, plus BSE broad/market-cap, sectoral, thematic and strategy index families. Official index names are retained even when this data vendor has no symbol mapping.
- **Data-provider mapping:** official index names are not always Yahoo Finance ticker symbols. Only index tickers explicitly mapped in `YAHOO_INDEX_SYMBOLS` are downloaded. Other official index catalogue entries remain visible in the unavailable list with the reason "no verified Yahoo Finance ticker mapping"; the app never invents ticker strings.
- **Custom symbols:** accepts NSE tickers such as `RELIANCE`, `HDFCBANK`, `INFY`, BSE-prefixed tickers such as `BSE:500325` only when the Yahoo data provider recognises the resulting ticker, and supported index aliases such as `NIFTY 50` and `NIFTY BANK`.

The Nifty and BSE index providers also publish fixed-income, bond, hybrid, multi-asset, custom and licensed indices. This CRT scanner catalogue is focused on publicly documented equity/market-index families for stock-market scanning; it is not a promise to include every custom, fixed-income or multi-asset index. The full index portfolios are larger than the equity scanner universe.

## Data source and limitations

The project uses **Yahoo Finance through `yfinance`** for daily OHLC history. It does **not** connect to Dhan, place orders, or use broker credentials. Yahoo Finance is an unofficial data source and is not an exchange-grade guaranteed real-time feed. Data may be delayed, missing, adjusted, throttled, or unavailable for some symbols. The displayed LTP is the latest downloaded daily close, not a live tick quote.

A symbol being present in an NSE/BSE exchange master does not guarantee Yahoo Finance has historical data for it. Failed and unmapped symbols are listed separately in the dashboard. The full NSE+BSE universe can be several thousand symbols; downloads are batched and a full scan may take substantial time. Yahoo Finance may rate-limit large scans. Increase or decrease the batch size in the sidebar if downloads fail.

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

- The scanner uses completed daily candles and excludes today's still-forming daily candle before 15:40 IST.
- This is a Python implementation of the supplied strategy's intent, not a byte-for-byte Pine execution clone. Differences can occur due to candle confirmation, pivot ties, vendor histories, corporate actions, and missing symbols.
- Validate signals on your broker's chart before considering any trade. This is a screening tool, not investment advice or a guaranteed signal system.

## Added dashboard modules

The Streamlit navigation also includes:

- **Backtesting & Performance** — replays the main daily three-month CRT scanner on one selected symbol. Signals are known at completed daily close and simulated entries occur at the next session open. If stop and target are both touched within the same daily candle, the backtest assumes stop first. It applies a configurable transaction-cost/slippage estimate, risk-based sizing and reports win rate, profit factor, average R, realized-equity maximum drawdown and trade count. It does not yet backtest all five MTF pairs.
- **Watchlist & Alerts** — stores a local watchlist, manually scans up to 10 symbols per run for valid CRT / entry-ready MTF states, and records new in-app alerts. It does not send browser push, SMS, WhatsApp or email notifications.
- **Trade Journal** — records manual entries and exits, costs, realized P&L and R multiple. It never sends broker orders.
- **AI Market Assistant** — optional Gemini or Groq connector. It explains the selected symbol's scanner result and recent daily OHLC; it does not independently scan every exchange, guarantee live data, execute trades or replace the market-data feed.
- **Multiple Broker Connections** — read-only profile checks for Zerodha Kite, Upstox and DhanHQ. This does not yet switch the scanner to broker candle feeds and does not place or modify orders.

## Optional AI setup

Create an API key with Google AI Studio or Groq, then add it in Streamlit app settings → **Secrets**. Example:

\`\`\`toml
[ai]
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
- `scanner.py` — CRT bias, sweep, ATR, displacement, entry and target calculations.
- `data_fetch.py` — batched Yahoo Finance daily OHLC downloader.
- `universe.py` — NSE/BSE stock masters and Nifty equity-index catalogue.
- `test_scanner.py`, `test_app.py` — offline unit and dashboard tests.
- `live_smoke_test.py` — small external market-data smoke test.
