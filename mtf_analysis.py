"""Higher-timeframe to lower-timeframe CRT confirmation scanner.

Pairs: Monthly->Daily, Weekly->4H, Daily->15m, 4H->5m, 1H->1m.
A pair confirms only when the completed HTF and LTF candles both show a
same-direction liquidity sweep/reclaim plus close beyond the prior candle
range. This is a conservative sweep/MSS confirmation, not a full FVG/OB
retest engine or broker execution system.
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import yfinance as yf

from data_fetch import yahoo_ticker

PAIR_SPECS = [
    {"HTF": "Monthly", "LTF": "1D", "htf_interval": "1mo", "htf_period": "10y",
     "ltf_interval": "1d", "ltf_period": "2y"},
    {"HTF": "Weekly", "LTF": "4H", "htf_interval": "1wk", "htf_period": "5y",
     "ltf_interval": "60m", "ltf_period": "60d", "ltf_resample": "4h"},
    {"HTF": "Daily", "LTF": "15m", "htf_interval": "1d", "htf_period": "2y",
     "ltf_interval": "15m", "ltf_period": "60d"},
    {"HTF": "4H", "LTF": "5m", "htf_interval": "60m", "htf_period": "60d",
     "htf_resample": "4h", "ltf_interval": "5m", "ltf_period": "60d"},
    {"HTF": "1H", "LTF": "1m", "htf_interval": "60m", "htf_period": "60d",
     "ltf_interval": "1m", "ltf_period": "7d"},
]


def _clean_ohlc(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    data = frame.copy()
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    data.columns = [str(c).title() for c in data.columns]
    cols = ["Open", "High", "Low", "Close"]
    if not all(c in data.columns for c in cols):
        return pd.DataFrame()
    data = data[cols].copy()
    data.index = pd.to_datetime(data.index)
    if getattr(data.index, "tz", None) is not None:
        data.index = data.index.tz_localize(None)
    return data[~data.index.duplicated(keep="last")].sort_index().apply(
        pd.to_numeric, errors="coerce"
    ).dropna()


def _resample(frame: pd.DataFrame, rule: str) -> pd.DataFrame:
    if frame.empty:
        return frame
    return frame.resample(rule, label="right", closed="right").agg({
        "Open": "first", "High": "max", "Low": "min", "Close": "last"
    }).dropna()


def _download(ticker: str, period: str, interval: str) -> pd.DataFrame:
    raw = yf.download(
        ticker, period=period, interval=interval, auto_adjust=False,
        progress=False, threads=False, timeout=25,
    )
    return _clean_ohlc(raw)


def _completed(frame: pd.DataFrame) -> pd.DataFrame:
    data = _clean_ohlc(frame)
    # Drop newest bar conservatively because Yahoo may return an unfinished bar.
    return data.iloc[:-1] if len(data) > 1 else pd.DataFrame()


def _sweep_mss(frame: pd.DataFrame) -> dict[str, Any]:
    data = _completed(frame)
    if len(data) < 2:
        return {"direction": 0, "sweep": "NO DATA", "mss": "—", "close": None, "time": None}
    prev, cur = data.iloc[-2], data.iloc[-1]
    bull = cur.Low < prev.Low and cur.Close > prev.Low
    bear = cur.High > prev.High and cur.Close < prev.High
    # Confirm displacement through the opposite side of the reference candle.
    bull_mss = bull and cur.Close > prev.High
    bear_mss = bear and cur.Close < prev.Low
    direction = 1 if bull_mss else -1 if bear_mss else 0
    sweep = "BULL SWEEP" if bull else "BEAR SWEEP" if bear else "—"
    return {
        "direction": direction, "sweep": sweep,
        "mss": "BULL MSS" if bull_mss else "BEAR MSS" if bear_mss else "NO",
        "close": round(float(cur.Close), 2),
        "time": data.index[-1].strftime("%d-%b-%Y %H:%M"),
    }


def analyze_mtf_symbol(symbol: str) -> tuple[pd.DataFrame, dict[str, str]]:
    """Analyze all five HTF->LTF pairs for one Yahoo-compatible symbol."""
    ticker = yahoo_ticker(symbol)
    rows: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    cache: dict[tuple[str, str], pd.DataFrame] = {}

    def get_data(period: str, interval: str, resample: str | None = None) -> pd.DataFrame:
        key = (period, interval)
        if key not in cache:
            cache[key] = _download(ticker, period, interval)
        frame = cache[key]
        return _resample(frame, resample) if resample else frame

    for spec in PAIR_SPECS:
        htf, ltf = spec["HTF"], spec["LTF"]
        label = f"{htf} → {ltf}"
        try:
            higher = get_data(spec["htf_period"], spec["htf_interval"], spec.get("htf_resample"))
            lower = get_data(spec["ltf_period"], spec["ltf_interval"], spec.get("ltf_resample"))
            hs, ls = _sweep_mss(higher), _sweep_mss(lower)
            if hs["direction"] == 0:
                setup = "WAIT HTF"
                signal = "WAIT"
            elif ls["direction"] == 0:
                setup = "WAIT LTF CONFIRMATION"
                signal = "WAIT"
            elif hs["direction"] != ls["direction"]:
                setup = "LTF OPPOSITE — NO TRADE"
                signal = "WAIT"
            elif hs["direction"] == 1:
                setup, signal = "BULLISH HTF+LTF CONFIRMED", "BULL WATCH"
            else:
                setup, signal = "BEARISH HTF+LTF CONFIRMED", "BEAR WATCH"

            rows.append({
                "HTF → LTF": label,
                "HTF Sweep": hs["sweep"], "HTF MSS": hs["mss"],
                "LTF Sweep": ls["sweep"], "LTF MSS": ls["mss"],
                "Alignment / Setup": setup, "Signal": signal,
                "HTF Close": hs["close"], "LTF Close": ls["close"],
                "HTF Candle": hs["time"], "LTF Candle": ls["time"],
            })
            if hs["close"] is None:
                errors[label] = f"{htf} data unavailable/insufficient"
            if ls["close"] is None:
                errors[label] = (errors.get(label, "") + f"; {ltf} data unavailable/insufficient").strip("; ")
        except Exception as exc:
            errors[label] = f"{type(exc).__name__}: {str(exc)[:180]}"
            rows.append({
                "HTF → LTF": label, "HTF Sweep": "ERROR", "HTF MSS": "—",
                "LTF Sweep": "ERROR", "LTF MSS": "—",
                "Alignment / Setup": "DATA ERROR", "Signal": "WAIT",
                "HTF Close": None, "LTF Close": None,
                "HTF Candle": None, "LTF Candle": None,
            })
    return pd.DataFrame(rows), errors
