---
name: day-trading
description: >-
  Day Trading Workflow Orchestrator for Scanner 5.0. Coordinates market
  selection, pre-market preparation, US and India scanners, catalyst review,
  completed-candle entry confirmation, stop and target planning, historical
  replay, position sizing, risk checks, alerts, paper tracking and broker
  handoff. Integrates the existing trader-* skills, NSE/BSE engines and the
  DhanHQ manual broker panel. Use when the user asks for a day-trading plan,
  a full trading workflow, intraday stock screening, a trade setup review,
  trade preparation or end-of-day review. It does not promise profits and
  never treats a scanner signal as an instruction to trade.
argument-hint: "[US|NSE|BSE] [pre-market|scan|review SYMBOL|manage SYMBOL|end-of-day]"
---

# day-trading

This is the top-level workflow for Scanner 5.0. It coordinates the existing
skills; it does not replace their tested scanners, planners, risk checks or
broker controls. The user's market, broker, account mode and risk limits must
be known before a trade is prepared.

## First principles

1. A scan result is a rule match, not a buy or sell recommendation.
2. Use the correct exchange engine and exchange clock. Never apply US market
   hours, symbols, sizing assumptions or broker payloads to NSE/BSE.
3. Prefer completed candles. An intrabar price touch is not a candle-close
   confirmation.
4. Every proposed entry needs a defined invalidation level, stop, target,
   position size and maximum loss before any order is considered.
5. A backtest or replay is historical evidence, not a forecast. State the
   sample period, data source, missing data and assumptions.
6. Do not chase stale signals. Refresh the quote and re-check the setup.
7. Paper trading is the default. Never change the user's live/paper setting.
8. No automatic signal-to-order execution. A human must review and confirm
   every live order.

## Identify the trading context

Before scanning or preparing an order, establish:

- Market: US, NSE or BSE. If absent, ask one concise question.
- Symbol or universe: a named instrument, an uploaded watchlist or a scanner
  universe.
- Session: pre-market, regular session or post-market, using the exchange's
  local time and current holiday/early-close calendar.
- Account mode: paper or live, and which broker is actually connected.
- Risk limits: capital allocated to trading, maximum loss per trade, maximum
  daily loss, trade count and whether overnight positions are forbidden.

Never infer capital, risk tolerance, broker account mode, instrument
eligibility or order quantity. If a required limit is missing, ask for it
before sizing.

## US market workflow

Run commands from `scanner-core`. Each skill's own SKILL.md is the authority
for its flags and detailed behavior.

### Before the open

1. Refresh the symbol universe when needed:
   `python3 trader-scanner/scan.py universe`
2. Scan daily setups:
   `python3 trader-scanner/scan.py daily`
3. Report symbols scanned, data failures, usable results, setup labels and
   data timestamp. Do not call partial results a full-market scan.
4. For each user-selected candidate, review the catalyst and filings with
   `trader-news`. Mention earnings, halts, offerings, regulatory events and
   material headlines where verified.

### During the session

1. Scan opening-range breakouts after the first 15-minute range is complete:
   `python3 trader-scanner/scan.py orb`
2. Confirm one selected symbol with `trader-entry`. Only a completed 1-minute
   or 5-minute bar can trigger. The current entry skill is long-side only.
3. Plan the stop and target with `trader-exit`. Do this before sizing.
4. Replay the setup with `trader-timemachine` when enough valid historical
   bars exist. State the replay assumptions and its limits.
5. Size with `trader-budget`, then run `trader-risk`. A BLOCK is final for
   that proposal. Do not modify a limit or silently edit an order to force
   PASS.
6. Only after a fresh PASS, present the exact order ticket. Use
   `trader-broker` only for a supported, connected broker and only after the
   user's explicit approval. A risk PASS is not user approval.
7. Add stop, target and flat-by alerts with `trader-alerts`. Quotes from free
   feeds may be delayed; alerts are not a substitute for broker-side orders.

### End of day

- Confirm open positions and whether each was closed before the configured
  flat-by time.
- Reconcile actual broker fills, fees and slippage; never infer fills from a
  signal or an alert alone.
- Update the paper/live ledger only from confirmed fills.
- Review rule adherence, missed setups, late entries, stop discipline and
  daily loss limits. Do not judge a process only by one day's P&L.

## NSE workflow

Use `trader-india`, not the US scanner's New York clock or US-specific order
format. Run from `scanner-core`.

### Pre-market and universe

- Review the current NSE equity universe. The included CSV is a curated
  starter list, not the full exchange listing.
- Daily scan:
  `python trader-india/india.py --universe trader-india/universe.csv --output trader/india-daily.json`
- Sector snapshot:
  `python trader-india/sectors.py --universe trader-india/universe.csv --output trader/nse-sectors.json`
- For a current exchange file, import and validate it with
  `python trader-india/universe.py --input /path/to/nse-equity-master.csv --output trader-india/universe.csv --series EQ`.

### Intraday

- Run the 5-minute scanner:
  `python trader-india/intraday.py --universe trader-india/universe.csv --output trader/india-intraday.json`
- The current engine uses completed 5-minute candles, a 15-minute opening
  range and volume confirmation. It is a screening engine, not a live tick
  engine.
- Review the symbol, signal timestamp, candle completeness, volume, spread,
  liquidity, corporate actions and any catalyst before considering a setup.
- Size conservatively with the India paper-sizing defaults and inspect the
  assumptions. Current defaults are 0.5% capital risk per trade and 20%
  maximum notional; these are software defaults, not personal advice.
- Paper ledger example:
  `python trader-india/portfolio.py --ledger trader/paper-portfolio.json open --exchange NSE --symbol RELIANCE --qty 5 --entry 1500 --stop 1480`
  Replace example quantity and prices only with values from the user's plan.
- Refresh marks only from a timestamped source and keep exchange-qualified
  keys such as `NSE:RELIANCE`.

## BSE workflow

- The BSE universe is a curated starter list. Validate numeric scrip codes
  against the latest BSE scrip master before use.
- Daily scan:
  `python trader-india/bse.py --universe trader-india/bse-universe.csv --output trader/bse-daily.json`
- Intraday scan:
  `python trader-india/bse_intraday.py --universe trader-india/bse-universe.csv --output trader/bse-intraday.json`
- Import a user-downloaded scrip master with:
  `python trader-india/bse_universe.py --input /path/to/bse-scrip-master.csv --output trader-india/bse-universe.csv`.
- Confirm the exact scrip code and exchange segment. Do not substitute an
  NSE symbol or assume every BSE scrip has reliable intraday feed coverage.

## DhanHQ workflow for India

The Streamlit dashboard includes a Dhan Broker Connect tab.

1. Connect using the user's Dhan Client ID and a current Access Token. Never
   request or store the token in chat, source code, commits or logs.
2. Use the Dhan LTP endpoint as a request-time quote snapshot. Do not call it
   a WebSocket tick stream or imply continuous streaming.
3. Check funds, holdings, positions and the order book before preparing a
   trade. Confirm the exact Dhan Security ID, exchange segment, product,
   quantity, order type and validity.
4. A scanner JSON file may be uploaded to the dashboard; a selected signal
   can prefill the order ticket. Prefill is not verification and does not
   send an order.
5. Live order placement is disabled unless the server's actual outbound IP
   matches the configured IP and Dhan has whitelisted that fixed IP. Never
   enable live orders on Streamlit Community Cloud or an unverified host.
6. Require the user to inspect the final ticket and explicitly confirm it.
   Market orders may fill at a different price; orders can be rejected or
   partially filled. Verify the broker order book and fills afterward.

The Dhan dashboard's current manual ticket is a separate path from the
original US trader-risk / trader-budget / trader-broker pipeline. Do not claim
that an India Dhan order has passed those US checks. Before live execution,
perform and record an India-specific risk review, including stop distance,
quantity, estimated charges, liquidity and maximum rupee loss.

See `trader-india/web-dashboard/DHAN_INTEGRATION.md` for setup details.

## Data quality and reporting

- US chart scans use unofficial free Yahoo endpoints and may be delayed or
  incomplete.
- NSE/BSE price scans currently use unofficial Yahoo Finance chart data and
  may be delayed, rate-limited or missing bars.
- Dhan LTP is a quote snapshot from the broker API; it is not the same as a
  subscribed streaming feed.
- User-supplied bhavcopy and scrip-master files must be validated before use.
- State the source and timestamp for every quote, candle set and signal.
- Never fabricate a missing candle, volume value, Security ID, fill or price.
- If a feed is stale, inconsistent or incomplete, stop the workflow and say
  what could not be verified.

## Mandatory risk gate

Before a live order is considered, show the user:

- instrument, exchange and direction;
- setup and exact signal/candle timestamp;
- proposed entry and current quote timestamp;
- stop, target and reward-to-risk;
- quantity and estimated order value;
- maximum loss at the stop in account currency;
- estimated brokerage, taxes and slippage where available;
- total open risk and remaining daily loss allowance;
- reason to skip if any required input is unknown or any limit is breached.

Never increase size to recover a loss. Never average down unless the user's
written strategy explicitly allows it and the risk is recalculated. Never
remove a stop to make a trade pass. Never open a position solely because
multiple indicators agree.

## What this skill never does

- It never promises a profit, win rate or certain direction.
- It never selects a trade or places an order merely because a scanner found
  a match.
- It never invents live prices, exchange IDs, liquidity, fills or account
  balances.
- It never silently changes risk limits or broker settings.
- It never sends an order from a background scan, alert or scheduled task.
- It never uses the US workflow as a substitute for NSE/BSE-specific checks.

## Related skills

- `trader-scanner`: US universe and daily/intraday scan.
- `trader-news`: catalysts, news and filings.
- `trader-entry`: completed-bar entry confirmation.
- `trader-exit`: stop and target plan.
- `trader-timemachine`: historical replay.
- `trader-budget`: position sizing.
- `trader-risk`: order and daily risk checks.
- `trader-broker`: supported US broker order handoff.
- `trader-alerts`: local price/time alerts.
- `trader-india`: NSE/BSE scanner and paper portfolio.
- `trader-broker` Dhan integration is accessed through the Streamlit dashboard, not this US broker skill.


## Safety and approval

This skill is education and tooling, not financial advice. A scanner hit,
historical replay or risk PASS is not a recommendation and is not the user's
yes. Before any live order, the user must review the exact ticket and give an
explicit yes for that order. The broker's own approval controls must remain
enabled. Never set an order tool to always allow. If the order, quantity,
price, stop or account mode changes, repeat the risk review and obtain a new
yes. Paper trading remains the default unless the user deliberately chooses
otherwise.
