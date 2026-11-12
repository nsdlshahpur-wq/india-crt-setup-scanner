"""Standalone multi-timeframe structure scanner for indices and selected symbols.

This module is deliberately separate from scanner.py and does not change the
existing Daily CRT strategy. Uses Yahoo Finance intraday candles; zones are
mechanical candidates, not discretionary/guaranteed ICT labels.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
import yfinance as yf


WATCHLIST = {
    "Nifty 50": "^NSEI",
    "Bank Nifty": "^NSEBANK",
    "Nifty Financial Services (FINNIFTY)": "^CNXFINANCE",
    "Sensex": "^BSESN",
    "Nifty IT": "^CNXIT",
    "Nifty Auto": "^CNXAUTO",
    "Nifty Pharma": "^CNXPHARMA",
}


def download_intraday(symbol: str, interval: str, period: str = "60d") -> pd.DataFrame:
    """Download intraday OHLC; Yahoo limits historical intraday depth."""
    frame = yf.download(
        symbol, period=period, interval=interval, auto_adjust=False,
        progress=False, threads=False, timeout=25,
    )
    if frame is None or frame.empty:
        return pd.DataFrame()
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = [str(c[0] if isinstance(c, tuple) else c).title() for c in frame.columns]
    frame.columns = [str(c).title() for c in frame.columns]
    required = ["Open", "High", "Low", "Close"]
    if not all(c in frame.columns for c in required):
        return pd.DataFrame()
    frame = frame[required + (["Volume"] if "Volume" in frame.columns else [])].copy()
    frame.index = pd.to_datetime(frame.index)
    if getattr(frame.index, "tz", None) is not None:
        frame.index = frame.index.tz_convert("Asia/Kolkata").tz_localize(None)
    for col in required:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    return frame.dropna(subset=required).sort_index()


def _pivots(frame: pd.DataFrame, left: int = 2, right: int = 2) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    highs, lows = [], []
    for i in range(left, len(frame) - right):
        h = frame.High.iloc[i-left:i+right+1]
        l = frame.Low.iloc[i-left:i+right+1]
        if frame.High.iloc[i] == h.max() and (h == h.max()).sum() == 1:
            highs.append((i, float(frame.High.iloc[i])))
        if frame.Low.iloc[i] == l.min() and (l == l.min()).sum() == 1:
            lows.append((i, float(frame.Low.iloc[i])))
    return highs, lows


def _structure(frame: pd.DataFrame, direction: str) -> dict[str, Any]:
    if len(frame) < 12:
        return {"choch": False, "level": None, "side": "Insufficient data"}
    highs, lows = _pivots(frame)
    close = float(frame.Close.iloc[-1])
    if direction == "Bullish":
        candidates = [(i, p) for i, p in highs if i < len(frame) - 2]
        level = candidates[-1][1] if candidates else None
        crossed = level is not None and close > level and float(frame.Close.iloc[-2]) <= level
    else:
        candidates = [(i, p) for i, p in lows if i < len(frame) - 2]
        level = candidates[-1][1] if candidates else None
        crossed = level is not None and close < level and float(frame.Close.iloc[-2]) >= level
    return {"choch": bool(crossed), "level": level, "side": direction if crossed else "No fresh break"}


def _zones(frame: pd.DataFrame, direction: str) -> list[dict[str, Any]]:
    """Return latest directional FVGs and last opposite candle OB candidates."""
    out: list[dict[str, Any]] = []
    start = max(2, len(frame) - 80)
    for i in range(start, len(frame)):
        if direction == "Bullish" and float(frame.Low.iloc[i]) > float(frame.High.iloc[i-2]):
            out.append({"Type": "Bullish FVG", "Low": float(frame.High.iloc[i-2]), "High": float(frame.Low.iloc[i]), "Formed": str(frame.index[i])})
        elif direction == "Bearish" and float(frame.High.iloc[i]) < float(frame.Low.iloc[i-2]):
            out.append({"Type": "Bearish FVG", "Low": float(frame.High.iloc[i]), "High": float(frame.Low.iloc[i-2]), "Formed": str(frame.index[i])})
    # OB candidate: last opposite-colour candle before latest strong directional candle.
    for i in range(len(frame)-1, max(0, len(frame)-12), -1):
        row = frame.iloc[i]
        directional = row.Close > row.Open if direction == "Bullish" else row.Close < row.Open
        if not directional:
            continue
        for j in range(i-1, max(-1, i-8), -1):
            opposite = frame.Close.iloc[j] < frame.Open.iloc[j] if direction == "Bullish" else frame.Close.iloc[j] > frame.Open.iloc[j]
            if opposite:
                out.append({"Type": f"{direction} OB candidate", "Low": float(frame.Low.iloc[j]), "High": float(frame.High.iloc[j]), "Formed": str(frame.index[j])})
                break
        break
    return out[-8:]


def analyse_symbol(symbol: str, name: str) -> dict[str, Any]:
    daily = download_intraday(symbol, "1d", "1y")
    hourly = download_intraday(symbol, "1h", "60d")
    fifteen = download_intraday(symbol, "15m", "60d")
    if daily.empty or hourly.empty or fifteen.empty:
        raise RuntimeError("Yahoo Finance se Daily/1H/15M data poora nahi mila. Thodi der baad dobara try karein.")
    daily = daily.iloc[:-1] if len(daily) > 1 else daily
    hourly = hourly.iloc[:-1] if len(hourly) > 1 else hourly
    fifteen = fifteen.iloc[:-1] if len(fifteen) > 1 else fifteen
    if len(daily) < 30 or len(hourly) < 20 or len(fifteen) < 20:
        raise RuntimeError("Is symbol ke liye intraday history paryapt nahi hai.")

    recent_daily = daily.tail(60)
    resistance = float(recent_daily.High.iloc[:-1].tail(20).max())
    support = float(recent_daily.Low.iloc[:-1].tail(20).min())
    close = float(daily.Close.iloc[-1])
    breakout = close > resistance
    daily_bias = "Bullish" if close > float(daily.Close.rolling(20).mean().iloc[-1]) else "Bearish"
    hourly_bias = "Bullish" if float(hourly.Close.iloc[-1]) >= float(hourly.Close.rolling(20).mean().iloc[-1]) else "Bearish"
    structure = _structure(hourly, hourly_bias)
    zones = _zones(hourly, hourly_bias)
    current = float(fifteen.Close.iloc[-1])
    touched = []
    for z in zones:
        if float(fifteen.Low.tail(12).min()) <= z["High"] and float(fifteen.High.tail(12).max()) >= z["Low"]:
            z = dict(z)
            z["Retest"] = "Recent 12 bars touched zone"
            z["Status"] = "Retest candidate - 15M confirmation pending"
            touched.append(z)
        else:
            z = dict(z)
            z["Retest"] = "Not seen in recent 12 bars"
            z["Status"] = "WAITING"
            touched.append(z)
    return {
        "Name": name, "Symbol": symbol, "Last Daily Close": close,
        "Daily Bias": daily_bias, "20-session Resistance": resistance,
        "20-session Support": support, "Daily Breakout": "YES" if breakout else "NO",
        "1H Bias": hourly_bias, "1H CHoCH": "YES" if structure["choch"] else "NO",
        "1H CHoCH Reference": structure["level"], "15M Last Close": current,
        "Zones": touched, "Daily Candle": str(daily.index[-1]),
        "1H Candle": str(hourly.index[-1]), "15M Candle": str(fifteen.index[-1]),
        "Daily": daily, "Hourly": hourly, "Fifteen": fifteen,
    }
