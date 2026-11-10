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
- **Nifty equity indices:** the catalogue includes broad-market, sectoral, thematic and strategy/factor indices published in the Nifty equity factsheet, plus selected BSE benchmark-index names.
- **Data-provider mapping:** official index names are not always Yahoo Finance ticker symbols. Only index tickers explicitly mapped in `YAHOO_INDEX_SYMBOLS` are downloaded. Other official index catalogue entries remain visible in the unavailable list with the reason "no verified Yahoo Finance ticker mapping"; the app never invents ticker strings.
- **Custom symbols:** accepts NSE tickers such as `RELIANCE`, `HDFCBANK`, `INFY`, BSE-prefixed tickers such as `BSE:500325` only when the Yahoo data provider recognises the resulting ticker, and supported index aliases such as `NIFTY 50` and `NIFTY BANK`.

The Nifty brand portfolio contains many other index families, including fixed-income, bond, hybrid and multi-asset indices. This CRT scanner catalogue is focused on equity/market indices; it is not a catalogue of every fixed-income or hybrid index in the Nifty portfolio. The official Nifty index factsheet is the reference list.

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

## Project files

- `app.py` — Streamlit dashboard and universe selection.
- `scanner.py` — CRT bias, sweep, ATR, displacement, entry and target calculations.
- `data_fetch.py` — batched Yahoo Finance daily OHLC downloader.
- `universe.py` — NSE/BSE stock masters and Nifty equity-index catalogue.
- `test_scanner.py`, `test_app.py` — offline unit and dashboard tests.
- `live_smoke_test.py` — small external market-data smoke test.
