# Scanner 5.0 — Standalone Engine

This directory contains a vendored copy of the independent Scanner 5.0 India research engine from the Scanner-5.0 project.

## Isolation boundary

- The engine is stored under `scanner5_engine/trader-india/`.
- It does not import or call the Indian CRT strategy, its scanner, its signals, or its risk rules.
- The existing CRT tabs and CRT code remain unchanged.
- Scanner 5.0 uses its own NSE/BSE rules, universe files and outputs.

## Run from the repository root

The Streamlit tab launches these scripts as separate Python processes:

- NSE daily: `scanner5_engine/trader-india/india.py`
- NSE intraday: `scanner5_engine/trader-india/intraday.py`
- BSE daily: `scanner5_engine/trader-india/bse.py`
- BSE intraday: `scanner5_engine/trader-india/bse_intraday.py`

Optional research tools are also included: sector snapshots, normalized NSE F&O futures OI analysis, position sizing, paper portfolio, daily-bar backtest and local alerts.

## Data and trading limitations

NSE .NS and BSE .BO data use an unofficial Yahoo Finance chart feed and can be delayed, incomplete or unavailable. Included universes are starter samples, not complete exchange listings. F&O analysis requires a user-supplied normalized CSV. This integration does not enable broker order routing or auto-trading. Research outputs are not buy/sell recommendations.
