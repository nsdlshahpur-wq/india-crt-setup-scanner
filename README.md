# India CRT Setup Scanner

A Streamlit dashboard for Indian equities and indices with CRT scanning, historical backtesting, multi-timeframe analysis and CISD entry scanning.

## Dashboard

The main app contains four sections:

- **Dashboard** — Monthly range, liquidity sweep/reclaim, Daily CHoCH and FVG/IFVG/OB/BOB retest results.
- **Backtest** — Five-year full-market historical simulation with position sizing, estimated charges, slippage, equity curve and trade history.
- **CRT MTF Analysis** — Scan selected Indian indices/stocks across the configured timeframe pairs.
- **Multi-Symbol Screener** — Apply the CRT rules across the selected market universe.

## Monthly-Daily CRT strategy

1. **M1:** Previous completed month's High–Low liquidity range.
2. **M2:** Sweep exactly one side of M1 and close back inside the full M1 range.
3. **M3:** Use current-month completed Daily candles for CHoCH and entry-zone analysis.
4. After CHoCH, look for a retest in one of FVG, IFVG, OB or BOB, followed by a directional Daily confirmation close.
5. **Stop loss:** Actual M2 sweep-candle extreme. **Target:** Opposite M1 liquidity.
6. Only a fresh confirmation on the latest completed Daily candle is labelled BUY/SELL. Older untriggered opportunities are shown as missed/stale, not fresh entries.

These are explicit mechanical OHLC rules. They may differ from discretionary chart interpretations and do not guarantee profitable signals.

## Historical backtesting

- Default test request: 5 years of Daily OHLC, ₹100,000 starting capital, 1% equity risk per trade.
- Signals are evaluated using only candles available at each historical date (no look-ahead).
- Entry is the confirming Daily candle close. SL/target checks start on the following candle.
- If one candle touches both SL and target, the result is marked ambiguous and conservatively priced at SL.
- Position size is risk-budget based and capped by available capital.
- Default estimated costs are 12 bps transaction charges and 5 bps slippage per side; both are editable.
- Win rate excludes ambiguous and end-of-data open trades. Open trades are marked to the last available close in final P&L.

**Important:** Current exchange constituents do not represent historical point-in-time constituents; delisted stocks and past constituent changes are missing (survivorship bias). Yahoo Finance history can be incomplete, adjusted or unavailable. Results are research estimates, not guaranteed or executable performance.

## Market data and limitations

- Daily OHLC history is downloaded from Yahoo Finance through `yfinance`.
- Yahoo Finance is an unofficial data source. Prices may be delayed, incomplete, adjusted, throttled or unavailable.
- The displayed LTP is the latest downloaded Daily close, not a live tick quote.
- Verify every candidate on a broker or TradingView chart before making a trading decision.
- The scanner and bots are read-only and do not place, modify or cancel orders.

## Run locally

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## Streamlit Community Cloud

Deploy this repository with branch `main` and main file `app.py`. No broker token or external language-model API key is required.

## Validation

GitHub Actions runs Python compilation and offline pytest checks on pushes and pull requests. Live market-data smoke checks are non-blocking because the external data provider may be unavailable.

## Main files

- `app.py` — Main Streamlit dashboard.
- `scanner.py` — Monthly sweep/reclaim, Daily CHoCH, FVG/IFVG/OB/BOB zones, retest, entry and outcome logic.
- `backtest.py` — No-look-ahead historical simulation, position sizing, costs, metrics and equity curve.
- `data_fetch.py` — Yahoo Finance daily OHLC downloader.
- `universe.py` — NSE/BSE stock and index universe.
- `mtf_analysis.py`, `multi_symbol_scanner.py` — Multi-timeframe and multi-symbol CRT scans.
- `cisd_scanner.py` — CRT + CISD entry/backtest rules.
- `gold_cisd_scanner.py` — Multi-asset futures CISD scanner.

## Scheduled CRT monitoring bot

- `crt_bot.py` scans the NIFTY 50 index itself plus the BSE equity universe for fresh confirmed Daily CRT setups.
- `.github/workflows/crt-bot.yml` schedules a best-effort scan on weekdays during the approximate Indian cash-market session.
- Telegram alerts require repository Actions secrets `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
- GitHub Actions is not a continuously running 24/7 server. Runs can be delayed, quotas apply, and scans do not execute on weekends/holidays.
- The bot never places or modifies orders.

## Multi-Asset Futures CISD + FVG Scanner

- Page: `pages/6_XAUUSD_Gold_CISD_Scanner.py`; engine: `gold_cisd_scanner.py`.
- Metals: Yahoo Finance continuous futures symbols `GC=F` (Gold) and `SI=F` (Silver).
- US index: `YM=F` E-mini Dow futures as the US30 proxy.
- FX futures: CME currency futures `6E=F`, `6B=F`, `6J=F`, `6A=F`, `6C=F`, `6S=F`, and `6N=F`.
- Crypto: Binance USD-M USDT-margined perpetual futures via CCXT.
- No options or spot fallback is used. If the selected futures feed is unavailable, the scanner shows an error.
- Yahoo intraday futures quotes can be delayed or unavailable; continuous futures series can be affected by contract rolls.

## CRT + CISD Entry Scanner

- Page: `pages/7_MTF_CRT_CISD_Entry_Scanner.py`.
- CRT timeframes and mapped entry timeframes are configured in the strategy engine.
- Entry zones include FVG, IFVG, OB and Advanced OB retests.
- This is a research/alert-only scanner; it does not place broker orders.

## Separate CISD Liquidity Sweep Scanner

- Page: `pages/5_CISD_Liquidity_Scanner.py`; engine: `cisd_scanner.py`.
- Uses NIFTY 50 1-minute historical OHLC resampled to NSE-aligned candles.
- Mechanical sequence: liquidity sweep and reclaim → CISD body-close confirmation → imbalance/zone formation → zone retest → next-bar entry.
- Backtest results are index points, not option/futures rupee P&L. Costs are configurable estimates.
