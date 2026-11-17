"""Cached loader for public NIFTY50 one-minute history.

Each source CSV is cached independently so a missing/new month does not force
all historical years to download and parse again.
"""
from __future__ import annotations

from datetime import date
from io import BytesIO
from typing import Iterable

import pandas as pd
import requests
import streamlit as st

BASE_URL = (
    "https://raw.githubusercontent.com/technovusin/"
    "nifty50-historical-data/main/1min"
)
SOURCE_REPO = "https://github.com/technovusin/nifty50-historical-data"
OHLC = ["Open", "High", "Low", "Close"]


def _file_urls(today: date | None = None) -> Iterable[tuple[int, int | None, str]]:
    today = today or date.today()
    for year in range(2017, min(today.year, 2025) + 1):
        yield year, None, f"{BASE_URL}/{year}/NIFTY50_1min_{year}.csv"
    if today.year >= 2026:
        for month in range(1, today.month + 1):
            suffix = f"2026-{month:02d}"
            yield 2026, month, f"{BASE_URL}/2026/NIFTY50_1min_{suffix}.csv"


@st.cache_data(ttl=7 * 24 * 60 * 60, show_spinner=False, max_entries=16)
def _load_one_csv(url: str, label: str) -> tuple[pd.DataFrame | None, str | None, int]:
    """Download/parse one historical CSV once; return a compact OHLC frame."""
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "CRT-Scanner-Historical-Backtest/2.0"},
            timeout=(10, 60),
        )
        if response.status_code == 404:
            return None, "not published", 0
        response.raise_for_status()
        frame = pd.read_csv(
            BytesIO(response.content),
            usecols=["Timestamp", *OHLC],
            dtype={"Open": "float32", "High": "float32",
                   "Low": "float32", "Close": "float32"},
        )
        frame["Timestamp"] = pd.to_datetime(frame["Timestamp"], errors="coerce")
        frame = frame.dropna(subset=["Timestamp", *OHLC])
        frame = frame.set_index("Timestamp")[OHLC]
        frame = frame.between_time("09:15", "15:29")
        frame = frame[
            (frame["High"] >= frame[["Open", "Close", "Low"]].max(axis=1))
            & (frame["Low"] <= frame[["Open", "Close", "High"]].min(axis=1))
        ]
        frame.index.name = "Timestamp"
        return frame, None, len(response.content)
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}", 0


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False, max_entries=2)
def load_full_nifty50_1m(force_refresh: bool = False) -> tuple[pd.DataFrame, dict]:
    """Combine independently cached CSVs; force_refresh clears source-file cache."""
    if force_refresh:
        _load_one_csv.clear()

    frames: list[pd.DataFrame] = []
    report = {
        "source": SOURCE_REPO, "files_loaded": [],
        "files_missing": [], "errors": [],
        "cache_policy": "Each yearly/monthly source file cached for 7 days",
    }
    for year, month, url in _file_urls():
        label = f"{year}-{month:02d}" if month else str(year)
        frame, error, size = _load_one_csv(url, label)
        if error == "not published":
            report["files_missing"].append(label)
        elif error:
            report["errors"].append(f"{label}: {error}")
        elif frame is not None and not frame.empty:
            frames.append(frame)
            report["files_loaded"].append(
                {"period": label, "rows": len(frame), "bytes": size}
            )

    if not frames:
        raise RuntimeError("GitHub se NIFTY50 historical CSV data download nahi hua.")

    # Concatenate and sort only once; use float32 to reduce memory footprint.
    data = pd.concat(frames, copy=False).sort_index()
    data = data[~data.index.duplicated(keep="last")]
    data.index.name = "Timestamp"
    report["total_rows"] = len(data)
    report["start"] = str(data.index.min())
    report["end"] = str(data.index.max())
    report["years"] = sorted(data.index.year.unique().tolist())
    return data, report
