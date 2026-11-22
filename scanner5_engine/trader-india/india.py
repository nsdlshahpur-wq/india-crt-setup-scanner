#!/usr/bin/env python3
"""NSE cash-equity scanner. Standard library only; research and paper mode only.

Examples (from scanner-core):
  python trader-india/india.py --universe trader-india/universe.csv
  python trader-india/india.py --symbols RELIANCE,TCS,INFY
  python trader-india/india.py --symbols RELIANCE,TCS --offline tests/fixtures/trader-india/sample.json

Yahoo Finance chart data is unofficial and may be delayed. Signals are rule matches,
not recommendations. This module never places broker orders.
"""
import argparse
import csv
import datetime as dt
import json
import math
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import time
import yfinance as yf

IST = dt.timezone(dt.timedelta(hours=5, minutes=30), "IST")
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
USER_AGENT = "Mozilla/5.0 (compatible; Scanner5India/1.0)"


def yahoo_ticker(symbol):
    symbol = symbol.strip().upper()
    if not symbol or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789&-" for ch in symbol):
        raise ValueError("Invalid NSE symbol: " + symbol)
    return symbol + ".NS"


def fetch_yahoo_ticker(ticker, interval="1d", range_="3mo", timeout=20):
    """Fetch OHLCV from Yahoo Finance through yfinance's session/cookie handling.

    This remains Yahoo Finance data; yfinance is an unofficial client. A small
    retry/backoff is used for transient Yahoo throttling and session failures.
    """
    last_error = None
    for attempt in range(3):
        try:
            frame = yf.Ticker(ticker).history(
                period=range_, interval=interval, auto_adjust=False,
                actions=False, timeout=timeout, raise_errors=True
            )
            if frame is None or frame.empty:
                raise RuntimeError("Yahoo Finance returned no rows for " + ticker)
            bars = []
            for stamp, row in frame.iterrows():
                close = row.get("Close")
                if close is None or not math.isfinite(float(close)):
                    continue
                stamp = stamp.to_pydatetime() if hasattr(stamp, "to_pydatetime") else stamp
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=IST)
                local = stamp.astimezone(IST)
                def value(key):
                    item = row.get(key)
                    if item is None:
                        return None
                    try:
                        number = float(item)
                        return number if math.isfinite(number) else None
                    except (TypeError, ValueError):
                        return None
                bars.append({
                    "time": local.isoformat(), "open": value("Open"),
                    "high": value("High"), "low": value("Low"),
                    "close": value("Close"), "volume": value("Volume") or 0
                })
            if not bars:
                raise RuntimeError("Yahoo Finance returned no usable OHLCV bars for " + ticker)
            return bars
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError("Yahoo Finance fetch failed for {0} after 3 attempts: {1}".format(ticker, last_error))


def fetch_chart(symbol, interval="1d", range_="3mo", timeout=20):
    return fetch_yahoo_ticker(yahoo_ticker(symbol), interval=interval, range_=range_, timeout=timeout)


def load_universe(path):
    symbols = []
    with open(path, newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            symbol = (row.get("symbol") or "").strip().upper()
            if symbol and not symbol.startswith("#"):
                yahoo_ticker(symbol)
                symbols.append(symbol)
    return list(dict.fromkeys(symbols))


def sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def rsi_wilder(closes, period=14):
    if len(closes) < period + 1:
        return None
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period
    if avg_loss == 0:
        return 100.0 if avg_gain else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def atr_wilder(bars, period=14):
    if len(bars) < period + 1:
        return None
    true_ranges = []
    for i in range(1, len(bars)):
        bar, prev = bars[i], bars[i - 1]
        high, low, prev_close = bar.get("high"), bar.get("low"), prev.get("close")
        if high is None or low is None or prev_close is None:
            continue
        true_ranges.append(max(float(high) - float(low),
                               abs(float(high) - float(prev_close)),
                               abs(float(low) - float(prev_close))))
    if len(true_ranges) < period:
        return None
    value = sum(true_ranges[:period]) / period
    for tr in true_ranges[period:]:
        value = ((value * (period - 1)) + tr) / period
    return value


def normalize_daily_bars(bars, now=None):
    """Exclude today's still-forming daily candle before 15:45 IST."""
    now = now or dt.datetime.now(IST)
    clean = []
    for bar in bars:
        stamp = dt.datetime.fromisoformat(bar["time"].replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=IST)
        local = stamp.astimezone(IST)
        item = dict(bar)
        item["_date"] = local.date().isoformat()
        clean.append(item)
    if clean and clean[-1]["_date"] == now.date().isoformat() and now.timetz().replace(tzinfo=None) < dt.time(15, 45):
        clean.pop()
    return clean


def analyze_daily(symbol, raw_bars, now=None):
    bars = normalize_daily_bars(raw_bars, now=now)
    closes = [float(b["close"]) for b in bars if b.get("close") is not None]
    if len(closes) < 21:
        return {"symbol": symbol, "status": "insufficient_data", "bars": len(closes), "setups": []}
    last = closes[-1]
    prior20 = closes[-21:-1]
    ma20 = sma(closes, 20)
    rsi = rsi_wilder(closes, 14)
    atr = atr_wilder(bars, 14)
    setups = []
    if last > max(prior20):
        setups.append("breakout_20d")
    if len(closes) >= 25:
        prior_run = closes[-15:-5]
        flag = closes[-5:]
        if prior_run[0] > 0 and (max(prior_run) / min(prior_run) - 1) > 0.10 and \
           (max(flag) / min(flag) - 1) <= 0.05:
            setups.append("bull_flag")
    if len(closes) >= 21 and closes[-2] < sma(closes[:-1], 20) and last > ma20:
        setups.append("reclaim_ma20")
    if rsi is not None and rsi < 30:
        setups.append("oversold")
    if len(closes) >= 16 and rsi_wilder(closes[:-1], 14) is not None and \
       rsi_wilder(closes[:-1], 14) < 30 and last > closes[-2]:
        setups.append("oversold_bounce")
    volume = bars[-1].get("volume") if bars else None
    avg_volume = None
    vols = [float(b.get("volume") or 0) for b in bars[-21:-1]]
    if len(vols) == 20:
        avg_volume = sum(vols) / 20
    volume_ratio = (float(volume or 0) / avg_volume) if avg_volume and avg_volume > 0 else None
    # Conservative confirmation: avoid chasing an extended close far above MA20.
    extension_pct = ((last / ma20) - 1) * 100 if ma20 else None
    return {
        "symbol": symbol, "status": "ok", "as_of": bars[-1]["_date"],
        "close": round(last, 2), "ma20": round(ma20, 2) if ma20 else None,
        "rsi14": round(rsi, 2) if rsi is not None else None,
        "atr14": round(atr, 2) if atr is not None else None,
        "volume": int(volume or 0), "avg_volume20": round(avg_volume, 0) if avg_volume else None,
        "volume_ratio": round(volume_ratio, 2) if volume_ratio is not None else None,
        "extension_from_ma20_pct": round(extension_pct, 2) if extension_pct is not None else None,
        "setups": setups,
        "conservative_watch": bool(setups) and (extension_pct is None or extension_pct <= 5.0),
        "entry_rule": "Next-session confirmation only; require a completed 5-minute close above the trigger with supportive volume.",
        "stop_rule": "Use the lower of the confirmed breakout structure and a risk-sized stop; do not widen after entry.",
        "data_note": "Yahoo Finance unofficial chart feed; verify quote and corporate actions before use."
    }


def analyze_opening_range(bars, now=None, range_minutes=15):
    """Confirm ORB only from completed 5-minute bars after first 15 minutes."""
    if range_minutes < 5 or range_minutes % 5:
        raise ValueError("range_minutes must be a positive multiple of 5")
    now = now or dt.datetime.now(IST)
    parsed = []
    for bar in bars:
        stamp = dt.datetime.fromisoformat(bar["time"].replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=IST)
        local = stamp.astimezone(IST)
        if local.date() != now.date():
            continue
        start = local.timetz().replace(tzinfo=None)
        end = (local + dt.timedelta(minutes=5)).timetz().replace(tzinfo=None)
        if end > now.timetz().replace(tzinfo=None):
            continue
        parsed.append((local, bar))
    parsed.sort(key=lambda x: x[0])
    opening = [(t, b) for t, b in parsed if dt.time(9, 15) <= t.timetz().replace(tzinfo=None) < (dt.datetime.combine(now.date(), dt.time(9,15)) + dt.timedelta(minutes=range_minutes)).time()]
    after = [(t, b) for t, b in parsed if t.timetz().replace(tzinfo=None) >= (dt.datetime.combine(now.date(), dt.time(9,15)) + dt.timedelta(minutes=range_minutes)).time()]
    if len(opening) < range_minutes // 5:
        return {"status": "insufficient_opening_range", "signal": False}
    highs = [float(b["high"]) for _, b in opening if b.get("high") is not None]
    lows = [float(b["low"]) for _, b in opening if b.get("low") is not None]
    if not highs or not lows:
        return {"status": "invalid_opening_range", "signal": False}
    range_high, range_low = max(highs), min(lows)
    for stamp, bar in after:
        close = bar.get("close")
        if close is not None and float(close) > range_high:
            return {"status": "confirmed_rule_match", "signal": True,
                    "breakout_time": stamp.isoformat(), "range_high": round(range_high, 2),
                    "range_low": round(range_low, 2), "breakout_close": round(float(close), 2),
                    "stop_reference": round(range_low, 2),
                    "note": "Rule match only. Check market breadth, volume, liquidity and slippage."}
    return {"status": "no_confirmed_breakout", "signal": False,
            "range_high": round(range_high, 2), "range_low": round(range_low, 2)}


def scan(symbols, fetcher=fetch_chart, now=None):
    results, errors = [], []
    for symbol in symbols:
        try:
            bars = fetcher(symbol)
            results.append(analyze_daily(symbol, bars, now=now))
        except Exception as exc:
            errors.append({"symbol": symbol, "error": str(exc)})
    return {"market": "NSE", "mode": "research_only", "symbols_requested": len(symbols),
            "symbols_returned": len(results), "failed": len(errors), "as_of": (now or dt.datetime.now(IST)).isoformat(),
            "results": results, "errors": errors,
            "safety": "No broker orders are sent. Signals are rule matches, not buy recommendations."}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Scanner 5.0 NSE daily scanner (research/paper only)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--symbols", help="Comma-separated NSE symbols, e.g. RELIANCE,TCS,INFY")
    group.add_argument("--universe", help="CSV file with a symbol column")
    parser.add_argument("--offline", help="JSON mapping symbols to arrays of OHLCV bars; no network")
    parser.add_argument("--output", help="Write JSON results to this path")
    parser.add_argument("--show", type=int, default=25)
    args = parser.parse_args(argv)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] if args.symbols else load_universe(args.universe)
    if args.offline:
        with open(args.offline, encoding="utf-8") as handle:
            fixture = json.load(handle)
        payload = scan(symbols, fetcher=lambda s: fixture[s], now=dt.datetime.now(IST))
    else:
        payload = scan(symbols)
    rendered = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(rendered + "\n")
    print("NSE Scanner: requested {0}, returned {1}, failed {2}".format(
        payload["symbols_requested"], payload["symbols_returned"], payload["failed"]))
    hits = [r for r in payload["results"] if r.get("setups")]
    for row in hits[:max(0, args.show)]:
        print("{symbol:14} {close:>10} RSI={rsi14} MA20={ma20} setups={setups}".format(**row))
    if not hits:
        print("No setup matched the configured rules.")
    if args.output:
        print("Saved: " + args.output)
    return 0 if payload["symbols_returned"] else 1


if __name__ == "__main__":
    sys.exit(main())
