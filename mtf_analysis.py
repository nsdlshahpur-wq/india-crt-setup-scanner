"""CRT HTF->LTF scanner using the SAME FVG/IFVG/OB/BOB retest rules as scanner.py."""
from __future__ import annotations

from typing import Any

import pandas as pd
import yfinance as yf

from data_fetch import yahoo_ticker
from scanner import (
    ScanConfig, _collect_entry_zones, _find_entry_in_zones,
    _confirmed_pivots, _zone_is_active,
)

PAIR_SPECS = [
    {"HTF": "Monthly", "LTF": "Daily", "htf_period": "10y", "htf_interval": "1mo",
     "ltf_period": "2y", "ltf_interval": "1d"},
    {"HTF": "Weekly", "LTF": "4H", "htf_period": "5y", "htf_interval": "1wk",
     "ltf_period": "60d", "ltf_interval": "60m", "ltf_resample": "4h"},
    {"HTF": "Daily", "LTF": "1H", "htf_period": "2y", "htf_interval": "1d",
     "ltf_period": "60d", "ltf_interval": "60m"},
    {"HTF": "4H", "LTF": "5m", "htf_period": "60d", "htf_interval": "60m",
     "htf_resample": "4h", "ltf_period": "60d", "ltf_interval": "5m"},
    {"HTF": "1H", "LTF": "5m", "htf_period": "60d", "htf_interval": "60m",
     "ltf_period": "60d", "ltf_interval": "5m"},
]

CONFIG = ScanConfig()


def _clean_ohlc(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    data = frame.copy()
    if isinstance(data.columns, pd.MultiIndex):
        names = {"open", "high", "low", "close", "volume"}
        data.columns = [
            next((str(x).title() for x in col if str(x).lower() in names), str(col[0]).title())
            for col in data.columns
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


def _resample(frame: pd.DataFrame, rule: str) -> pd.DataFrame:
    if frame.empty:
        return frame
    return frame.resample(rule, label="right", closed="right").agg({
        "Open": "first", "High": "max", "Low": "min", "Close": "last"
    }).dropna()


def _download(ticker: str, period: str, interval: str) -> pd.DataFrame:
    return _clean_ohlc(yf.download(
        ticker, period=period, interval=interval, auto_adjust=False,
        progress=False, threads=False, timeout=25,
    ))


def _closed_bars(frame: pd.DataFrame) -> pd.DataFrame:
    data = _clean_ohlc(frame)
    return data.iloc[:-1] if len(data) > 1 else pd.DataFrame()


def _sweep_and_mss(frame: pd.DataFrame) -> dict[str, Any]:
    """Find latest sweep and subsequent confirmed pivot break, without look-ahead."""
    data = _closed_bars(frame)
    empty = {"direction": 0, "sweep": "NO DATA", "mss": "—", "sweep_index": None,
             "choch_index": None, "close": None, "time": None}
    if len(data) < max(12, CONFIG.pivot_left + CONFIG.pivot_right + 4):
        return empty
    highs, lows = data.High, data.Low
    bull_sweeps = [i for i in range(1, len(data))
                   if lows.iloc[i] < lows.iloc[i-1] and data.Close.iloc[i] > lows.iloc[i-1]]
    bear_sweeps = [i for i in range(1, len(data))
                   if highs.iloc[i] > highs.iloc[i-1] and data.Close.iloc[i] < highs.iloc[i-1]]
    candidates = [(i, 1) for i in bull_sweeps] + [(i, -1) for i in bear_sweeps]
    if not candidates:
        out = dict(empty)
        out.update({"sweep": "—", "mss": "NO", "close": round(float(data.Close.iloc[-1]), 2),
                    "time": data.index[-1].strftime("%d-%b-%Y %H:%M")})
        return out
    sweep_i, direction = max(candidates, key=lambda item: item[0])
    pivots = _confirmed_pivots(
        data.High if direction == 1 else data.Low,
        CONFIG.pivot_left, CONFIG.pivot_right, is_high=(direction == 1)
    )
    level = None
    choch_i = None
    for i in range(sweep_i + 1, len(data)):
        available = pivots.iloc[:i].dropna()
        if available.empty:
            continue
        level = float(available.iloc[-1])
        if (float(data.Close.iloc[i]) > level if direction == 1 else float(data.Close.iloc[i]) < level):
            choch_i = i
            break
    return {
        "direction": direction if choch_i is not None else 0,
        "sweep": "BULL SWEEP" if direction == 1 else "BEAR SWEEP",
        "mss": "BULL MSS" if choch_i is not None and direction == 1 else
               "BEAR MSS" if choch_i is not None else "NO",
        "sweep_index": sweep_i, "choch_index": choch_i,
        "close": round(float(data.Close.iloc[-1]), 2),
        "time": data.index[-1].strftime("%d-%b-%Y %H:%M"),
    }


def _entry_from_same_zones(frame: pd.DataFrame, structure: dict[str, Any]) -> dict[str, Any]:
    """Reuse scanner.py's exact zone formation, invalidation, retest and confirmation."""
    data = _closed_bars(frame)
    direction, choch_i = structure["direction"], structure["choch_index"]
    result = {"zone": "—", "retest_price": None, "entry": None,
              "entry_time": None, "status": "WAIT RETEST"}
    if direction not in (-1, 1) or choch_i is None or choch_i >= len(data) - 1:
        return result
    zones = _collect_entry_zones(data, 0, int(choch_i), len(data)-1, direction, CONFIG)
    active = [z for z in zones if _zone_is_active(data, z, direction)]
    candidate = _find_entry_in_zones(data, active, direction, CONFIG.entry_valid_days)
    if candidate is None:
        if active:
            result.update({"zone": "+".join(dict.fromkeys(z["type"] for z in active)),
                           "status": "WAIT RETEST"})
        else:
            result["status"] = "WAIT ZONE"
        return result
    z = candidate["zone"]
    entry_i, retest_i = int(candidate["entry_index"]), int(candidate["retest_index"])
    result.update({
        "zone": "+".join(candidate["zone_types"]),
        "retest_price": round((float(z["low"]) + float(z["high"])) / 2, 2),
        "entry": round(float(data.Close.iloc[entry_i]), 2),
        "entry_time": data.index[entry_i].strftime("%d-%b-%Y %H:%M"),
        "status": "ORDER",
    })
    return result


def analyze_mtf_symbol(symbol: str) -> tuple[pd.DataFrame, dict[str, str]]:
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
        pair = f"{htf} → {ltf}"
        try:
            higher = get_data(spec["htf_period"], spec["htf_interval"], spec.get("htf_resample"))
            lower = get_data(spec["ltf_period"], spec["ltf_interval"], spec.get("ltf_resample"))
            hs, ls = _sweep_and_mss(higher), _sweep_and_mss(lower)
            entry = _entry_from_same_zones(lower, ls)
            if hs["direction"] == 0:
                alignment, signal = "WAIT HTF", "WAIT"
            elif ls["direction"] == 0:
                alignment, signal = "WAIT LTF MSS", "WAIT"
            elif hs["direction"] != ls["direction"]:
                alignment, signal = "LTF OPPOSITE — NO TRADE", "WAIT"
            elif entry["status"] != "ORDER":
                alignment, signal = "WAIT LTF RETEST", "WAIT"
            else:
                alignment = "HTF + LTF CONFIRMED"
                signal = "BULL ORDER" if hs["direction"] == 1 else "BEAR ORDER"

            rows.append({
                "HTF → LTF": pair,
                "HTF Liquidity": hs["sweep"], "HTF MSS": hs["mss"],
                "LTF Liquidity": ls["sweep"], "LTF MSS": ls["mss"],
                "Entry Zone": entry["zone"], "Retest Price": entry["retest_price"],
                "Entry Price": entry["entry"], "Entry Time": entry["entry_time"],
                "Alignment": alignment, "Entry Status": entry["status"], "Signal": signal,
                "HTF Close": hs["close"], "LTF Close": ls["close"],
                "HTF Candle": hs["time"], "LTF Candle": ls["time"],
            })
            if hs["close"] is None or ls["close"] is None:
                errors[pair] = "Insufficient timeframe history"
        except Exception as exc:
            errors[pair] = f"{type(exc).__name__}: {str(exc)[:180]}"
            rows.append({
                "HTF → LTF": pair, "HTF Liquidity": "ERROR", "HTF MSS": "—",
                "LTF Liquidity": "ERROR", "LTF MSS": "—", "Entry Zone": "—",
                "Retest Price": None, "Entry Price": None, "Entry Time": None,
                "Alignment": "DATA ERROR", "Entry Status": "WAIT", "Signal": "WAIT",
                "HTF Close": None, "LTF Close": None, "HTF Candle": None, "LTF Candle": None,
            })
    return pd.DataFrame(rows), errors
