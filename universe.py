"""NSE stock universe and supported Indian index tickers."""
from __future__ import annotations

import io
from pathlib import Path
from datetime import datetime

import requests
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent / "data"
CACHE_FILE = DATA_DIR / "EQUITY_L.csv"
NSE_HOME = "https://www.nseindia.com/"
NSE_EQUITY_CSV = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"

INDICES: dict[str, str] = {
    "NIFTY 50": "^NSEI",
    "NIFTY BANK": "^NSEBANK",
    "NIFTY FINANCIAL SERVICES (CNXFINANCE)": "^CNXFINANCE",
    "NIFTY FINANCIAL SERVICES 25/50": "^CNXFIN",
    "NIFTY 100": "^CNX100",
    "NIFTY IT": "^CNXIT",
    "NIFTY AUTO": "^CNXAUTO",
    "NIFTY FMCG": "^CNXFMCG",
    "NIFTY PHARMA": "^CNXPHARMA",
    "NIFTY METAL": "^CNXMETAL",
    "NIFTY REALTY": "^CNXREALTY",
    "NIFTY ENERGY": "^CNXENERGY",
    "NIFTY MEDIA": "^CNXMEDIA",
    "NIFTY PSU BANK": "^CNXPSUBANK",
    "NIFTY INFRA": "^CNXINFRA",
    "NIFTY CONSUMPTION": "^CNXCONSUM",
    "NIFTY COMMODITIES": "^CNXCMDT",
    "NIFTY PSE": "^CNXPSE",
    "S&P BSE SENSEX": "^BSESN",
    "INDIA VIX": "^INDIAVIX",
}


def _read_equity_csv(content: bytes) -> pd.DataFrame:
    frame = pd.read_csv(io.BytesIO(content))
    frame.columns = [str(c).strip().upper() for c in frame.columns]
    if "SYMBOL" not in frame.columns or "SERIES" not in frame.columns:
        raise ValueError("NSE equity file did not contain SYMBOL and SERIES columns")
    frame["SYMBOL"] = frame["SYMBOL"].astype(str).str.strip()
    frame["SERIES"] = frame["SERIES"].astype(str).str.strip().str.upper()
    frame = frame[(frame["SERIES"] == "EQ") & frame["SYMBOL"].ne("")]
    if "NAME OF COMPANY" not in frame.columns:
        frame["NAME OF COMPANY"] = frame["SYMBOL"]
    frame = frame.drop_duplicates(subset=["SYMBOL"], keep="last")
    return frame[["SYMBOL", "NAME OF COMPANY", "SERIES"]].sort_values("SYMBOL").reset_index(drop=True)


def get_nse_equity_universe(force_refresh: bool = False) -> pd.DataFrame:
    """Fetch the official NSE EQ-series list; fall back to any saved copy if needed."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cached_frame = None
    if CACHE_FILE.exists():
        try:
            cached_frame = _read_equity_csv(CACHE_FILE.read_bytes())
            is_fresh = datetime.now().timestamp() - CACHE_FILE.stat().st_mtime < 24 * 60 * 60
            if not force_refresh and is_fresh and not cached_frame.empty:
                return cached_frame
        except Exception:
            cached_frame = None

    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": NSE_HOME,
    }
    try:
        session.get(NSE_HOME, headers=headers, timeout=20)
        response = session.get(NSE_EQUITY_CSV, headers=headers, timeout=30)
        response.raise_for_status()
        content = response.content
        frame = _read_equity_csv(content)
        if frame.empty:
            raise RuntimeError("NSE equity universe returned no EQ-series symbols")
        CACHE_FILE.write_bytes(content)
        return frame
    except Exception as exc:
        if cached_frame is not None and not cached_frame.empty:
            return cached_frame
        raise RuntimeError(
            "Could not download the NSE equity list and no cached copy is available. "
            "Please retry later or run from a network that can access nsearchives.nseindia.com."
        ) from exc


def make_universe(mode: str, custom_symbols: str = "") -> pd.DataFrame:
    """Build the selected scanner universe with columns Symbol, Name, Type."""
    rows: list[dict[str, str]] = []
    if mode in {"All NSE EQ stocks", "All NSE EQ stocks + indices"}:
        stocks = get_nse_equity_universe()
        for _, row in stocks.iterrows():
            symbol = str(row["SYMBOL"]).strip()
            rows.append({"Symbol": f"{symbol}.NS", "Name": str(row["NAME OF COMPANY"]), "Type": "Stock"})
    elif mode == "NIFTY 500 constituents (proxy: all NSE EQ)":
        stocks = get_nse_equity_universe()
        for _, row in stocks.iterrows():
            symbol = str(row["SYMBOL"]).strip()
            rows.append({"Symbol": f"{symbol}.NS", "Name": str(row["NAME OF COMPANY"]), "Type": "Stock"})

    if mode in {"Major Indian indices", "All NSE EQ stocks + indices"}:
        rows.extend({"Symbol": ticker, "Name": name, "Type": "Index"} for name, ticker in INDICES.items())

    if mode == "Custom symbols" and custom_symbols.strip():
        index_aliases = {
            "NIFTY": "^NSEI", "NIFTY 50": "^NSEI", "NIFTY50": "^NSEI",
            "NIFTY BANK": "^NSEBANK", "BANKNIFTY": "^NSEBANK",
            "NIFTY FINANCIAL SERVICES": "^CNXFINANCE", "CNXFINANCE": "^CNXFINANCE",
            "NIFTY FINANCIAL SERVICES 25/50": "^CNXFIN", "NIFTY 100": "^CNX100",
            "NIFTY IT": "^CNXIT", "CNXIT": "^CNXIT", "NIFTY AUTO": "^CNXAUTO", "CNXAUTO": "^CNXAUTO",
            "NIFTY FMCG": "^CNXFMCG", "CNXFMCG": "^CNXFMCG", "NIFTY PHARMA": "^CNXPHARMA", "CNXPHARMA": "^CNXPHARMA",
            "NIFTY METAL": "^CNXMETAL", "CNXMETAL": "^CNXMETAL", "NIFTY REALTY": "^CNXREALTY",
            "NIFTY ENERGY": "^CNXENERGY", "NIFTY MEDIA": "^CNXMEDIA", "NIFTY PSU BANK": "^CNXPSUBANK",
            "NIFTY INFRA": "^CNXINFRA", "NIFTY CONSUMPTION": "^CNXCONSUM", "NIFTY COMMODITIES": "^CNXCMDT",
            "NIFTY PSE": "^CNXPSE", "SENSEX": "^BSESN", "BSE SENSEX": "^BSESN", "INDIA VIX": "^INDIAVIX",
        }
        for raw in custom_symbols.replace("\n", ",").split(","):
            ticker = raw.strip().upper()
            if not ticker:
                continue
            if ticker.startswith("NSE:"):
                ticker = ticker.split(":", 1)[1]
            if ticker in index_aliases:
                ticker = index_aliases[ticker]
            elif ticker.isalpha() and not ticker.startswith("^") and not ticker.endswith((".NS", ".BO")):
                ticker += ".NS"
            rows.append({"Symbol": ticker, "Name": ticker, "Type": "Custom"})

    result = pd.DataFrame(rows, columns=["Symbol", "Name", "Type"])
    if result.empty:
        return result
    return result.drop_duplicates(subset="Symbol").reset_index(drop=True)
