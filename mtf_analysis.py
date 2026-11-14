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


def _analyze_pair_with_monthly_crt_rules(
    higher: pd.DataFrame,
    lower: pd.DataFrame,
) -> dict[str, Any]:
    """Generalise the proven M1-range -> M2 sweep/reclaim -> M3 LTF CHoCH -> zone retest model.

    For each pair, M1/M2/M3 are three consecutive HTF candles. The sweep is
    detected on the LTF bars inside M2; CHoCH and FVG/IFVG/OB/BOB retest are
    detected on LTF bars inside the current M3 candle. All confirmations use
    completed LTF candles only.
    """
    # Keep the latest forming HTF candle as M3; only LTF execution bars must be closed.
    htf = _clean_ohlc(higher)
    ltf = _closed_bars(lower)
    empty = {
        "htf_sweep": "—", "ltf_sweep": "—", "htf_choch": "NO",
        "ltf_choch": "NO", "zone": "—", "retest_zone": "—",
        "retest_price": None, "entry": None, "entry_time": None,
        "signal": "WAIT", "alignment": "WAIT — INSUFFICIENT CRT HISTORY",
        "entry_status": "WAIT", "htf_close": None, "ltf_close": None,
        "sweep_time": None, "choch_time": None,
    }
    if len(htf) < 3 or len(ltf) < 30:
        return empty

    # Use the last three HTF candles: M1 range, M2 sweep/reclaim, M3 active entry period.
    m1, m2, m3 = htf.iloc[-3], htf.iloc[-2], htf.iloc[-1]
    m2_start, m3_start = htf.index[-2], htf.index[-1]
    m2_rows = ltf[(ltf.index >= m2_start) & (ltf.index < m3_start)]
    m3_rows = ltf[ltf.index >= m3_start]
    if m2_rows.empty or len(m3_rows) < 8:
        out = dict(empty)
        out.update({
            "alignment": "WAIT — LTF HISTORY NOT COVERING M2/M3",
            "htf_close": round(float(m3.Close), 2),
            "ltf_close": round(float(ltf.Close.iloc[-1]), 2),
        })
        return out

    m1_high, m1_low = float(m1.High), float(m1.Low)
    bull_sweeps = m2_rows[
        (m2_rows.Low < m1_low)
        & (m2_rows.Close > m1_low)
        & (m2_rows.Close < m1_high)
    ]
    bear_sweeps = m2_rows[
        (m2_rows.High > m1_high)
        & (m2_rows.Close < m1_high)
        & (m2_rows.Close > m1_low)
    ]
    if not bull_sweeps.empty and not bear_sweeps.empty:
        out = dict(empty)
        out.update({
            "htf_sweep": "DOUBLE SWEEP — REJECTED",
            "alignment": "WAIT — AMBIGUOUS M2 SWEEP",
            "htf_close": round(float(m3.Close), 2),
            "ltf_close": round(float(ltf.Close.iloc[-1]), 2),
        })
        return out
    if not bull_sweeps.empty:
        direction, sweep_row, sweep_label = 1, bull_sweeps.iloc[-1], "BULL SWEEP"
    elif not bear_sweeps.empty:
        direction, sweep_row, sweep_label = -1, bear_sweeps.iloc[-1], "BEAR SWEEP"
    else:
        out = dict(empty)
        out.update({
            "htf_sweep": "NO SWEEP",
            "alignment": "WAIT — M2 DID NOT SWEEP M1 RANGE",
            "htf_close": round(float(m3.Close), 2),
            "ltf_close": round(float(ltf.Close.iloc[-1]), 2),
        })
        return out

    sweep_time = sweep_row.name
    sweep_matches = ltf.index.get_indexer([sweep_time])
    sweep_index = int(sweep_matches[0]) if len(sweep_matches) and sweep_matches[0] >= 0 else -1
    m3_positions = ltf.index.get_indexer_for(m3_rows.index)
    m3_start_index = int(m3_positions[0]) if len(m3_positions) else len(ltf)
    last_index = len(ltf) - 1
    choch = _find_m3_choch(ltf, m3_start_index, sweep_index, last_index, direction, CONFIG)
    if choch["index"] is None:
        return {
            **empty,
            "htf_sweep": sweep_label,
            "ltf_sweep": "—",
            "htf_choch": "NO",
            "ltf_choch": "NO",
            "alignment": "WAIT — LTF CHoCH NOT CONFIRMED",
            "htf_close": round(float(m3.Close), 2),
            "ltf_close": round(float(ltf.Close.iloc[-1]), 2),
            "sweep_time": sweep_time.strftime("%Y-%m-%d %H:%M"),
        }

    choch_index = int(choch["index"])
    choch_label = "BULL CHoCH" if direction == 1 else "BEAR CHoCH"
    zones = _collect_entry_zones(
        ltf, m3_start_index, choch_index, last_index, direction, CONFIG
    )
    active_zones = [z for z in zones if _zone_is_active(ltf, z, direction)]
    candidate = _find_entry_in_zones(ltf, active_zones, direction, CONFIG.entry_valid_days)
    zone_names = list(dict.fromkeys(z["type"] for z in active_zones))
    base = {
        "htf_sweep": sweep_label,
        "ltf_sweep": sweep_label,
        "htf_choch": "NO",
        "ltf_choch": choch_label,
        "zone": "+".join(zone_names) if zone_names else "—",
        "retest_zone": "—",
        "retest_price": None,
        "entry": None,
        "entry_time": None,
        "signal": "WAIT",
        "alignment": "WAIT — ZONE RETEST / CONFIRMATION",
        "entry_status": "WAIT RETEST" if active_zones else "WAIT ZONE",
        "htf_close": round(float(m3.Close), 2),
        "ltf_close": round(float(ltf.Close.iloc[-1]), 2),
        "sweep_time": sweep_time.strftime("%Y-%m-%d %H:%M"),
        "choch_time": ltf.index[choch_index].strftime("%Y-%m-%d %H:%M"),
    }
    if candidate is None:
        return base

    entry_index = int(candidate["entry_index"])
    zone = candidate["zone"]
    entry_price = float(ltf.Close.iloc[entry_index])
    stop = float(sweep_row.Low) if direction == 1 else float(sweep_row.High)
    target = m1_high if direction == 1 else m1_low
    risk = abs(entry_price - stop)
    reward = abs(target - entry_price)
    if risk <= 0 or reward <= 0 or reward / risk < 1.5:
        base["alignment"] = "WAIT — MINIMUM RR 1.5 NOT MET"
        base["entry_status"] = "RETEST FOUND — RR FILTER FAILED"
        return base

    # Avoid stale entries: only the latest completed LTF candle may confirm.
    if entry_index != last_index:
        base["alignment"] = "WAIT — ENTRY WAS ON AN EARLIER LTF CANDLE"
        base["entry_status"] = "MISSED — NO FRESH ENTRY"
        return base

    base.update({
        "zone": "+".join(candidate["zone_types"]),
        "retest_zone": "+".join(candidate["zone_types"]),
        "retest_price": round((float(zone["low"]) + float(zone["high"])) / 2, 2),
        "entry": round(entry_price, 2),
        "entry_time": ltf.index[entry_index].strftime("%Y-%m-%d %H:%M"),
        "signal": "BULL ORDER" if direction == 1 else "BEAR ORDER",
        "alignment": "CRT + LTF CHoCH + ZONE RETEST CONFIRMED",
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
                "HTF Liquidity": crt["htf_sweep"], "HTF MSS": crt["htf_choch"],
                "LTF Liquidity": crt["ltf_sweep"], "LTF MSS": crt["ltf_choch"],
                "Entry Zone": crt["zone"], "Retest Zone": crt["retest_zone"],
                "Retest Price": crt["retest_price"],
                "Entry Price": crt["entry"], "Entry Time": crt["entry_time"],
                "Alignment": crt["alignment"], "Entry Status": crt["entry_status"],
                "Signal": crt["signal"], "HTF Close": crt["htf_close"],
                "LTF Close": crt["ltf_close"], "HTF Candle": crt["sweep_time"],
                "LTF Candle": crt["choch_time"],
            })
            if hs["close"] is None or ls["close"] is None:
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
