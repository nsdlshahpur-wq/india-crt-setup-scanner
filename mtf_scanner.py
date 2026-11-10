"""Selected-symbol multi-timeframe CRT scanner.

Mapping requested by the user:
Monthly -> Daily, Weekly -> 4H, Daily -> 30m, 4H -> 5m, 1H -> 1m.

Signals use completed candles only. CRT is a prior-candle range sweep and close-back-inside.
Entry confirmation is a structure break plus a same-direction 3-candle FVG.
This is a transparent baseline model, not a claim to reproduce an undocumented HCS rule.
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import yfinance as yf


TIMEFRAME_PAIRS: dict[str, str] = {
    "Monthly": "Daily",
    "Weekly": "4H",
    "Daily": "30m",
    "4H": "5m",
    "1H": "1m",
}

SOURCE_INTERVALS = {
    "Monthly": ("1mo", "10y"),
    "Weekly": ("1wk", "10y"),
    "Daily": ("1d", "5y"),
    "1H": ("60m", "730d"),
    "30m": ("30m", "60d"),
    "5m": ("5m", "60d"),
    "1m": ("1m", "7d"),
}
DURATIONS = {
    "Monthly": pd.DateOffset(months=1),
    "Weekly": pd.Timedelta(days=7),
    "Daily": pd.Timedelta(days=1),
    "4H": pd.Timedelta(hours=4),
    "1H": pd.Timedelta(hours=1),
    "30m": pd.Timedelta(minutes=30),
    "5m": pd.Timedelta(minutes=5),
    "1m": pd.Timedelta(minutes=1),
}


def _normalise(raw: pd.DataFrame) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()
    frame = raw.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        # yfinance can return either (field, ticker) or (ticker, field).
        flat_cols = []
        for col in frame.columns:
            field = next(
                (str(part).title() for part in col
                 if str(part).lower() in {"open", "high", "low", "close", "volume"}),
                str(col[-1]).title(),
            )
            flat_cols.append(field)
        frame.columns = flat_cols
        frame = frame.loc[:, ~pd.Index(frame.columns).duplicated(keep="first")]
    frame.columns = [str(col).strip().title() for col in frame.columns]
    required = ["Open", "High", "Low", "Close"]
    if not all(col in frame.columns for col in required):
        return pd.DataFrame()
    keep = required + (["Volume"] if "Volume" in frame.columns else [])
    frame = frame[keep].copy()
    frame.index = pd.to_datetime(frame.index)
    if getattr(frame.index, "tz", None) is None:
        frame.index = frame.index.tz_localize("Asia/Kolkata")
    else:
        frame.index = frame.index.tz_convert("Asia/Kolkata")
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    for col in keep:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    return frame.dropna(subset=required)


def _download_source(ticker: str, interval: str, period: str) -> pd.DataFrame:
    try:
        raw = yf.download(
            tickers=ticker,
            period=period,
            interval=interval,
            auto_adjust=False,
            actions=False,
            progress=False,
            threads=False,
            timeout=25,
        )
        return _normalise(raw)
    except Exception:
        return pd.DataFrame()


def _completed(frame: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Drop the still-forming final bar when it can be identified safely."""
    if frame.empty:
        return frame
    now = pd.Timestamp.now(tz="Asia/Kolkata")
    last = frame.index[-1]
    if timeframe == "Daily":
        if last.date() == now.date() and now.hour * 60 + now.minute < 15 * 60 + 40:
            return frame.iloc[:-1]
    elif timeframe in {"1H", "30m", "5m", "1m", "4H"}:
        duration = DURATIONS[timeframe]
        if now < last + duration:
            return frame.iloc[:-1]
    elif timeframe == "Weekly":
        # Do not treat the current week's candle as complete before Friday close.
        if last.isocalendar().week == now.isocalendar().week and now.weekday() < 4:
            return frame.iloc[:-1]
        if last.isocalendar().week == now.isocalendar().week and now.weekday() == 4 and now.hour * 60 + now.minute < 15 * 60 + 40:
            return frame.iloc[:-1]
    elif timeframe == "Monthly":
        if last.year == now.year and last.month == now.month and not (
            now.is_month_end and now.hour * 60 + now.minute >= 15 * 60 + 40
        ):
            return frame.iloc[:-1]
    return frame


def _timeframe_data(
    timeframe: str,
    ticker: str,
    source_cache: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    if timeframe == "4H":
        source_tf = "1H"
    else:
        source_tf = timeframe
    if source_tf not in source_cache:
        interval, period = SOURCE_INTERVALS[source_tf]
        source_cache[source_tf] = _download_source(ticker, interval, period)
    frame = source_cache[source_tf].copy()
    if timeframe == "4H" and not frame.empty:
        frame = (
            frame.resample(
                "4h",
                origin="start_day",
                offset="9h15min",
                label="left",
                closed="left",
            )
            .agg(
                {
                    "Open": "first",
                    "High": "max",
                    "Low": "min",
                    "Close": "last",
                    **({"Volume": "sum"} if "Volume" in frame.columns else {}),
                }
            )
            .dropna(subset=["Open", "High", "Low", "Close"])
        )
    return _completed(frame, timeframe)


def _find_sweep(crt: pd.DataFrame, timeframe: str) -> dict[str, Any] | None:
    if len(crt) < 3:
        return None
    start = max(1, len(crt) - 12)
    for i in range(len(crt) - 1, start - 1, -1):
        ref = crt.iloc[i - 1]
        bar = crt.iloc[i]
        bull = float(bar["Low"]) < float(ref["Low"]) and float(bar["Close"]) > float(ref["Low"])
        bear = float(bar["High"]) > float(ref["High"]) and float(bar["Close"]) < float(ref["High"])
        if bull and bear:
            return {"ambiguous": True, "index": i}
        if bull or bear:
            direction = 1 if bull else -1
            invalidated = False
            for j in range(i + 1, len(crt)):
                close = float(crt["Close"].iloc[j])
                if (direction == 1 and close < float(bar["Low"])) or (
                    direction == -1 and close > float(bar["High"])
                ):
                    invalidated = True
                    break
            return {
                "ambiguous": False,
                "direction": direction,
                "index": i,
                "reference": ref,
                "sweep": bar,
                "sweep_time": crt.index[i],
                "sweep_end": crt.index[i] + DURATIONS[timeframe],
                "invalidated": invalidated,
            }
    return None


def _entry_confirmation(entry: pd.DataFrame, sweep_end: pd.Timestamp, direction: int) -> dict[str, Any]:
    after = entry.loc[entry.index >= sweep_end].copy()
    if len(after) < 8:
        return {"confirmed": False, "fvg": None, "data": after, "reason": "Entry timeframe has fewer than 8 post-sweep candles"}
    last = after.iloc[-1]
    prior = after.iloc[-7:-1]
    if direction == 1:
        structure = float(last["Close"]) > float(prior["High"].max()) and float(last["Close"]) > float(last["Open"])
        fvg = None
        for i in range(len(after) - 1, max(1, len(after) - 11), -1):
            if i >= 2 and float(after["Low"].iloc[i]) > float(after["High"].iloc[i - 2]):
                fvg = (float(after["High"].iloc[i - 2]), float(after["Low"].iloc[i]))
                break
    else:
        structure = float(last["Close"]) < float(prior["Low"].min()) and float(last["Close"]) < float(last["Open"])
        fvg = None
        for i in range(len(after) - 1, max(1, len(after) - 11), -1):
            if i >= 2 and float(after["High"].iloc[i]) < float(after["Low"].iloc[i - 2]):
                fvg = (float(after["High"].iloc[i]), float(after["Low"].iloc[i - 2]))
                break
    return {
        "confirmed": bool(structure and fvg is not None),
        "structure": bool(structure),
        "fvg": fvg,
        "data": after,
        "last_time": after.index[-1],
        "last_close": float(last["Close"]),
    }


def analyze_multi_timeframe(ticker: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Analyze all five requested CRT/entry pairs for one selected ticker."""
    source_cache: dict[str, pd.DataFrame] = {}
    frame_cache: dict[str, pd.DataFrame] = {}
    errors: dict[str, str] = {}

    for timeframe in ["Monthly", "Weekly", "Daily", "4H", "1H", "30m", "5m", "1m"]:
        frame_cache[timeframe] = _timeframe_data(timeframe, ticker, source_cache)
        if frame_cache[timeframe].empty:
            errors[timeframe] = "Yahoo Finance data unavailable or outside its intraday history limit"

    rows: list[dict[str, Any]] = []
    for crt_tf, entry_tf in TIMEFRAME_PAIRS.items():
        crt = frame_cache[crt_tf]
        entry = frame_cache[entry_tf]
        base: dict[str, Any] = {
            "CRT TF": crt_tf,
            "Entry TF": entry_tf,
            "CRT Status": "NO DATA" if crt.empty else "NO SWEEP",
            "HTF Bias": "Neutral",
            "Liquidity Sweep": "Not found",
            "Structure / CHoCH": "Pending",
            "Retest Price": None,
            "CRT Range High": None,
            "CRT Range Low": None,
            "Zone Low": None,
            "Zone High": None,
            "Entry": None,
            "SL": None,
            "Target": None,
            "CRT Candle": None,
            "Entry Candle": None,
            "Data Note": errors.get(crt_tf, errors.get(entry_tf, "")),
        }
        if crt.empty or entry.empty:
            rows.append(base)
            continue

        sweep = _find_sweep(crt, crt_tf)
        if sweep is None:
            rows.append(base)
            continue
        if sweep.get("ambiguous"):
            base["CRT Status"] = "AMBIGUOUS"
            base["Liquidity Sweep"] = "Both sides swept"
            rows.append(base)
            continue

        direction = int(sweep["direction"])
        ref = sweep["reference"]
        bar = sweep["sweep"]
        bullish = direction == 1
        base.update(
            {
                "CRT Status": "INVALID" if sweep["invalidated"] else "VALID - WAIT ENTRY",
                "HTF Bias": "Bullish" if bullish else "Bearish",
                "Liquidity Sweep": "Sell-side swept" if bullish else "Buy-side swept",
                "Retest Price": float(ref["Low"] if bullish else ref["High"]),
                "CRT Range High": float(ref["High"]),
                "CRT Range Low": float(ref["Low"]),
                "SL": float(bar["Low"] if bullish else bar["High"]),
                "Target": float(ref["High"] if bullish else ref["Low"]),
                "CRT Candle": sweep["sweep_time"].strftime("%Y-%m-%d %H:%M"),
            }
        )
        if sweep["invalidated"]:
            rows.append(base)
            continue

        confirm = _entry_confirmation(entry, sweep["sweep_end"], direction)
        if confirm.get("last_time") is not None:
            base["Entry Candle"] = confirm["last_time"].strftime("%Y-%m-%d %H:%M")
        base["Structure / CHoCH"] = "Confirmed" if confirm.get("structure") else "Pending"
        if confirm.get("fvg") is not None:
            base["Zone Low"], base["Zone High"] = confirm["fvg"]
        if confirm.get("confirmed"):
            base["CRT Status"] = "ENTRY READY"
            base["Entry"] = confirm["last_close"]
        elif confirm.get("reason"):
            base["Data Note"] = confirm["reason"]
        rows.append(base)

    return rows, errors
