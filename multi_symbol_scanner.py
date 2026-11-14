"""Multi-symbol Monthly CRT -> Daily confirmation scanner.
Uses the same Monthly/Daily strategy engine as the single-symbol scanner.
Read-only; no broker orders are placed.
"""
from __future__ import annotations
from typing import Any
import pandas as pd
import yfinance as yf
from data_fetch import yahoo_ticker
from scanner import ScanConfig, scan_symbol as scan_monthly_daily


def _clean(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    data = frame.copy()
    if isinstance(data.columns, pd.MultiIndex):
        fields = {"open", "high", "low", "close", "volume"}
        data.columns = [
            next((str(x).title() for x in col if str(x).lower() in fields),
                 str(col[0]).title()) for col in data.columns
        ]
    data.columns = [str(c).strip().title() for c in data.columns]
    required = ["Open", "High", "Low", "Close"]
    if not all(c in data.columns for c in required):
        return pd.DataFrame()
    data = data[required].copy()
    data.index = pd.to_datetime(data.index)
    if getattr(data.index, "tz", None) is not None:
        data.index = data.index.tz_localize(None)
    return data[~data.index.duplicated(keep="last")].sort_index().apply(
        pd.to_numeric, errors="coerce"
    ).dropna()


def _display_row(result: dict[str, Any], symbol: str, ticker: str) -> dict[str, Any]:
    entry, sl = result.get("Entry"), result.get("SL")
    target = result.get("Target (M1 Monthly H/L)")
    rr = None
    if pd.notna(entry) and pd.notna(sl) and pd.notna(target):
        risk = abs(float(entry) - float(sl))
        rr = round(abs(float(target) - float(entry)) / risk, 2) if risk else None
    setup = str(result.get("Setup", "No Valid Monthly Sweep"))
    return {
        "Symbol": symbol, "Yahoo Ticker": ticker,
        "Strategy": "Monthly M1/M2 -> Daily CHoCH -> Zone Retest -> Daily Close",
        "HTF Trend": str(result.get("Bias", "Neutral")).upper(),
        "Sweep": result.get("Sweep Type", "No confirmed sweep"),
        "MSS": result.get("CHoCH Rule", "Daily CHoCH not confirmed"),
        "Zone": result.get("Entry Zone Type") or result.get("Available Entry Zones") or "—",
        "Signal": "LONG" if setup == "BUY" else "SHORT" if setup == "SELL" else "WAIT",
        "Setup": setup, "Price": result.get("LTP"), "Entry": entry,
        "SL": sl, "Target": target, "RR": rr,
        "Entry Status": result.get("Entry Status", "WAITING"),
        "Monthly Status": result.get("Monthly Status", "—"),
        "Sweep Date": result.get("Sweep Date"), "CHoCH Date": result.get("CHoCH Date"),
        "Retest Date": result.get("Retest Date"), "Entry Date": result.get("Entry Date"),
        "Status": result.get("Setup Reason", ""),
        "Target Status": result.get("Target Status", "NOT READY"),
        "M1 High": result.get("M1 High"), "M1 Low": result.get("M1 Low"),
        "Sweep Candle High": result.get("Sweep Candle High"),
        "Sweep Candle Low": result.get("Sweep Candle Low"),
    }


def scan_symbol(symbol: str, timeframe: str = "Daily", pivot_len: int = 3,
                mss_lookback: int = 10, zone_lookback: int = 30,
                min_rr: float = 1.5) -> dict[str, Any]:
    """Scan one symbol; execution timeframe for this strategy is always Daily."""
    raw_symbol = str(symbol).strip().upper()
    ticker = yahoo_ticker(raw_symbol)
    try:
        raw = yf.download(
            ticker, period="10y", interval="1d", auto_adjust=False,
            actions=False, progress=False, threads=False, timeout=25,
        )
        frame = _clean(raw)
        if frame.empty:
            raise ValueError("Yahoo Finance returned no usable Daily OHLC data")
        config = ScanConfig(
            pivot_left=max(1, int(pivot_len)),
            pivot_right=max(1, int(pivot_len)),
            entry_valid_days=3, ob_lookback_days=20,
            bob_lookback_days=max(1, int(zone_lookback)),
        )
        result = scan_monthly_daily(raw_symbol, raw_symbol, frame, config)
        if result is None:
            raise ValueError(f"Insufficient Daily history for Monthly CRT ({len(frame)} candles)")
        return _display_row(result, raw_symbol, ticker)
    except Exception as exc:
        return {
            "Symbol": raw_symbol, "Yahoo Ticker": ticker,
            "Strategy": "Monthly M1/M2 -> Daily CHoCH -> Zone Retest -> Daily Close",
            "HTF Trend": "ERROR", "Sweep": "—", "MSS": "—", "Zone": "—",
            "Signal": "WAIT", "Setup": "DATA ERROR", "Price": None,
            "Entry": None, "SL": None, "Target": None, "RR": None,
            "Entry Status": "WAITING", "Monthly Status": "ERROR",
            "Status": f"{type(exc).__name__}: {str(exc)[:180]}",
            "Target Status": "NOT READY",
        }


def scan_symbols(symbols: list[str], timeframe: str = "Daily", **kwargs: Any) -> pd.DataFrame:
    """Scan up to 10 symbols using identical Monthly->Daily CRT rules."""
    unique = list(dict.fromkeys(str(s).strip() for s in symbols if str(s).strip()))[:10]
    rows = [scan_symbol(symbol, timeframe=timeframe, **kwargs) for symbol in unique]
    result = pd.DataFrame(rows)
    if not result.empty:
        result["_rank"] = result["Signal"].map({"LONG": 0, "SHORT": 1, "WAIT": 2}).fillna(3)
        result = result.sort_values(["_rank", "Symbol"]).drop(columns="_rank").reset_index(drop=True)
    return result
