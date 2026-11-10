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

from data_fetch import yahoo_ticker


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
        session_close = last.normalize() + pd.Timedelta(hours=15, minutes=30)
        bar_end = min(last + duration, session_close)
        if now < bar_end:
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
    """Return only a recent, still-valid sweep of the immediately preceding CRT candle."""
    if len(crt) < 3:
        return None

    # Scan recent completed bars; do not revive a sweep that is too old for the
    # selected CRT period. A pair is explicitly the current bar vs prior bar.
    start = max(1, len(crt) - 3)
    for i in range(len(crt) - 1, start - 1, -1):
        ref = crt.iloc[i - 1]
        bar = crt.iloc[i]
        bull = float(bar["Low"]) < float(ref["Low"]) and float(bar["Close"]) > float(ref["Low"])
        bear = float(bar["High"]) > float(ref["High"]) and float(bar["Close"]) < float(ref["High"])
        if bull and bear:
            return {"ambiguous": True, "index": i}
        if not (bull or bear):
            continue

        direction = 1 if bull else -1
        # Invalidation is a completed CRT candle closing beyond the sweep extreme.
        invalidated = any(
            (direction == 1 and float(crt["Close"].iloc[j]) < float(bar["Low"]))
            or (direction == -1 and float(crt["Close"].iloc[j]) > float(bar["High"]))
            for j in range(i + 1, len(crt))
        )
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
    """Check for a post-sweep structure break and FVG, with a fresh signal window."""
    after = entry.loc[entry.index >= sweep_end].copy()
    if len(after) < 8:
        return {
            "confirmed": False,
            "fvg": None,
            "data": after,
            "reason": "Entry timeframe has fewer than 8 post-sweep candles",
        }

    # Evaluate completed bars in a bounded recent window. The structure break and
    # FVG must occur after the CRT sweep, not merely coexist somewhere in history.
    scan_start = max(6, len(after) - 12)
    found = None
    for i in range(scan_start, len(after)):
        bar = after.iloc[i]
        prior = after.iloc[i - 6:i]
        if direction == 1:
            structure = float(bar["Close"]) > float(prior["High"].max()) and float(bar["Close"]) > float(bar["Open"])
            fvg = (
                (float(after["High"].iloc[i - 2]), float(after["Low"].iloc[i]))
                if i >= 2 and float(after["Low"].iloc[i]) > float(after["High"].iloc[i - 2])
                else None
            )
        else:
            structure = float(bar["Close"]) < float(prior["Low"].min()) and float(bar["Close"]) < float(bar["Open"])
            fvg = (
                (float(after["High"].iloc[i]), float(after["Low"].iloc[i - 2]))
                if i >= 2 and float(after["High"].iloc[i]) < float(after["Low"].iloc[i - 2])
                else None
            )
        if structure and fvg is not None:
            found = {"index": i, "fvg": fvg}
            break

    if found is None:
        last = after.iloc[-1]
        return {
            "confirmed": False,
            "structure": False,
            "fvg": None,
            "data": after,
            "last_time": after.index[-1],
            "last_close": float(last["Close"]),
        }

    bar = after.iloc[found["index"]]
    return {
        "confirmed": True,
        "structure": True,
        "fvg": found["fvg"],
        "data": after,
        "last_time": after.index[found["index"]],
        "last_close": float(bar["Close"]),
    }


def _build_pair_result(
    ticker: str,
    crt_tf: str,
    entry_tf: str,
    crt: pd.DataFrame,
    entry: pd.DataFrame,
    errors: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build one CRT/entry pair result from its own timeframe candle sets."""
    errors = errors or {}
    base: dict[str, Any] = {
        "Symbol": ticker,
        "CRT TF": crt_tf,
        "Entry TF": entry_tf,
        "CRT Status": "NO DATA" if crt.empty or entry.empty else "NO SWEEP",
        "CRT Mark": "",
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
        return base

    sweep = _find_sweep(crt, crt_tf)
    if sweep is None:
        return base
    if sweep.get("ambiguous"):
        base["CRT Status"] = "AMBIGUOUS"
        base["Liquidity Sweep"] = "Both sides swept"
        return base

    direction = int(sweep["direction"])
    reference = sweep["reference"]
    sweep_bar = sweep["sweep"]
    bullish = direction == 1
    base.update({
        "CRT Status": "INVALID" if sweep["invalidated"] else "VALID - WAIT ENTRY",
        "CRT Mark": "" if sweep["invalidated"] else "✓ VALID CRT",
        "HTF Bias": "Bullish" if bullish else "Bearish",
        "Liquidity Sweep": "Sell-side swept" if bullish else "Buy-side swept",
        "Retest Price": None if sweep["invalidated"] else float(reference["Low"] if bullish else reference["High"]),
        "CRT Range High": None if sweep["invalidated"] else float(reference["High"]),
        "CRT Range Low": None if sweep["invalidated"] else float(reference["Low"]),
        "SL": None if sweep["invalidated"] else float(sweep_bar["Low"] if bullish else sweep_bar["High"]),
        "Target": None if sweep["invalidated"] else float(reference["High"] if bullish else reference["Low"]),
        "CRT Candle": sweep["sweep_time"].strftime("%Y-%m-%d %H:%M") if not sweep["invalidated"] else None,
    })
    if sweep["invalidated"]:
        return base

    confirm = _entry_confirmation(entry, sweep["sweep_end"], direction)
    if confirm.get("last_time") is not None:
        base["Entry Candle"] = confirm["last_time"].strftime("%Y-%m-%d %H:%M")
    base["Structure / CHoCH"] = "Confirmed" if confirm.get("structure") else "Pending"
    if confirm.get("fvg") is not None:
        base["Zone Low"], base["Zone High"] = confirm["fvg"]
    if confirm.get("confirmed"):
        base["CRT Status"] = "ENTRY READY"
        base["CRT Mark"] = "✓ VALID CRT"
        base["Entry"] = confirm["last_close"]
    elif confirm.get("reason"):
        base["Data Note"] = confirm["reason"]
    return base


def analyze_timeframe_pair(
    ticker: str,
    crt_timeframe: str,
    entry_timeframe: str | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Analyze one selectable CRT/entry pair using the correct Yahoo intervals."""
    if crt_timeframe not in TIMEFRAME_PAIRS:
        raise ValueError(f"Unsupported CRT timeframe: {crt_timeframe}")
    entry_tf = entry_timeframe or TIMEFRAME_PAIRS[crt_timeframe]
    supported_entry = set(DURATIONS) - {"Monthly", "Weekly"}
    if entry_tf not in supported_entry:
        raise ValueError(f"Unsupported entry timeframe: {entry_tf}")

    yahoo_symbol = yahoo_ticker(ticker)
    source_cache: dict[str, pd.DataFrame] = {}
    crt = _timeframe_data(crt_timeframe, yahoo_symbol, source_cache)
    entry = _timeframe_data(entry_tf, yahoo_symbol, source_cache)
    errors: dict[str, str] = {}
    if crt.empty:
        errors[crt_timeframe] = f"No completed {crt_timeframe} candles returned for Yahoo ticker {yahoo_symbol}"
    if entry.empty:
        errors[entry_tf] = f"No completed {entry_tf} candles returned for Yahoo ticker {yahoo_symbol}"
    result = _build_pair_result(ticker, crt_timeframe, entry_tf, crt, entry, errors)
    return result, errors


def analyze_multi_timeframe(ticker: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Analyze all five requested CRT/entry pairs for one selected ticker."""
    yahoo_symbol = yahoo_ticker(ticker)
    source_cache: dict[str, pd.DataFrame] = {}
    frame_cache: dict[str, pd.DataFrame] = {}
    errors: dict[str, str] = {}

    for timeframe in ["Monthly", "Weekly", "Daily", "4H", "1H", "30m", "5m", "1m"]:
        frame_cache[timeframe] = _timeframe_data(timeframe, yahoo_symbol, source_cache)
        if frame_cache[timeframe].empty:
            errors[timeframe] = f"No completed {timeframe} candles returned for Yahoo ticker {yahoo_symbol}"

    rows: list[dict[str, Any]] = []
    for crt_tf, entry_tf in TIMEFRAME_PAIRS.items():
        rows.append(_build_pair_result(
            ticker,
            crt_tf,
            entry_tf,
            frame_cache[crt_tf],
            frame_cache[entry_tf],
            errors,
        ))
    return rows, errors
