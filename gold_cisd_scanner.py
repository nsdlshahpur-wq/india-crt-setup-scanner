"""Gold (XAUUSD) CISD scanner using the two uploaded videos as source.

The first video defines the mechanical sequence: liquidity sweep/reclaim,
CISD body close, three-candle FVG, FVG retest/rejection, next-bar entry.
The second video is a practical XAUUSD chart example with a bullish CISD
label, FVG zone and long-position risk box. It does not disclose a verified
broker/data feed or a complete written parameter set.

This module intentionally reuses the independently tested CISD rule engine.
It accepts user-supplied XAUUSD OHLC CSV data; it does not fabricate prices.
"""
from __future__ import annotations

from io import BytesIO
from typing import Any

import pandas as pd

from cisd_scanner import CISDConfig, backtest_cisd, find_day_setup


ALIASES = {
    "timestamp": "Timestamp", "time": "Timestamp", "date": "Timestamp",
    "datetime": "Timestamp", "open": "Open", "high": "High",
    "low": "Low", "close": "Close",
}


def load_gold_ohlc_csv(file: Any) -> tuple[pd.DataFrame, dict]:
    """Read TradingView-style OHLC CSV and return a clean datetime-indexed frame."""
    raw = pd.read_csv(file if hasattr(file, "read") else BytesIO(file))
    rename = {}
    for col in raw.columns:
        key = str(col).strip().lower().replace("<", "").replace(">", "")
        if key in ALIASES:
            rename[col] = ALIASES[key]
    raw = raw.rename(columns=rename)
    required = {"Timestamp", "Open", "High", "Low", "Close"}
    missing = sorted(required - set(raw.columns))
    if missing:
        raise ValueError(
            "CSV mein Date/Time/Timestamp aur Open, High, Low, Close columns chahiye. "
            f"Missing: {', '.join(missing)}"
        )
    raw["Timestamp"] = pd.to_datetime(raw["Timestamp"], errors="coerce")
    for col in ("Open", "High", "Low", "Close"):
        raw[col] = pd.to_numeric(raw[col], errors="coerce")
    frame = raw.dropna(subset=["Timestamp", "Open", "High", "Low", "Close"])
    frame = frame.set_index("Timestamp")[["Open", "High", "Low", "Close"]].sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    valid = (
        (frame["High"] >= frame[["Open", "Close", "Low"]].max(axis=1))
        & (frame["Low"] <= frame[["Open", "Close", "High"]].min(axis=1))
    )
    frame = frame.loc[valid]
    if frame.empty:
        raise ValueError("CSV se valid OHLC candles nahi mile.")
    report = {
        "rows": int(len(frame)),
        "start": str(frame.index.min()),
        "end": str(frame.index.max()),
        "source": "User-uploaded XAUUSD OHLC CSV",
    }
    return frame, report


__all__ = ["CISDConfig", "backtest_cisd", "find_day_setup", "load_gold_ohlc_csv"]
