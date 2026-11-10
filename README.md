# India CRT Setup Scanner (Python)

A Streamlit dashboard that ports the supplied Pine Script CRT workflow into Python:

1. **Monthly CRT bias:** the latest completed month sweeps the previous completed month's high/low and closes back inside.
2. **Daily liquidity sweep:** a daily candle runs a prior rolling high/low and closes back across it.
3. **Displacement entry:** a recent candle closes beyond a confirmed pivot (or fallback five-candle level) with a body at least `Displacement × ATR`.
4. **Risk levels:** stop at the sweep candle extreme, T1 at 2R, and T2 at the previous completed month's opposite extreme.

## Market coverage

- **All NSE EQ-series stocks:** downloads the current official NSE `EQUITY_L.csv` list and filters to the `EQ` series.
- **Major Indian indices:** includes NIFTY 50, NIFTY Bank, NIFTY Financial Services, NIFTY 100, sector indices, SENSEX and India VIX where Yahoo Finance provides data.
- **Custom symbols:** accepts NSE tickers such as `RELIANCE`, `HDFCBANK`, `INFY`, and index names such as `NIFTY 50`, `NIFTY BANK`.

“All NSE EQ stocks” means active securities in the NSE cash-market EQ series returned by the official list. It does not automatically include BSE-only listings, SME series, ETFs, futures/options contracts, or every index published by every exchange. Yahoo Finance may not have data for every listed security or index.

## Data source and limitations

The project uses **Yahoo Finance through `yfinance`** for daily OHLC history. It does **not** connect to Dhan, place orders, or use broker credentials. Yahoo Finance is an unofficial data source and is not an exchange-grade guaranteed real-time feed. Data may be delayed, missing, adjusted, throttled, or unavailable for some symbols. The displayed LTP is the latest downloaded daily close, not a live tick quote.

The full NSE equity universe can contain a large number of symbols. Downloads are split into configurable batches; large scans can take time and some symbols may fail. Failed symbols are listed in the dashboard. NSE may also restrict automated CSV downloads; the app caches the last successful list locally for 24 hours.

## Run on Windows

```powershell
py -m venv .venv
.venv\\Scripts\\activate
py -m pip install -r requirements.txt
py -m streamlit run app.py
```

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

## Strategy notes

- The scanner uses completed daily candles and excludes today's still-forming daily candle before 15:40 IST.
- This is a Python implementation of the supplied strategy's intent, not a byte-for-byte Pine execution clone. Differences can occur due to candle confirmation, pivot ties, vendor histories, corporate actions, and missing symbols.
- Validate signals on your broker's chart before considering any trade. This is a screening tool, not investment advice or a guaranteed signal system.

## Project files

- `app.py` — Streamlit dashboard.
- `scanner.py` — CRT bias, sweep, ATR, displacement, entry and target calculations.
- `data_fetch.py` — batched Yahoo Finance daily OHLC downloader.
- `universe.py` — NSE EQ-series stock list and Indian index symbol map.
- `test_scanner.py` — offline unit checks.
