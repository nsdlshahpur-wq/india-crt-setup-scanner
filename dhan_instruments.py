"""Dhan instrument-master download and safe NSE cash-equity symbol resolution.
Only the official Dhan compact security master is used for IDs. Never guesses IDs.
"""
from __future__ import annotations
from io import StringIO
from typing import Any
import pandas as pd
import requests

DHAN_INSTRUMENT_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
_REQUIRED = {"SEM_EXM_EXCH_ID", "SEM_SEGMENT", "SEM_SMST_SECURITY_ID", "SEM_INSTRUMENT_NAME", "SEM_TRADING_SYMBOL"}

class DhanInstrumentError(RuntimeError):
    """Safe instrument-master or symbol-resolution error."""

def parse_dhan_instrument_master(csv_content: str | bytes) -> pd.DataFrame:
    """Parse official compact CSV and return NSE EQ cash instruments only."""
    try:
        if isinstance(csv_content, bytes):
            csv_content = csv_content.decode("utf-8-sig")
        frame = pd.read_csv(StringIO(csv_content), dtype=str, keep_default_na=False)
    except Exception:
        raise DhanInstrumentError("Dhan instrument master CSV could not be parsed.") from None
    frame.columns = [str(col).strip().upper() for col in frame.columns]
    missing = sorted(_REQUIRED.difference(frame.columns))
    if missing:
        raise DhanInstrumentError("Dhan instrument master is missing required columns: " + ", ".join(missing))
    for col in _REQUIRED:
        frame[col] = frame[col].astype(str).str.strip()
    selected = frame[
        frame["SEM_EXM_EXCH_ID"].str.upper().eq("NSE")
        & frame["SEM_SEGMENT"].str.upper().eq("E")
        & frame["SEM_INSTRUMENT_NAME"].str.upper().eq("EQUITY")
    ].copy()
    if "SEM_SERIES" in frame.columns:
        selected = selected[selected["SEM_SERIES"].str.upper().isin(["EQ", ""])]
    selected["SYMBOL"] = selected["SEM_TRADING_SYMBOL"].str.upper().str.strip()
    selected["SECURITY_ID"] = selected["SEM_SMST_SECURITY_ID"].str.strip()
    selected = selected[selected["SYMBOL"].ne("") & selected["SECURITY_ID"].str.fullmatch(r"\d+").fillna(False)]
    selected = selected.drop_duplicates(subset=["SYMBOL"], keep=False)
    if selected.empty:
        raise DhanInstrumentError("Dhan master contains no unambiguous NSE EQ cash instruments.")
    selected["EXCHANGE_SEGMENT"] = "NSE_EQ"
    selected["INSTRUMENT"] = "EQUITY"
    columns = ["SYMBOL", "SECURITY_ID", "EXCHANGE_SEGMENT", "INSTRUMENT"]
    if "SEM_CUSTOM_SYMBOL" in selected.columns:
        selected["DISPLAY_NAME"] = selected["SEM_CUSTOM_SYMBOL"].astype(str).str.strip()
        columns.append("DISPLAY_NAME")
    return selected[columns].sort_values("SYMBOL").reset_index(drop=True)

def download_dhan_instrument_master(*, timeout: int = 30, session: Any = requests) -> pd.DataFrame:
    """Download and parse the current official Dhan compact instrument master."""
    try:
        response = session.get(
            DHAN_INSTRUMENT_MASTER_URL,
            headers={"Accept": "text/csv", "User-Agent": "India-CRT-Scanner/1.0"},
            timeout=timeout,
        )
        response.raise_for_status()
        content = response.content or response.text
    except requests.Timeout:
        raise DhanInstrumentError("Dhan instrument-master download timed out.") from None
    except requests.RequestException:
        raise DhanInstrumentError("Could not download Dhan's official instrument master.") from None
    return parse_dhan_instrument_master(content)

def resolve_dhan_nse_equity(symbol: str, instrument_master: pd.DataFrame) -> dict[str, str]:
    """Resolve NSE ticker such as RELIANCE or RELIANCE.NS to its verified ID."""
    raw = str(symbol or "").strip().upper()
    if not raw:
        raise ValueError("A stock symbol is required.")
    if raw.startswith("^") or raw.endswith(".BO"):
        raise DhanInstrumentError("Dhan NSE_EQ resolver supports NSE cash equities only.")
    if raw.startswith("NSE:"):
        raw = raw[4:]
    if raw.endswith(".NS"):
        raw = raw[:-3]
    if not raw or "." in raw:
        raise DhanInstrumentError("Only plain NSE equity symbols are supported.")
    required = {"SYMBOL", "SECURITY_ID", "EXCHANGE_SEGMENT", "INSTRUMENT"}
    if not required.issubset(instrument_master.columns):
        raise DhanInstrumentError("Instrument master is not in the expected normalized format.")
    matches = instrument_master[
        instrument_master["SYMBOL"].astype(str).str.upper().eq(raw)
        & instrument_master["EXCHANGE_SEGMENT"].eq("NSE_EQ")
        & instrument_master["INSTRUMENT"].eq("EQUITY")
    ]
    if len(matches) == 0:
        raise DhanInstrumentError(f"No verified Dhan NSE EQ security ID found for {raw}.")
    if len(matches) != 1:
        raise DhanInstrumentError(f"Multiple Dhan NSE EQ matches found for {raw}; refusing to guess.")
    row = matches.iloc[0]
    return {"symbol": raw, "security_id": str(row["SECURITY_ID"]), "exchange_segment": "NSE_EQ", "instrument": "EQUITY"}
