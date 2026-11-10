"""Daily NSE + BSE equity universe and broad Nifty equity-index catalogue.

Exchange masters are the source of listed-symbol names. Yahoo Finance is only
the data adapter; many official index names may not have Yahoo ticker mappings.
"""
from __future__ import annotations

import io
import re
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

DATA_DIR = Path(__file__).resolve().parent / "data"
NSE_CACHE_FILE = DATA_DIR / "EQUITY_L.csv"
NSE_SME_CACHE_FILE = DATA_DIR / "SME_EQUITY_L.csv"
BSE_CACHE_FILE = DATA_DIR / "BSE_EQ_SCRIP.csv"
BSE_SOURCE_FILE = DATA_DIR / "BSE_EQ_SCRIP_SOURCE.txt"
NSE_HOME = "https://www.nseindia.com/"
NSE_EQUITY_CSV = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
NSE_SME_CSV = "https://nsearchives.nseindia.com/emerge/corporates/content/SME_EQUITY_L.csv"
BSE_SCRIP_ZIP = "https://www.bseindia.com/downloads/Help/file/scrip.zip"

# Yahoo ticker mappings are kept separate from the official catalog. A catalog
# entry without a mapping is displayed as unavailable rather than guessed.
YAHOO_INDEX_SYMBOLS: dict[str, str] = {
    "NIFTY 50": "^NSEI",
    "NIFTY NEXT 50": "^NSMIDCP",
    "NIFTY 100": "^CNX100",
    "NIFTY 200": "^CNX200",
    "NIFTY BANK": "^NSEBANK",
    "NIFTY FINANCIAL SERVICES": "^CNXFINANCE",
    "NIFTY FINANCIAL SERVICES 25/50": "^CNXFIN",
    "NIFTY IT": "^CNXIT",
    "NIFTY AUTO": "^CNXAUTO",
    "NIFTY FMCG": "^CNXFMCG",
    "NIFTY PHARMA": "^CNXPHARMA",
    "NIFTY METAL": "^CNXMETAL",
    "NIFTY REALTY": "^CNXREALTY",
    "NIFTY ENERGY": "^CNXENERGY",
    "NIFTY MEDIA": "^CNXMEDIA",
    "NIFTY PSU BANK": "^CNXPSUBANK",
    "NIFTY INFRASTRUCTURE": "^CNXINFRA",
    "NIFTY MNC": "^CNXMNC",
    "NIFTY SMLCAP 100": "^CNXSC",
    "NIFTY SMALLCAP 100": "^CNXSC",
    "NIFTY PSE": "^CNXPSE",
    "NIFTY SERVICES SECTOR": "^CNXSERVICE",
    "NIFTY CONSUMPTION": "^CNXCONSUM",
    "NIFTY COMMODITIES": "^CNXCMDT",
    "INDIA VIX": "^INDIAVIX",
    "S&P BSE SENSEX": "^BSESN",
}
# The official Nifty factsheet publishes equity indices in broad, sectoral,
# thematic and strategy families. Names below are catalog entries; a blank
# Yahoo symbol means the scanner cannot obtain that index from this provider.
NIFTY_EQUITY_INDEX_CATALOG: list[tuple[str, str]] = [
    # Broad market
    ("NIFTY 50", "Broad Market"), ("NIFTY NEXT 50", "Broad Market"),
    ("NIFTY 100", "Broad Market"), ("NIFTY NEXT 100", "Broad Market"),
    ("NIFTY 200", "Broad Market"), ("NIFTY TOTAL MARKET", "Broad Market"),
    ("NIFTY 500", "Broad Market"), ("NIFTY500 MULTICAP 50:25:25", "Broad Market"),
    ("NIFTY500 LARGE MID SMALL EQUAL-CAP WEIGHTED", "Broad Market"),
    ("NIFTY MIDCAP 150", "Broad Market"), ("NIFTY MIDCAP 50", "Broad Market"),
    ("NIFTY MIDCAP SELECT", "Broad Market"), ("NIFTY MIDCAP 100", "Broad Market"),
    ("NIFTY SMALLCAP 500", "Broad Market"), ("NIFTY SMALLCAP 250", "Broad Market"),
    ("NIFTY SMALLCAP 50", "Broad Market"), ("NIFTY SMALLCAP 100", "Broad Market"),
    ("NIFTY MICROCAP 250", "Broad Market"), ("NIFTY LARGEMIDCAP 250", "Broad Market"),
    ("NIFTY MIDSMALLCAP 400", "Broad Market"), ("NIFTY MIDSMALLCAP400 50:50", "Broad Market"),
    ("NIFTY INDIA FPI 150", "Broad Market"), ("INDIA VIX", "Volatility"),
    # Sectoral
    ("NIFTY AUTO", "Sectoral"), ("NIFTY BANK", "Sectoral"),
    ("NIFTY CAPITAL GOODS", "Sectoral"), ("NIFTY CEMENT", "Sectoral"),
    ("NIFTY CHEMICALS", "Sectoral"), ("NIFTY COMMERCIAL & TRANSPORT SERVICES", "Sectoral"),
    ("NIFTY CONSTRUCTION", "Sectoral"), ("NIFTY CONSUMER DURABLES", "Sectoral"),
    ("NIFTY CONSUMER SERVICES", "Sectoral"), ("NIFTY FINANCIAL SERVICES", "Sectoral"),
    ("NIFTY FINANCIAL SERVICES 25/50", "Sectoral"),
    ("NIFTY FINANCIAL SERVICES EX BANK", "Sectoral"), ("NIFTY FMCG", "Sectoral"),
    ("NIFTY HEALTHCARE", "Sectoral"), ("NIFTY HOSPITALS", "Sectoral"),
    ("NIFTY HOUSING FINANCE", "Sectoral"), ("NIFTY INSURANCE", "Sectoral"),
    ("NIFTY IT", "Sectoral"), ("NIFTY MEDIA", "Sectoral"), ("NIFTY METAL", "Sectoral"),
    ("NIFTY NBFC", "Sectoral"), ("NIFTY OIL AND GAS", "Sectoral"),
    ("NIFTY PHARMA", "Sectoral"), ("NIFTY POWER", "Sectoral"),
    ("NIFTY PRIVATE BANK", "Sectoral"), ("NIFTY PSU BANK", "Sectoral"),
    ("NIFTY REALTY", "Sectoral"), ("NIFTY REITS & REALTY", "Sectoral"),
    ("NIFTY RETAIL", "Sectoral"), ("NIFTY TELECOMMUNICATIONS", "Sectoral"),
    ("NIFTY500 HEALTHCARE", "Sectoral"),
    ("NIFTY MIDSMALL FINANCIAL SERVICES", "Sectoral"),
    ("NIFTY MIDSMALL HEALTHCARE", "Sectoral"),
    ("NIFTY MIDSMALL IT & TELECOM", "Sectoral"),
    # Thematic
    ("NIFTY AI CATALYSTS", "Thematic"), ("NIFTY INDIA CORPORATE GROUP - ADITYA BIRLA", "Thematic"),
    ("NIFTY CAPITAL MARKETS", "Thematic"), ("NIFTY COMMODITIES", "Thematic"),
    ("NIFTY CONGLOMERATE 50", "Thematic"), ("NIFTY CORE HOUSING", "Thematic"),
    ("NIFTY CPSE", "Thematic"), ("NIFTY ENERGY", "Thematic"),
    ("NIFTY EV & NEW AGE AUTOMOTIVE", "Thematic"), ("NIFTY HOUSING", "Thematic"),
    ("NIFTY100 ESG", "Thematic"), ("NIFTY100 ENHANCED ESG", "Thematic"),
    ("NIFTY100 ESG SECTOR LEADERS", "Thematic"), ("NIFTY INDIA CONSUMPTION", "Thematic"),
    ("NIFTY INDIA DEFENCE", "Thematic"), ("NIFTY INDIA DEFENCE EQUAL WEIGHT", "Thematic"),
    ("NIFTY INDIA DIGITAL", "Thematic"), ("NIFTY INDIA INFRASTRUCTURE & LOGISTICS", "Thematic"),
    ("NIFTY INDIA INTERNET", "Thematic"), ("NIFTY INDIA MANUFACTURING", "Thematic"),
    ("NIFTY INDIA NEW AGE CONSUMPTION", "Thematic"), ("NIFTY INDIA RAILWAYS PSU", "Thematic"),
    ("NIFTY INDIA TOURISM", "Thematic"), ("NIFTY INDIA SELECT 5 CORPORATE GROUPS (MAATR)", "Thematic"),
    ("NIFTY INFRASTRUCTURE", "Thematic"), ("NIFTY INDIA CORPORATE GROUP - MAHINDRA", "Thematic"),
    ("NIFTY IPO", "Thematic"), ("NIFTY MIDCAP LIQUID 15", "Thematic"),
    ("NIFTY MIDSMALL INDIA CONSUMPTION", "Thematic"), ("NIFTY MNC", "Thematic"),
    ("NIFTY MOBILITY", "Thematic"), ("NIFTY PSE", "Thematic"),
    ("NIFTY REITS & INVITS", "Thematic"), ("NIFTY REITS & INVITS 90:10", "Thematic"),
    ("NIFTY RURAL", "Thematic"), ("NIFTY NON-CYCLICAL CONSUMER", "Thematic"),
    ("NIFTY SERVICES SECTOR", "Thematic"), ("NIFTY SHARIAH 25", "Thematic"),
    ("NIFTY SMALL FINANCE BANKS & MICROFINANCE INSTITUTIONS", "Thematic"),
    ("NIFTY SUGAR & ETHANOL", "Thematic"),
    ("NIFTY INDIA CORPORATE GROUP - TATA", "Thematic"),
    ("NIFTY INDIA CORPORATE GROUP - TATA 25% CAP", "Thematic"),
    ("NIFTY TRANSPORTATION & LOGISTICS", "Thematic"), ("NIFTY100 LIQUID 15", "Thematic"),
    ("NIFTY50 SHARIAH", "Thematic"), ("NIFTY500 SHARIAH", "Thematic"),
    ("NIFTY500 MULTICAP INDIA MANUFACTURING 50:30:20", "Thematic"),
    ("NIFTY500 MULTICAP INFRASTRUCTURE 50:30:20", "Thematic"),
    ("NIFTY500 AHIMSA", "Thematic"), ("NIFTY SME EMERGE", "Thematic"),
    ("NIFTY WAVES", "Thematic"),
    # Strategy / factor
    ("NIFTY 100 EQUAL WEIGHT", "Strategy"), ("NIFTY 100 LOW VOLATILITY 30", "Strategy"),
    ("NIFTY 50 ARBITRAGE", "Strategy"), ("NIFTY 50 FUTURES PR", "Strategy"),
    ("NIFTY 50 FUTURES TR", "Strategy"), ("NIFTY200 MOMENTUM 30", "Strategy"),
    ("NIFTY200 ALPHA 30", "Strategy"), ("NIFTY100 ALPHA 30", "Strategy"),
    ("NIFTY ALPHA 50", "Strategy"), ("NIFTY ALPHA LOW VOLATILITY 30", "Strategy"),
    ("NIFTY ALPHA QUALITY LOW VOLATILITY 30", "Strategy"),
    ("NIFTY ALPHA QUALITY VALUE LOW VOLATILITY 30", "Strategy"),
    ("NIFTY DIVIDEND OPPORTUNITIES 50", "Strategy"),
    ("NIFTY HIGH DIVIDEND YIELD 15", "Strategy"), ("NIFTY GROWTH SECTORS 15", "Strategy"),
    ("NIFTY HIGH BETA 50", "Strategy"), ("NIFTY LOW VOLATILITY 50", "Strategy"),
    ("NIFTY TOP 10 EQUAL WEIGHT", "Strategy"), ("NIFTY TOP 15 EQUAL WEIGHT", "Strategy"),
    ("NIFTY TOP 20 EQUAL WEIGHT", "Strategy"), ("NIFTY100 QUALITY 30", "Strategy"),
    ("NIFTY MIDCAP150 MOMENTUM 50", "Strategy"), ("NIFTY500 FLEXICAP QUALITY 30", "Strategy"),
    ("NIFTY500 GROWTH 50", "Strategy"), ("NIFTY500 LOW VOLATILITY 50", "Strategy"),
    ("NIFTY500 MOMENTUM 50", "Strategy"), ("NIFTY500 QUALITY 50", "Strategy"),
    ("NIFTY500 MULTIFACTOR MQVLV 50", "Strategy"),
    ("NIFTY MIDCAP150 QUALITY 50", "Strategy"), ("NIFTY SMALLCAP250 QUALITY 50", "Strategy"),
    ("NIFTY TOTAL MARKET MOMENTUM QUALITY 50", "Strategy"),
    ("NIFTY500 MULTICAP MOMENTUM QUALITY 50", "Strategy"),
    ("NIFTY MIDSMALLCAP400 MOMENTUM QUALITY 100", "Strategy"),
    ("NIFTY SMALLCAP250 MOMENTUM QUALITY 100", "Strategy"),
    ("NIFTY QUALITY LOW VOLATILITY 30", "Strategy"), ("NIFTY50 DIVIDEND POINTS", "Strategy"),
    ("NIFTY50 EQUAL WEIGHT", "Strategy"), ("NIFTY50 USD", "Strategy"),
    ("NIFTY50 PR 1X INVERSE", "Strategy"), ("NIFTY50 PR 2X LEVERAGE", "Strategy"),
    ("NIFTY50 TR 1X INVERSE", "Strategy"), ("NIFTY50 TR 2X LEVERAGE", "Strategy"),
    ("NIFTY50 VALUE 20", "Strategy"), ("NIFTY200 VALUE 30", "Strategy"),
    ("NIFTY500 VALUE 50", "Strategy"), ("NIFTY500 EQUAL WEIGHT", "Strategy"),
    ("NIFTY200 QUALITY 30", "Strategy"),
]
# Widely followed BSE indices. Yahoo symbol mapping is intentionally limited to
# the benchmark whose Yahoo ticker is established here.
BSE_INDEX_CATALOG = [
    ("S&P BSE SENSEX", "^BSESN", "BSE"),
    ("S&P BSE BANKEX", "", "BSE"),
    ("S&P BSE 100", "", "BSE"),
    ("S&P BSE 200", "", "BSE"),
    ("S&P BSE 500", "", "BSE"),
    ("S&P BSE MIDCAP", "", "BSE"),
    ("S&P BSE SMALLCAP", "", "BSE"),
]


def _headers(referer: str) -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": referer,
    }


def _read_nse_equity_csv(content: bytes) -> pd.DataFrame:
    frame = pd.read_csv(io.BytesIO(content), dtype=str)
    frame.columns = [str(c).strip().upper() for c in frame.columns]
    if "SYMBOL" not in frame.columns or "SERIES" not in frame.columns:
        raise ValueError("NSE equity CSV did not contain SYMBOL and SERIES columns")
    frame["SYMBOL"] = frame["SYMBOL"].astype(str).str.strip()
    frame["SERIES"] = frame["SERIES"].astype(str).str.strip().str.upper()
    frame = frame[(frame["SERIES"] == "EQ") & frame["SYMBOL"].ne("") & frame["SYMBOL"].ne("NAN")]
    name_col = "NAME OF COMPANY" if "NAME OF COMPANY" in frame.columns else "SYMBOL"
    frame["NAME"] = frame[name_col].fillna(frame["SYMBOL"]).astype(str).str.strip()
    frame = frame.drop_duplicates(subset=["SYMBOL"], keep="last")
    return frame[["SYMBOL", "NAME", "SERIES"]].sort_values("SYMBOL").reset_index(drop=True)


def get_nse_equity_universe(force_refresh: bool = False) -> pd.DataFrame:
    """Fetch the official NSE cash-market EQ-series list; use 24h cache on success."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cached = None
    if NSE_CACHE_FILE.exists():
        try:
            cached = _read_nse_equity_csv(NSE_CACHE_FILE.read_bytes())
            fresh = time.time() - NSE_CACHE_FILE.stat().st_mtime < 24 * 60 * 60
            if not force_refresh and fresh and not cached.empty:
                return cached
        except Exception:
            cached = None

    session = requests.Session()
    headers = _headers(NSE_HOME)
    try:
        session.get(NSE_HOME, headers=headers, timeout=20)
        response = session.get(NSE_EQUITY_CSV, headers=headers, timeout=30)
        response.raise_for_status()
        frame = _read_nse_equity_csv(response.content)
        if frame.empty:
            raise RuntimeError("NSE returned an empty EQ-series list")
        NSE_CACHE_FILE.write_bytes(response.content)
        return frame
    except Exception as exc:
        if cached is not None and not cached.empty:
            return cached
        raise RuntimeError("NSE EQ list is unavailable and no cache exists.") from exc


def _read_nse_sme_csv(content: bytes) -> pd.DataFrame:
    """Parse NSE's separate SME equity-segment security list."""
    frame = pd.read_csv(io.BytesIO(content), dtype=str)
    frame.columns = [re.sub(r"[^A-Z0-9]", "", str(c).upper()) for c in frame.columns]
    if "SYMBOL" not in frame.columns:
        raise ValueError("NSE SME CSV did not contain SYMBOL")
    name_col = next((c for c in ["NAMEOFCOMPANY", "COMPANYNAME", "NAME", "ISSUERNAME"] if c in frame.columns), None)
    symbols = frame["SYMBOL"].fillna("").astype(str).str.strip()
    names = frame[name_col].fillna(symbols).astype(str).str.strip() if name_col else symbols
    result = pd.DataFrame({"SYMBOL": symbols, "NAME": names})
    result = result[result["SYMBOL"].ne("") & result["SYMBOL"].str.lower().ne("nan")]
    result = result.drop_duplicates(subset=["SYMBOL"]).sort_values("SYMBOL").reset_index(drop=True)
    if result.empty:
        raise ValueError("NSE SME CSV contained no symbols")
    return result


def get_nse_sme_universe(force_refresh: bool = False) -> pd.DataFrame:
    """Fetch the official NSE SME equity list, with a 24-hour local cache."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cached = None
    if NSE_SME_CACHE_FILE.exists():
        try:
            cached = _read_nse_sme_csv(NSE_SME_CACHE_FILE.read_bytes())
            fresh = time.time() - NSE_SME_CACHE_FILE.stat().st_mtime < 24 * 60 * 60
            if not force_refresh and fresh and not cached.empty:
                return cached
        except Exception:
            cached = None
    session = requests.Session()
    headers = _headers(NSE_HOME)
    try:
        session.get(NSE_HOME, headers=headers, timeout=20)
        response = session.get(NSE_SME_CSV, headers=headers, timeout=30)
        response.raise_for_status()
        frame = _read_nse_sme_csv(response.content)
        NSE_SME_CACHE_FILE.write_bytes(response.content)
        return frame
    except Exception as exc:
        if cached is not None and not cached.empty:
            return cached
        raise RuntimeError("NSE SME list is unavailable and no cache exists.") from exc


def _normalise_columns(frame: pd.DataFrame) -> dict[str, str]:
    return {re.sub(r"[^A-Z0-9]", "", str(col).upper()): col for col in frame.columns}


def _parse_bse_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Parse BSE standard scrip master fields (headered or position-based)."""
    if frame is None or frame.empty:
        raise ValueError("Empty BSE scrip file")
    cols = _normalise_columns(frame)
    symbol_keys = ["INSTRUMENTCODE", "SCRIPID", "SECURITYID", "TRADINGSYMBOL", "SYMBOL"]
    name_keys = ["SCRIPNAME", "SECURITYNAME", "ISSUERNAME", "NAME", "SCNAME"]
    type_keys = ["SECURITYTYPEFLAG", "SECURITYTYPE", "INSTRUMENTTYPE"]
    group_keys = ["GROUPNAME", "SCRIPGROUP", "GROUP"]
    symbol_col = next((cols[k] for k in symbol_keys if k in cols), None)
    name_col = next((cols[k] for k in name_keys if k in cols), None)
    type_col = next((cols[k] for k in type_keys if k in cols), None)
    group_col = next((cols[k] for k in group_keys if k in cols), None)

    if symbol_col is not None:
        symbols = frame[symbol_col].astype(str).str.strip()
        names = frame[name_col].astype(str).str.strip() if name_col else symbols
        result = pd.DataFrame({"SYMBOL": symbols, "NAME": names})
        if type_col:
            result = result[frame[type_col].astype(str).str.strip().str.upper().eq("EQ").values]
        if group_col:
            result["GROUP"] = frame.loc[result.index, group_col].astype(str).str.strip()
    else:
        # BSE standard master field order starts: Scrip Code, Instrument Code,
        # Group Name, Scrip Name, ISIN, Market Lot, Face Value, Security Type Flag.
        if frame.shape[1] < 8:
            raise ValueError("Unrecognised BSE scrip-master columns")
        result = pd.DataFrame({
            "SYMBOL": frame.iloc[:, 1].astype(str).str.strip(),
            "NAME": frame.iloc[:, 3].astype(str).str.strip(),
        })
        result = result[frame.iloc[:, 7].astype(str).str.strip().str.upper().eq("EQ").values]
        result["GROUP"] = frame.iloc[result.index, 2].astype(str).str.strip()

    result = result[result["SYMBOL"].ne("") & result["SYMBOL"].str.lower().ne("nan")]
    result = result[~result["SYMBOL"].str.contains(r"[^A-Za-z0-9&._-]", regex=True)]
    result = result.drop_duplicates(subset=["SYMBOL"]).reset_index(drop=True)
    if result.empty:
        raise ValueError("BSE master contained no equity scrips")
    return result


def _read_bse_zip(content: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        candidates = [n for n in archive.namelist() if n.lower().endswith((".csv", ".txt")) and not n.endswith("/")]
        errors = []
        for member in candidates:
            raw = archive.read(member)
            for sep in [",", "|"]:
                try:
                    frame = pd.read_csv(io.BytesIO(raw), sep=sep, dtype=str, header=0, engine="python")
                    return _parse_bse_frame(frame)
                except Exception as exc:
                    errors.append(str(exc))
                try:
                    frame = pd.read_csv(io.BytesIO(raw), sep=sep, dtype=str, header=None, engine="python")
                    return _parse_bse_frame(frame)
                except Exception as exc:
                    errors.append(str(exc))
        raise ValueError("Could not parse BSE SCRIP.ZIP: " + "; ".join(errors[-3:]))


def _fetch_bse_bhavcopy_fallback(session: requests.Session) -> pd.DataFrame:
    """Fallback: collect symbols traded in a recent official BSE daily bhavcopy."""
    today = datetime.now().date()
    headers = _headers("https://www.bseindia.com/")
    last_error = None
    for offset in range(1, 11):
        day = today - timedelta(days=offset)
        datestr = day.strftime("%Y%m%d")
        url = f"https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{datestr}_F_0000.CSV"
        try:
            response = session.get(url, headers=headers, timeout=20)
            if response.status_code != 200 or not response.content:
                continue
            frame = pd.read_csv(io.BytesIO(response.content), dtype=str)
            cols = _normalise_columns(frame)
            symbol_col = next((cols[k] for k in ["TCKRSYMB", "TRADINGSYMBOL", "SYMBOL", "SCNAME"] if k in cols), None)
            name_col = next((cols[k] for k in ["FININSTRMNM", "SECURITYNAME", "SCNAME", "NAME"] if k in cols), None)
            if symbol_col is None:
                continue
            out = pd.DataFrame({
                "SYMBOL": frame[symbol_col].astype(str).str.strip(),
                "NAME": frame[name_col].astype(str).str.strip() if name_col else frame[symbol_col].astype(str).str.strip(),
            })
            out = out[out["SYMBOL"].ne("") & out["SYMBOL"].str.lower().ne("nan")]
            out = out[~out["SYMBOL"].str.contains(r"[^A-Za-z0-9&._-]", regex=True)]
            if not out.empty:
                out = out.drop_duplicates(subset="SYMBOL").reset_index(drop=True)
                out["SOURCE_NOTE"] = f"BSE daily bhavcopy {day.isoformat()} (traded symbols only)"
                return out
        except Exception as exc:
            last_error = exc
    raise RuntimeError("BSE scrip master and recent bhavcopy are unavailable") from last_error


def get_bse_equity_universe(force_refresh: bool = False) -> tuple[pd.DataFrame, str]:
    """Fetch BSE EQ scrips, falling back to recent traded symbols if needed."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cached = None
    if BSE_CACHE_FILE.exists():
        try:
            cached = _parse_bse_frame(pd.read_csv(BSE_CACHE_FILE, dtype=str))
            fresh = time.time() - BSE_CACHE_FILE.stat().st_mtime < 24 * 60 * 60
            if not force_refresh and fresh and not cached.empty:
                source_note = BSE_SOURCE_FILE.read_text(encoding="utf-8").strip() if BSE_SOURCE_FILE.exists() else "BSE equity scrip cache"
                return cached, source_note + " (cached up to 24 hours)"
        except Exception:
            cached = None

    session = requests.Session()
    try:
        response = session.get(BSE_SCRIP_ZIP, headers=_headers("https://www.bseindia.com/"), timeout=30)
        response.raise_for_status()
        frame = _read_bse_zip(response.content)
        frame.to_csv(BSE_CACHE_FILE, index=False)
        BSE_SOURCE_FILE.write_text("BSE official SCRIP.ZIP master", encoding="utf-8")
        return frame, "BSE official SCRIP.ZIP master"
    except Exception:
        if cached is not None and not cached.empty:
            return cached, "Cached BSE security master"
        frame = _fetch_bse_bhavcopy_fallback(session)
        frame.to_csv(BSE_CACHE_FILE, index=False)
        note = str(frame["SOURCE_NOTE"].iloc[0]) if "SOURCE_NOTE" in frame.columns else "Recent BSE bhavcopy"
        BSE_SOURCE_FILE.write_text(note, encoding="utf-8")
        return frame, note


def _index_rows(include_all: bool = True) -> list[dict[str, str | bool]]:
    rows: list[dict[str, str | bool]] = []
    seen = set()
    for name, category in NIFTY_EQUITY_INDEX_CATALOG:
        key = name.upper()
        if key in seen:
            continue
        seen.add(key)
        provider_symbol = YAHOO_INDEX_SYMBOLS.get(key, "")
        rows.append({
            "Symbol": provider_symbol,
            "Name": name,
            "Type": "Index",
            "Exchange": "NSE",
            "Category": category,
            "DataAvailable": bool(provider_symbol),
        })
    for name, provider_symbol, exchange in BSE_INDEX_CATALOG:
        rows.append({
            "Symbol": provider_symbol,
            "Name": name,
            "Type": "Index",
            "Exchange": exchange,
            "Category": "BSE Index",
            "DataAvailable": bool(provider_symbol),
        })
    return rows


def make_universe(mode: str, custom_symbols: str = "") -> pd.DataFrame:
    """Build selected NSE/BSE stock and index universe.

    Rows with blank Symbol are official catalogue entries whose Yahoo Finance
    ticker has not been verified. The dashboard reports these separately.
    """
    rows: list[dict[str, str | bool]] = []
    want_nse = mode in {
        "All NSE EQ stocks", "All NSE EQ + SME stocks", "All NSE + BSE stocks",
        "All NSE + BSE stocks + SME", "All India stocks + indices",
        "All NSE + BSE stocks + all indices",
    }
    want_sme = mode in {
        "All NSE EQ + SME stocks", "All NSE + BSE stocks + SME",
        "All India stocks + indices", "All NSE + BSE stocks + all indices",
    }
    want_bse = mode in {
        "All BSE EQ stocks", "All NSE + BSE stocks", "All India stocks + indices",
        "All NSE + BSE stocks + all indices",
    }
    want_indices = mode in {
        "All Indian indices", "Major Indian indices", "All India stocks + indices",
        "All NSE + BSE stocks + all indices",
    }

    if want_nse:
        stocks = get_nse_equity_universe()
        for item in stocks.itertuples(index=False):
            rows.append({
                "Symbol": f"{item.SYMBOL}.NS", "Name": item.NAME, "Type": "Stock",
                "Exchange": "NSE", "Category": "Equity EQ", "DataAvailable": True,
            })

    if want_sme:
        try:
            sme_stocks = get_nse_sme_universe()
            for item in sme_stocks.itertuples(index=False):
                rows.append({
                    "Symbol": f"{item.SYMBOL}.NS", "Name": item.NAME, "Type": "Stock",
                    "Exchange": "NSE-SME", "Category": "SME", "DataAvailable": True,
                })
        except Exception as exc:
            rows.append({
                "Symbol": "", "Name": f"NSE SME universe unavailable: {str(exc)[:180]}",
                "Type": "Source warning", "Exchange": "NSE-SME", "Category": "Data source",
                "DataAvailable": False,
            })

    if want_bse:
        try:
            bse_stocks, source_note = get_bse_equity_universe()
            for item in bse_stocks.itertuples(index=False):
                ticker = f"{item.SYMBOL}.BO"
                rows.append({
                    "Symbol": ticker, "Name": item.NAME, "Type": "Stock",
                    "Exchange": "BSE", "Category": source_note, "DataAvailable": True,
                })
        except Exception as exc:
            rows.append({
                "Symbol": "", "Name": f"BSE universe unavailable: {str(exc)[:180]}",
                "Type": "Source warning", "Exchange": "BSE", "Category": "Data source",
                "DataAvailable": False,
            })

    if want_indices:
        rows.extend(_index_rows())

    if mode == "Custom symbols" and custom_symbols.strip():
        index_aliases = {
            "NIFTY": "^NSEI", "NIFTY 50": "^NSEI", "NIFTY50": "^NSEI",
            "NIFTY NEXT 50": "^NSMIDCP", "NIFTY 100": "^CNX100",
            "NIFTY BANK": "^NSEBANK", "BANKNIFTY": "^NSEBANK",
            "NIFTY FINANCIAL SERVICES": "^CNXFINANCE",
            "NIFTY FINANCIAL SERVICES 25/50": "^CNXFIN",
            "NIFTY IT": "^CNXIT", "NIFTY AUTO": "^CNXAUTO", "NIFTY FMCG": "^CNXFMCG",
            "NIFTY PHARMA": "^CNXPHARMA", "NIFTY METAL": "^CNXMETAL",
            "NIFTY REALTY": "^CNXREALTY", "NIFTY ENERGY": "^CNXENERGY",
            "NIFTY MEDIA": "^CNXMEDIA", "NIFTY PSU BANK": "^CNXPSUBANK",
            "NIFTY INFRA": "^CNXINFRA", "SENSEX": "^BSESN",
            "BSE SENSEX": "^BSESN", "INDIA VIX": "^INDIAVIX",
        }
        for raw in custom_symbols.replace("\n", ",").split(","):
            ticker = raw.strip().upper()
            if not ticker:
                continue
            if ticker.startswith("NSE:"):
                ticker = ticker.split(":", 1)[1]
            if ticker in index_aliases:
                symbol = index_aliases[ticker]
                exchange, category, kind = "NSE/BSE", "Index", "Index"
            elif ticker.startswith("BSE:"):
                symbol = ticker.split(":", 1)[1] + ".BO"
                exchange, category, kind = "BSE", "Custom", "Stock"
            elif ticker.startswith("NSE:"):
                symbol = ticker.split(":", 1)[1] + ".NS"
                exchange, category, kind = "NSE", "Custom", "Stock"
            elif ticker.isalpha() and not ticker.endswith((".NS", ".BO")):
                symbol = ticker + ".NS"
                exchange, category, kind = "NSE", "Custom", "Stock"
            else:
                symbol = ticker
                exchange, category, kind = "Custom", "Custom", "Custom"
            rows.append({
                "Symbol": symbol, "Name": ticker, "Type": kind,
                "Exchange": exchange, "Category": category, "DataAvailable": True,
            })

    result = pd.DataFrame(rows, columns=["Symbol", "Name", "Type", "Exchange", "Category", "DataAvailable"])
    if result.empty:
        return result
    # Keep NSE and BSE listings distinct (same company can legitimately have two tickers).
    result = result.drop_duplicates(subset=["Symbol", "Name", "Exchange"]).reset_index(drop=True)
    result["Symbol"] = result["Symbol"].fillna("")
    return result
