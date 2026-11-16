"""NIFTY intraday CRT + CISD strategy.

CRT is detected only on Weekly/Daily/4H/1H. 15m confirms CISD;
5m supplies the FVG retest/entry trigger. Closed candles only.
"""
from __future__ import annotations

from typing import Any
import pandas as pd
import yfinance as yf
from data_fetch import yahoo_ticker

CRT_SPECS = [
    {"CRT": "1H", "period": "60d", "interval": "60m", "duration": "1h"},
    {"CRT": "4H", "period": "60d", "interval": "60m", "resample": "4h", "duration": "4h"},
    {"CRT": "Daily", "period": "2y", "interval": "1d", "duration": "1d"},
    {"CRT": "Weekly", "period": "5y", "interval": "1wk", "duration": "7d"},
]
ENTRY_SPECS = {
    "15M": {"period": "60d", "interval": "15m"},
    "5M": {"period": "60d", "interval": "5m"},
}
MIN_RR = 2.0
TARGET_R_MULTIPLE = 3.0
TICK_SIZE = 0.05


def clean_ohlc(frame: pd.DataFrame) -> pd.DataFrame:
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


def closed_bars(frame: pd.DataFrame) -> pd.DataFrame:
    data = clean_ohlc(frame)
    # Conservatively exclude the latest possibly-forming candle.
    return data.iloc[:-1] if len(data) > 1 else pd.DataFrame()


def resample_ohlc(frame: pd.DataFrame, rule: str) -> pd.DataFrame:
    data = clean_ohlc(frame)
    if data.empty:
        return data
    return data.resample(rule, label="right", closed="right").agg({
        "Open": "first", "High": "max", "Low": "min", "Close": "last"
    }).dropna()


def download(ticker: str, period: str, interval: str) -> pd.DataFrame:
    return clean_ohlc(yf.download(
        ticker, period=period, interval=interval, auto_adjust=False,
        progress=False, threads=False, timeout=25,
    ))


def _atr(frame: pd.DataFrame, length: int = 14) -> float:
    data = clean_ohlc(frame)
    if len(data) < 2:
        return TICK_SIZE
    prev_close = data.Close.shift(1)
    tr = pd.concat([
        data.High - data.Low,
        (data.High - prev_close).abs(),
        (data.Low - prev_close).abs(),
    ], axis=1).max(axis=1)
    value = tr.rolling(length, min_periods=2).mean().iloc[-1]
    return max(float(value) if pd.notna(value) else TICK_SIZE, TICK_SIZE)


def _find_15m_cisd(frame: pd.DataFrame, direction: int) -> dict[str, Any]:
    """CISD: body close through the open of the preceding opposing delivery run."""
    data = closed_bars(frame)
    if len(data) < 4:
        return {"confirmed": False, "time": None, "line": None, "status": "WAIT 15M CISD"}
    for i in range(1, len(data)):
        row = data.iloc[i]
        if direction == 1:
            # Bullish reversal: preceding contiguous bearish candle run.
            if float(row.Close) <= float(row.Open):
                continue
            j = i - 1
            if float(data.Close.iloc[j]) >= float(data.Open.iloc[j]):
                continue
            while j > 0 and float(data.Close.iloc[j - 1]) < float(data.Open.iloc[j - 1]):
                j -= 1
            line = float(data.Open.iloc[j])
            if float(row.Close) > line:
                return {"confirmed": True, "time": data.index[i], "line": line,
                        "status": "BULLISH CISD"}
        else:
            if float(row.Close) >= float(row.Open):
                continue
            j = i - 1
            if float(data.Close.iloc[j]) <= float(data.Open.iloc[j]):
                continue
            while j > 0 and float(data.Close.iloc[j - 1]) > float(data.Open.iloc[j - 1]):
                j -= 1
            line = float(data.Open.iloc[j])
            if float(row.Close) < line:
                return {"confirmed": True, "time": data.index[i], "line": line,
                        "status": "BEARISH CISD"}
    return {"confirmed": False, "time": None, "line": None, "status": "WAIT 15M CISD"}


def _find_5m_fvg_retest(frame: pd.DataFrame, direction: int, cisd_time) -> dict[str, Any]:
    """Find a post-CISD three-candle FVG and a later confirmed retest candle."""
    data = closed_bars(frame)
    if data.empty or cisd_time is None:
        return {"confirmed": False, "status": "WAIT 5M ENTRY", "entry": None,
                "entry_time": None, "fvg_low": None, "fvg_high": None}
    data = data[data.index > pd.Timestamp(cisd_time)]
    if len(data) < 4:
        return {"confirmed": False, "status": "WAIT 5M FVG", "entry": None,
                "entry_time": None, "fvg_low": None, "fvg_high": None}

    zones = []
    for i in range(2, len(data)):
        a, c = data.iloc[i - 2], data.iloc[i]
        if direction == 1 and float(c.Low) > float(a.High):
            zones.append((i, float(a.High), float(c.Low)))
        elif direction == -1 and float(c.High) < float(a.Low):
            zones.append((i, float(c.High), float(a.Low)))

    for formed_i, zone_low, zone_high in reversed(zones):
        for i in range(formed_i + 1, len(data)):
            row = data.iloc[i]
            touched = float(row.Low) <= zone_high and float(row.High) >= zone_low
            if not touched:
                continue
            confirmed = (
                float(row.Close) > float(row.Open) and float(row.Close) > zone_low
                if direction == 1 else
                float(row.Close) < float(row.Open) and float(row.Close) < zone_high
            )
            if confirmed and i == len(data) - 1:
                return {
                    "confirmed": True, "status": "5M FVG RETEST CONFIRMED",
                    "entry": round(float(row.Close), 2),
                    "entry_time": data.index[i].strftime("%Y-%m-%d %H:%M"),
                    "fvg_low": round(zone_low, 2), "fvg_high": round(zone_high, 2),
                }
    return {"confirmed": False, "status": "WAIT 5M FVG RETEST", "entry": None,
            "entry_time": None, "fvg_low": None, "fvg_high": None}


def analyze_crt_cisd_pair(crt_frame: pd.DataFrame, m15: pd.DataFrame,
                          m5: pd.DataFrame, duration: str,
                          crt_name: str) -> dict[str, Any]:
    htf_all = clean_ohlc(crt_frame)
    htf = closed_bars(htf_all)
    empty = {
        "CRT Timeframe": crt_name, "CRT M1 High": None, "CRT M1 Low": None,
        "CRT M2 High": None, "CRT M2 Low": None, "CRT M2 Close": None,
        "CRT Sweep": "WAIT", "15M CISD": "WAIT", "CISD Reference": None,
        "5M Entry Status": "WAIT", "FVG Low": None, "FVG High": None,
        "Entry Price": None, "Entry Time": None, "Stop Loss": None,
        "Target 1 (2R)": None, "Target 2 (3R)": None, "Risk Points": None,
        "RR": None, "Signal": "WAIT", "Alignment": "WAIT — CRT HISTORY",
        "Entry Status": "WAIT", "CRT Close": None, "15M Close": None,
        "5M Close": None, "CISD Time": None,
    }
    if len(htf) < 2 or len(htf_all) < 3:
        return empty

    m1, m2 = htf.iloc[-2], htf.iloc[-1]
    m1_high, m1_low = float(m1.High), float(m1.Low)
    m2_high, m2_low, m2_close = float(m2.High), float(m2.Low), float(m2.Close)
    swept_low = m2_low < m1_low
    swept_high = m2_high > m1_high
    reclaimed = m1_low < m2_close < m1_high
    marked = {
        "CRT M1 High": round(m1_high, 2), "CRT M1 Low": round(m1_low, 2),
        "CRT M2 High": round(m2_high, 2), "CRT M2 Low": round(m2_low, 2),
        "CRT M2 Close": round(m2_close, 2), "CRT Close": round(m2_close, 2),
        "15M Close": round(float(closed_bars(m15).Close.iloc[-1]), 2) if not closed_bars(m15).empty else None,
        "5M Close": round(float(closed_bars(m5).Close.iloc[-1]), 2) if not closed_bars(m5).empty else None,
    }
    if swept_low and swept_high:
        return {**empty, **marked, "CRT Sweep": "DOUBLE SWEEP — REJECTED",
                "Alignment": "WAIT — AMBIGUOUS DOUBLE SWEEP", "Entry Status": "REJECTED"}
    if not (swept_low or swept_high) or not reclaimed:
        label = "SWEEP WITHOUT RECLAIM" if (swept_low or swept_high) else "NO SWEEP"
        return {**empty, **marked, "CRT Sweep": label,
                "Alignment": "WAIT — M2 MUST SWEEP ONE SIDE AND CLOSE INSIDE M1"}

    direction = 1 if swept_low else -1
    side = "BULLISH" if direction == 1 else "BEARISH"
    # Start lower-timeframe confirmation only after the M2 CRT candle is complete.
    m2_end = htf.index[-1] + pd.Timedelta(duration)
    m15_after = clean_ohlc(m15)
    m15_after = m15_after[m15_after.index >= m2_end]
    cisd = _find_15m_cisd(m15_after, direction)
    base = {**empty, **marked, "CRT Sweep": f"{side} LIQUIDITY SWEEP",
            "CISD Reference": round(cisd["line"], 2) if cisd["line"] is not None else None,
            "15M CISD": cisd["status"], "CISD Time": str(cisd["time"]) if cisd["time"] is not None else None}
    if not cisd["confirmed"]:
        base.update({"Alignment": "WAIT — 15M CISD NOT CONFIRMED",
                     "Entry Status": "WAIT 15M CISD"})
        return base

    m5_after = clean_ohlc(m5)
    m5_after = m5_after[m5_after.index > pd.Timestamp(cisd["time"])]
    entry_setup = _find_5m_fvg_retest(m5_after, direction, cisd["time"])
    base.update({
        "5M Entry Status": entry_setup["status"],
        "FVG Low": entry_setup["fvg_low"], "FVG High": entry_setup["fvg_high"],
        "Alignment": "WAIT — 5M ENTRY CONFIRMATION",
        "Entry Status": entry_setup["status"],
    })
    if not entry_setup["confirmed"]:
        return base

    entry = float(entry_setup["entry"])
    atr = _atr(m5_after)
    buffer = max(TICK_SIZE, atr * 0.10)
    sweep_extreme = m2_low if direction == 1 else m2_high
    stop = sweep_extreme - buffer if direction == 1 else sweep_extreme + buffer
    risk = entry - stop if direction == 1 else stop - entry
    if risk <= 0:
        return {**base, "Alignment": "REJECTED — INVALID STOP", "Entry Status": "REJECTED"}
    t1 = entry + direction * 2.0 * risk
    t2 = entry + direction * TARGET_R_MULTIPLE * risk
    base.update({
        "Entry Price": round(entry, 2), "Entry Time": entry_setup["entry_time"],
        "Stop Loss": round(stop, 2), "Target 1 (2R)": round(t1, 2),
        "Target 2 (3R)": round(t2, 2), "Risk Points": round(risk, 2),
        "RR": "1:2 / 1:3", "Signal": "BUY" if direction == 1 else "SELL",
        "Alignment": "CRT SWEEP + 15M CISD + 5M FVG RETEST CONFIRMED",
        "Entry Status": "ORDER",
    })
    return base


def analyze_mtf_symbol(symbol: str) -> tuple[pd.DataFrame, dict[str, str]]:
    ticker = yahoo_ticker(symbol)
    cache: dict[tuple[str, str], pd.DataFrame] = {}
    errors: dict[str, str] = {}

    def get_data(period: str, interval: str, resample: str | None = None) -> pd.DataFrame:
        key = (period, interval)
        if key not in cache:
            cache[key] = download(ticker, period, interval)
        frame = cache[key]
        return resample_ohlc(frame, resample) if resample else frame

    m15 = get_data(**ENTRY_SPECS["15M"])
    m5 = get_data(**ENTRY_SPECS["5M"])
    rows = []
    for spec in CRT_SPECS:
        name = spec["CRT"]
        try:
            higher = get_data(spec["period"], spec["interval"], spec.get("resample"))
            row = analyze_crt_cisd_pair(higher, m15, m5, spec["duration"], name)
            # Compatibility fields retained for the scheduled scanner export.
            row["HTF → LTF"] = f"{name} → 15M CISD → 5M Entry"
            row["Entry Zone"] = "FVG" if row["FVG Low"] is not None else "—"
            row["Retest Zone"] = row["Entry Zone"]
            row["Retest Price"] = (
                round((row["FVG Low"] + row["FVG High"]) / 2, 2)
                if row["FVG Low"] is not None and row["FVG High"] is not None else None
            )
            row["Entry-TF CHoCH"] = "REPLACED BY 15M CISD"
            row["LTF Liquidity"] = row["CRT Sweep"]
            row["LTF MSS"] = row["15M CISD"]
            rows.append(row)
        except Exception as exc:
            errors[name] = f"{type(exc).__name__}: {str(exc)[:180]}"
            rows.append({"CRT Timeframe": name, "HTF → LTF": f"{name} → 15M CISD → 5M Entry",
                         "CRT Sweep": "DATA ERROR", "15M CISD": "—",
                         "5M Entry Status": "—", "Signal": "WAIT",
                         "Alignment": "DATA ERROR", "Entry Status": "WAIT"})
    return pd.DataFrame(rows), errors
