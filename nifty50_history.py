"""Download and cache the complete public NIFTY50 1-minute history.

Source: https://github.com/technovusin/nifty50-historical-data
The raw CSVs are intentionally NOT embedded in Python source or committed to
this app repo. They are downloaded on demand and cached by Streamlit so the
repository stays lightweight and the full history remains reproducible.
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


def _file_urls(today: date | None = None) -> Iterable[tuple[int, int | None, str]]:
    today = today or date.today()
    for year in range(2017, min(today.year, 2025) + 1):
        yield year, None, f"{BASE_URL}/{year}/NIFTY50_1min_{year}.csv"
    if today.year >= 2026:
        for month in range(1, today.month + 1):
            suffix = f"2026-{month:02d}"
            yield 2026, month, f"{BASE_URL}/2026/NIFTY50_1min_{suffix}.csv"


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def load_full_nifty50_1m(force_refresh: bool = False) -> tuple[pd.DataFrame, dict]:
    """Load all available yearly/monthly files, skipping months not published yet."""
    frames: list[pd.DataFrame] = []
    report = {"source": SOURCE_REPO, "files_loaded": [], "files_missing": [], "errors": []}
    headers = {"User-Agent": "CRT-Scanner-Historical-Backtest/1.0"}
    for year, month, url in _file_urls():
        label = f"{year}-{month:02d}" if month else str(year)
        try:
            response = requests.get(url, headers=headers, timeout=(15, 90))
            if response.status_code == 404:
                report["files_missing"].append(label)
                continue
            response.raise_for_status()
            frame = pd.read_csv(BytesIO(response.content))
            required = {"Timestamp", "Open", "High", "Low", "Close"}
            if not required.issubset(frame.columns):
                report["errors"].append(f"{label}: required OHLC columns missing")
                continue
            frame["Timestamp"] = pd.to_datetime(frame["Timestamp"], errors="coerce")
            for col in ("Open", "High", "Low", "Close"):
                frame[col] = pd.to_numeric(frame[col], errors="coerce")
            frame = frame.dropna(subset=["Timestamp", "Open", "High", "Low", "Close"])
            frame = frame.set_index("Timestamp")[["Open", "High", "Low", "Close"]]
            frame = frame[(frame.index.time >= pd.Timestamp("09:15").time()) &
                          (frame.index.time <= pd.Timestamp("15:29").time())]
            frames.append(frame)
            report["files_loaded"].append({"period": label, "rows": len(frame), "bytes": len(response.content)})
        except Exception as exc:
            report["errors"].append(f"{label}: {type(exc).__name__}: {exc}")

    if not frames:
        raise RuntimeError("GitHub se Nifty 50 ka historical CSV data download nahi hua.")

    data = pd.concat(frames).sort_index()
    data = data[~data.index.duplicated(keep="last")]
    data = data[(data["High"] >= data[["Open", "Close", "Low"]].max(axis=1)) &
                (data["Low"] <= data[["Open", "Close", "High"]].min(axis=1))]
    data.index.name = "Timestamp"
    report["total_rows"] = len(data)
    report["start"] = str(data.index.min())
    report["end"] = str(data.index.max())
    report["years"] = sorted(data.index.year.unique().tolist())
    return data, report
