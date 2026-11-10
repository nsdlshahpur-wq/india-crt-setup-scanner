"""CRT Setup Scanner: monthly CRT bias + daily sweep + displacement entry.

The calculations are performed on completed daily candles. This mirrors the
intent of the supplied Pine Script while avoiding Pine's lower-timeframe
security() offset mechanics in a Python daily-data workflow.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time as dtime
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ScanConfig:
    atr_length: int = 14
    displacement_atr: float = 1.2
    pivot_left: int = 3
    pivot_right: int = 3
    sweep_lookback: int = 10
    entry_valid_days: int = 3


def _normalise_ohlc(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a clean Open/High/Low/Close/Volume dataframe."""
    if frame is None or frame.empty:
        return pd.DataFrame()
    data = frame.copy()
    if isinstance(data.columns, pd.MultiIndex):
        # yfinance may return either (Price, Ticker) or (Ticker, Price).
        price_names = {"open", "high", "low", "close", "volume"}
        flattened = []
        for col in data.columns:
            parts = [str(part) for part in col]
            price = next((part for part in parts if part.lower() in price_names), parts[0])
            flattened.append(price.title())
        data.columns = flattened
    data.columns = [str(c).strip().title() for c in data.columns]
    required = ["Open", "High", "Low", "Close"]
    if not all(col in data.columns for col in required):
        return pd.DataFrame()
    cols = required + (["Volume"] if "Volume" in data.columns else [])
    data = data[cols].copy()
    data.index = pd.to_datetime(data.index)
    if getattr(data.index, "tz", None) is not None:
        data.index = data.index.tz_localize(None)
    data = data[~data.index.duplicated(keep="last")].sort_index()
    for col in cols:
        data[col] = pd.to_numeric(data[col], errors="coerce")
    data = data.dropna(subset=required)
    return data


def _wilder_atr(data: pd.DataFrame, length: int) -> pd.Series:
    prev_close = data["Close"].shift(1)
    true_range = pd.concat(
        [
            data["High"] - data["Low"],
            (data["High"] - prev_close).abs(),
            (data["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()


def _confirmed_pivots(series: pd.Series, left: int, right: int, is_high: bool) -> pd.Series:
    """Pivot value appears on its confirmation candle, as in ta.pivothigh/low."""
    values = series.to_numpy(dtype=float)
    result = np.full(len(values), np.nan, dtype=float)
    width = left + right + 1
    if len(values) < width:
        return pd.Series(result, index=series.index)
    for confirm_idx in range(width - 1, len(values)):
        pivot_idx = confirm_idx - right
        window = values[confirm_idx - width + 1 : confirm_idx + 1]
        candidate = values[pivot_idx]
        if not np.isfinite(candidate) or not np.isfinite(window).all():
            continue
        extreme = np.max(window) if is_high else np.min(window)
        if candidate == extreme and np.count_nonzero(window == extreme) == 1:
            result[confirm_idx] = candidate
    return pd.Series(result, index=series.index)


def _monthly_context(data: pd.DataFrame) -> dict[str, Any] | None:
    """Get the two most recently completed months (M1 and M2).

    M1 is the month before last; M2 is the most recently completed month.
    The current, incomplete month is deliberately excluded.
    """
    if data.empty:
        return None
    month_keys = data.index.to_period("M")
    current_month = month_keys[-1]
    completed = data.loc[month_keys < current_month]
    if completed.empty:
        return None
    monthly = completed.groupby(completed.index.to_period("M")).agg(
        High=("High", "max"),
        Low=("Low", "min"),
        Close=("Close", "last"),
    )
    if len(monthly) < 2:
        return None
    m1 = monthly.iloc[-2]
    m2 = monthly.iloc[-1]
    m2_period = monthly.index[-1]
    m2_rows = data.loc[data.index.to_period("M") == m2_period]
    if m2_rows.empty:
        return None
    return {
        "m1_high": float(m1["High"]),
        "m1_low": float(m1["Low"]),
        "m2_high": float(m2["High"]),
        "m2_low": float(m2["Low"]),
        "m2_close": float(m2["Close"]),
        "m2_start": m2_rows.index[0],
        "m1_period": str(monthly.index[-2]),
        "m2_period": str(m2_period),
    }


def scan_symbol(symbol: str, name: str, raw_data: pd.DataFrame, config: ScanConfig) -> dict[str, Any] | None:
    """Scan one stock/index and return a row for the dashboard."""
    data = _normalise_ohlc(raw_data)
    now_ist = pd.Timestamp.now(tz=ZoneInfo("Asia/Kolkata"))
    if not data.empty and data.index[-1].date() == now_ist.date() and now_ist.time() < dtime(15, 40):
        data = data.iloc[:-1].copy()
    minimum = max(config.atr_length + 5, config.sweep_lookback + config.entry_valid_days + 8, config.pivot_left + config.pivot_right + 8)
    if len(data) < minimum:
        return None

    monthly = _monthly_context(data)
    if monthly is None:
        return None

    atr = _wilder_atr(data, config.atr_length)
    prior_low = data["Low"].rolling(config.sweep_lookback, min_periods=config.sweep_lookback).min().shift(1)
    prior_high = data["High"].rolling(config.sweep_lookback, min_periods=config.sweep_lookback).max().shift(1)
    recent_high_5 = data["High"].rolling(5, min_periods=5).max().shift(1)
    recent_low_5 = data["Low"].rolling(5, min_periods=5).min().shift(1)
    last_pivot_high = _confirmed_pivots(data["High"], config.pivot_left, config.pivot_right, True).ffill()
    last_pivot_low = _confirmed_pivots(data["Low"], config.pivot_left, config.pivot_right, False).ffill()

    last_idx = len(data) - 1
    latest = data.iloc[last_idx]
    ltp = float(latest["Close"])

    bull = monthly["m2_low"] < monthly["m1_low"] and monthly["m2_close"] > monthly["m1_low"]
    bear = monthly["m2_high"] > monthly["m1_high"] and monthly["m2_close"] < monthly["m1_high"]
    bias = 1 if bull else (-1 if bear else 0)

    stage = 0
    entry = stop = target1 = target2 = invalidation = np.nan
    sweep_date = entry_date = None
    sweep_found = False

    if bias == 1 and ltp > monthly["m1_low"]:
        stage = 1
        invalidation = monthly["m1_low"]
        target2 = monthly["m2_high"]
    elif bias == -1 and ltp < monthly["m1_high"]:
        stage = 1
        invalidation = monthly["m1_high"]
        target2 = monthly["m2_low"]

    if bias == 1 and ltp > monthly["m1_low"]:
        for c in range(config.entry_valid_days):
            entry_idx = last_idx - c
            if entry_idx < 0:
                continue
            for s in range(c + 1, c + config.sweep_lookback + 1):
                sweep_idx = last_idx - s
                if sweep_idx < 1 or entry_idx <= sweep_idx:
                    continue
                if data.index[sweep_idx] < monthly["m2_start"]:
                    continue
                threshold = prior_low.iloc[sweep_idx]
                if not np.isfinite(threshold):
                    continue
                swept = data["Low"].iloc[sweep_idx] < threshold and data["Close"].iloc[sweep_idx] > threshold
                if not swept:
                    continue
                level = last_pivot_high.iloc[sweep_idx]
                if not np.isfinite(level):
                    level = recent_high_5.iloc[sweep_idx]
                body = data["Close"].iloc[entry_idx] - data["Open"].iloc[entry_idx]
                atr_value = atr.iloc[entry_idx]
                if np.isfinite(level) and np.isfinite(atr_value) and data["Close"].iloc[entry_idx] > level and body >= config.displacement_atr * atr_value:
                    entry = float(data["Close"].iloc[entry_idx])
                    stop = float(data["Low"].iloc[sweep_idx])
                    target1 = entry + 2 * (entry - stop)
                    sweep_date = data.index[sweep_idx].date().isoformat()
                    entry_date = data.index[entry_idx].date().isoformat()
                    stage = 3
                    sweep_found = True
                    break
            if sweep_found:
                break

    elif bias == -1 and ltp < monthly["m1_high"]:
        for c in range(config.entry_valid_days):
            entry_idx = last_idx - c
            if entry_idx < 0:
                continue
            for s in range(c + 1, c + config.sweep_lookback + 1):
                sweep_idx = last_idx - s
                if sweep_idx < 1 or entry_idx <= sweep_idx:
                    continue
                if data.index[sweep_idx] < monthly["m2_start"]:
                    continue
                threshold = prior_high.iloc[sweep_idx]
                if not np.isfinite(threshold):
                    continue
                swept = data["High"].iloc[sweep_idx] > threshold and data["Close"].iloc[sweep_idx] < threshold
                if not swept:
                    continue
                level = last_pivot_low.iloc[sweep_idx]
                if not np.isfinite(level):
                    level = recent_low_5.iloc[sweep_idx]
                body = data["Open"].iloc[entry_idx] - data["Close"].iloc[entry_idx]
                atr_value = atr.iloc[entry_idx]
                if np.isfinite(level) and np.isfinite(atr_value) and data["Close"].iloc[entry_idx] < level and body >= config.displacement_atr * atr_value:
                    entry = float(data["Close"].iloc[entry_idx])
                    stop = float(data["High"].iloc[sweep_idx])
                    target1 = entry - 2 * (stop - entry)
                    sweep_date = data.index[sweep_idx].date().isoformat()
                    entry_date = data.index[entry_idx].date().isoformat()
                    stage = 3
                    sweep_found = True
                    break
            if sweep_found:
                break

    if stage == 1:
        for s in range(0, config.sweep_lookback):
            sweep_idx = last_idx - s
            if sweep_idx < 1 or data.index[sweep_idx] < monthly["m2_start"]:
                continue
            if bias == 1:
                threshold = prior_low.iloc[sweep_idx]
                if np.isfinite(threshold) and data["Low"].iloc[sweep_idx] < threshold and data["Close"].iloc[sweep_idx] > threshold:
                    stage = 2
                    stop = float(data["Low"].iloc[sweep_idx])
                    sweep_date = data.index[sweep_idx].date().isoformat()
                    break
            else:
                threshold = prior_high.iloc[sweep_idx]
                if np.isfinite(threshold) and data["High"].iloc[sweep_idx] > threshold and data["Close"].iloc[sweep_idx] < threshold:
                    stage = 2
                    stop = float(data["High"].iloc[sweep_idx])
                    sweep_date = data.index[sweep_idx].date().isoformat()
                    break

    return {
        "Symbol": symbol,
        "Name": name,
        "Bias": "Bullish" if bias == 1 else ("Bearish" if bias == -1 else "Neutral"),
        "Stage": stage,
        "Setup": "BUY" if stage == 3 and bias == 1 else ("SELL" if stage == 3 and bias == -1 else ("Wait Sweep" if stage == 1 else ("Wait Entry" if stage == 2 else "-"))),
        "LTP": ltp,
        "Entry": entry,
        "SL": stop,
        "T1 (2R)": target1,
        "T2 (M2 H/L)": target2,
        "Invalidation": invalidation,
        "M1 High": monthly["m1_high"],
        "M1 Low": monthly["m1_low"],
        "M2 High": monthly["m2_high"],
        "M2 Low": monthly["m2_low"],
        "M2 Close": monthly["m2_close"],
        "M1 Month": monthly["m1_period"],
        "M2 Month": monthly["m2_period"],
        "Sweep Date": sweep_date,
        "Entry Date": entry_date,
        "Last Candle": data.index[-1].date().isoformat(),
    }
