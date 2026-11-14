"""CRT HTF->LTF scanner using the SAME FVG/IFVG/OB/BOB retest rules as scanner.py."""
from __future__ import annotations

from typing import Any

import pandas as pd
import yfinance as yf

from data_fetch import yahoo_ticker
from scanner import (
    ScanConfig, _collect_entry_zones, _find_entry_in_zones,
    _confirmed_pivots, _zone_is_active, _find_m3_choch,
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


def _analyze_pair_with_monthly_crt_rules(
    higher: pd.DataFrame,
    lower: pd.DataFrame,
) -> dict[str, Any]:
    """Separate CRT-timeframe candle marking from lower-timeframe entry planning.

    M1 and M2 are the two most recent COMPLETED candles on the CRT timeframe.
    M1 defines the CRT range. M2 itself must sweep exactly one M1 boundary and
    close back inside the full M1 range. Entry analysis begins only after M2
    has completed, using the configured lower timeframe.
    """
    htf_all = _clean_ohlc(higher)
    htf = _closed_bars(htf_all)
    ltf_all = _clean_ohlc(lower)
    ltf = _closed_bars(ltf_all)

    empty = {
        "m1_high": None, "m1_low": None, "m1_time": None,
        "m2_high": None, "m2_low": None, "m2_close": None, "m2_time": None,
        "htf_sweep": "—", "sweep_direction": "—",
        "ltf_choch": "NO", "zone": "—", "retest_zone": "—",
        "retest_price": None, "entry": None, "entry_time": None,
        "stop_loss": None, "target": None, "rr": None,
        "signal": "WAIT", "alignment": "WAIT — INSUFFICIENT CRT HISTORY",
        "entry_status": "WAIT", "htf_close": None, "ltf_close": None,
        "choch_time": None,
    }
    if len(htf) < 2 or len(htf_all) < 3:
        return empty

    # M1/M2 are explicitly selected on the CRT timeframe, not inferred from LTF bars.
    m1, m2 = htf.iloc[-2], htf.iloc[-1]
    m1_high, m1_low = float(m1.High), float(m1.Low)
    m2_high, m2_low, m2_close = float(m2.High), float(m2.Low), float(m2.Close)
    # Last row in the original HTF data is the currently forming next candle.
    next_htf_start = htf_all.index[-1]

    swept_low = m2_low < m1_low
    swept_high = m2_high > m1_high
    reclaimed = m1_low < m2_close < m1_high
    marked = {
        "m1_high": m1_high, "m1_low": m1_low,
        "m1_time": htf.index[-2].strftime("%Y-%m-%d %H:%M"),
        "m2_high": m2_high, "m2_low": m2_low, "m2_close": m2_close,
        "m2_time": htf.index[-1].strftime("%Y-%m-%d %H:%M"),
        "htf_close": round(m2_close, 2),
        "ltf_close": round(float(ltf.Close.iloc[-1]), 2) if not ltf.empty else None,
    }

    if swept_low and swept_high:
        return {
            **empty, **marked,
            "htf_sweep": "DOUBLE SWEEP — REJECTED",
            "sweep_direction": "AMBIGUOUS",
            "alignment": "WAIT — M2 SWEPT BOTH M1 SIDES",
            "entry_status": "REJECTED",
        }
    if not reclaimed:
        return {
            **empty, **marked,
            "htf_sweep": "SWEEP WITHOUT FULL-RANGE RECLAIM" if (swept_low or swept_high) else "NO SWEEP",
            "sweep_direction": "BULLISH" if swept_low else ("BEARISH" if swept_high else "—"),
            "alignment": "WAIT — M2 MUST CLOSE INSIDE M1 HIGH/LOW",
        }
    if not swept_low and not swept_high:
        return {
            **empty, **marked,
            "htf_sweep": "NO SWEEP",
            "alignment": "WAIT — M2 DID NOT SWEEP M1 RANGE",
        }

    direction = 1 if swept_low else -1
    sweep_label = "BULL SWEEP" if direction == 1 else "BEAR SWEEP"
    direction_label = "BULLISH" if direction == 1 else "BEARISH"

    # Entry timeframe starts after the M2 CRT candle has closed.
    entry_data = ltf[ltf.index >= next_htf_start]
    if len(entry_data) < max(12, CONFIG.pivot_left + CONFIG.pivot_right + 5):
        return {
            **empty, **marked,
            "htf_sweep": sweep_label, "sweep_direction": direction_label,
            "alignment": "WAIT — NOT ENOUGH POST-SWEEP ENTRY-TF HISTORY",
            "entry_status": "WAIT CHoCH",
        }

    # The HTF M2 candle is the sweep candle; its extreme defines the stop.
    sweep_stop = m2_low if direction == 1 else m2_high
    opposite_target = m1_high if direction == 1 else m1_low
    entry_data = entry_data.reset_index(drop=False).rename(columns={"index": "_time"})
    entry_data = entry_data.set_index("_time")
    last_index = len(entry_data) - 1

    # The LTF structure is evaluated independently after the HTF M2 close.
    choch = _find_m3_choch(entry_data, 0, 0, last_index, direction, CONFIG)
    base = {
        **empty, **marked,
        "htf_sweep": sweep_label,
        "sweep_direction": direction_label,
        "stop_loss": round(sweep_stop, 2),
        "target": round(opposite_target, 2),
        "htf_close": round(m2_close, 2),
        "ltf_close": round(float(entry_data.Close.iloc[-1]), 2),
    }
    if choch["index"] is None:
        base.update({
            "alignment": "WAIT — ENTRY-TF CHoCH NOT CONFIRMED",
            "entry_status": "WAIT CHoCH",
        })
        return base

    choch_index = int(choch["index"])
    choch_label = "BULL CHoCH" if direction == 1 else "BEAR CHoCH"
    zones = _collect_entry_zones(
        entry_data, 0, choch_index, last_index, direction, CONFIG
    )
    active_zones = [z for z in zones if _zone_is_active(entry_data, z, direction)]
    zone_names = list(dict.fromkeys(z["type"] for z in active_zones))
    base.update({
        "ltf_choch": choch_label,
        "zone": "+".join(zone_names) if zone_names else "—",
        "alignment": "WAIT — ENTRY-TF ZONE RETEST",
        "entry_status": "WAIT RETEST" if active_zones else "WAIT ZONE",
        "choch_time": entry_data.index[choch_index].strftime("%Y-%m-%d %H:%M"),
    })
    if not active_zones:
        return base

    candidate = _find_entry_in_zones(
        entry_data, active_zones, direction, CONFIG.entry_valid_days
    )
    if candidate is None:
        return base

    entry_index = int(candidate["entry_index"])
    zone = candidate["zone"]
    entry_price = float(entry_data.Close.iloc[entry_index])
    risk = abs(entry_price - sweep_stop)
    reward = abs(opposite_target - entry_price)
    rr = reward / risk if risk > 0 else 0.0
    base.update({
        "zone": "+".join(candidate["zone_types"]),
        "retest_zone": "+".join(candidate["zone_types"]),
        "retest_price": round((float(zone["low"]) + float(zone["high"])) / 2, 2),
        "rr": round(rr, 2),
        "entry_time": entry_data.index[entry_index].strftime("%Y-%m-%d %H:%M"),
    })
    if risk <= 0 or reward <= 0 or rr < 1.5:
        base.update({
            "alignment": "WAIT — MINIMUM RR 1.5 NOT MET",
            "entry_status": "RETEST FOUND — RR FILTER FAILED",
        })
        return base
    if entry_index != last_index:
        base.update({
            "alignment": "WAIT — ENTRY WAS ON AN EARLIER ENTRY-TF CANDLE",
            "entry_status": "MISSED — NO FRESH ENTRY",
        })
        return base

    base.update({
        "entry": round(entry_price, 2),
        "signal": "BULL ORDER" if direction == 1 else "BEAR ORDER",
        "alignment": "CRT M1/M2 + ENTRY-TF CHoCH + ZONE RETEST CONFIRMED",
        "entry_status": "ORDER",
    })
    return base

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
            crt = _analyze_pair_with_monthly_crt_rules(higher, lower)
            rows.append({
                "HTF → LTF": pair,
                "CRT M1 High": crt["m1_high"], "CRT M1 Low": crt["m1_low"],
                "CRT M1 Candle": crt["m1_time"],
                "CRT M2 High": crt["m2_high"], "CRT M2 Low": crt["m2_low"],
                "CRT M2 Close": crt["m2_close"], "CRT M2 Candle": crt["m2_time"],
                "CRT Sweep": crt["htf_sweep"], "Sweep Direction": crt["sweep_direction"],
                "Entry-TF CHoCH": crt["ltf_choch"], "Entry Zone": crt["zone"],
                "Retest Zone": crt["retest_zone"], "Retest Price": crt["retest_price"],
                "Entry Price": crt["entry"], "Entry Time": crt["entry_time"],
                "Stop Loss": crt["stop_loss"], "Target": crt["target"], "RR": crt["rr"],
                "Alignment": crt["alignment"], "Entry Status": crt["entry_status"],
                "Signal": crt["signal"], "CRT Close": crt["htf_close"],
                "Entry-TF Close": crt["ltf_close"], "CHoCH Time": crt["choch_time"],
            })
            if crt["htf_close"] is None or crt["ltf_close"] is None:
                errors[pair] = "Insufficient timeframe history"
        except Exception as exc:
            errors[pair] = f"{type(exc).__name__}: {str(exc)[:180]}"
            rows.append({
                "HTF → LTF": pair, "HTF Liquidity": "ERROR", "HTF MSS": "—",
                "LTF Liquidity": "ERROR", "LTF MSS": "—", "Entry Zone": "—",
                "Retest Zone": "—", "Retest Price": None, "Entry Price": None, "Entry Time": None,
                "Alignment": "DATA ERROR", "Entry Status": "WAIT", "Signal": "WAIT",
                "HTF Close": None, "LTF Close": None, "HTF Candle": None, "LTF Candle": None,
            })
    return pd.DataFrame(rows), errors
