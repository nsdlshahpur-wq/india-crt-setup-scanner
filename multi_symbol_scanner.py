"""Multi-symbol CRT screener translated from the supplied Pine v5 specification.

This is a Python/Streamlit read-only scanner. It uses completed HTF candles and
Yahoo Finance data; it does not place broker orders.
"""
from __future__ import annotations

from typing import Any
import pandas as pd
import yfinance as yf

from data_fetch import yahoo_ticker


HTF_OPTIONS = {
    "1H": ("60m", None, "60d"),
    "4H": ("60m", "4h", "60d"),
    "Daily": ("1d", None, "10y"),
    "Weekly": ("1wk", None, "10y"),
    "Monthly": ("1mo", None, "max"),
}


def _clean(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    data = frame.copy()
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = [str(c[0]).title() for c in data.columns]
    data.columns = [str(c).title() for c in data.columns]
    required = ["Open", "High", "Low", "Close"]
    if not all(c in data.columns for c in required):
        return pd.DataFrame()
    data = data[required].copy()
    data.index = pd.to_datetime(data.index)
    if getattr(data.index, "tz", None) is not None:
        data.index = data.index.tz_localize(None)
    return data.apply(pd.to_numeric, errors="coerce").dropna().sort_index()


def _pivots(series: pd.Series, left: int, right: int, high: bool) -> pd.Series:
    out = pd.Series(float("nan"), index=series.index)
    values = series.to_numpy()
    for i in range(left, len(values) - right):
        window = values[i-left:i+right+1]
        center = values[i]
        if center == (window.max() if high else window.min()):
            out.iloc[i + right] = center  # pivot becomes knowable after right bars
    return out


def _last_two(pivots: pd.Series) -> tuple[float | None, float | None]:
    vals = pivots.dropna()
    if len(vals) < 2:
        return None, None
    return float(vals.iloc[-1]), float(vals.iloc[-2])


def _scan_frame(frame: pd.DataFrame, pivot_len: int, mss_lookback: int,
                zone_lookback: int, min_rr: float) -> dict[str, Any]:
    data = _clean(frame)
    empty = {
        "HTF Trend": "NO DATA", "Sweep": "—", "Zone": "—",
        "Signal": "WAIT", "Price": None, "MSS": "NO",
        "RR": None, "Status": "Insufficient completed candles",
    }
    # Exclude the latest potentially forming candle.
    if len(data) > 2:
        data = data.iloc[:-1]
    if len(data) < max(2 * pivot_len + 8, 20):
        return empty.copy()

    o, h, l, c = (data[x] for x in ["Open", "High", "Low", "Close"])
    prev_high, prev_low = float(h.iloc[-2]), float(l.iloc[-2])
    last_high, last_low, last_close = float(h.iloc[-1]), float(l.iloc[-1]), float(c.iloc[-1])

    bull_sweep = last_low < prev_low and last_close > prev_low and last_close < prev_high
    bear_sweep = last_high > prev_high and last_close < prev_high and last_close > prev_low
    sweep = "BULL" if bull_sweep else "BEAR" if bear_sweep else "—"

    ph = _pivots(h, pivot_len, pivot_len, True)
    pl = _pivots(l, pivot_len, pivot_len, False)
    last_ph, prev_ph = _last_two(ph)
    last_pl, prev_pl = _last_two(pl)
    enough = None not in (last_ph, prev_ph, last_pl, prev_pl)
    bull_dow = bool(enough and last_ph > prev_ph and last_pl > prev_pl)
    bear_dow = bool(enough and last_ph < prev_ph and last_pl < prev_pl)
    trend = "BULL" if bull_dow else "BEAR" if bear_dow else "RANGE"

    bull_breaks = (c > ph.shift(1)).fillna(False)
    bear_breaks = (c < pl.shift(1)).fillna(False)
    bull_age = next((i for i, v in enumerate(reversed(bull_breaks.tolist())) if v), None)
    bear_age = next((i for i, v in enumerate(reversed(bear_breaks.tolist())) if v), None)
    bull_mss = bull_age is not None and bull_age <= mss_lookback
    bear_mss = bear_age is not None and bear_age <= mss_lookback
    mss = "BULL" if bull_mss else "BEAR" if bear_mss else "NO"

    atr = (h - l).rolling(14).mean()
    min_gap = float(atr.iloc[-1]) * 0.15 if pd.notna(atr.iloc[-1]) else 0.0
    bull_fvg_idx = [i for i in range(2, len(data))
                    if l.iloc[i] > h.iloc[i-2] and l.iloc[i] - h.iloc[i-2] >= min_gap]
    bear_fvg_idx = [i for i in range(2, len(data))
                    if h.iloc[i] < l.iloc[i-2] and l.iloc[i-2] - h.iloc[i] >= min_gap]

    zones: list[tuple[str, float, float, int, str]] = []
    if bull_fvg_idx:
        i = bull_fvg_idx[-1]
        if len(data) - 1 - i <= zone_lookback:
            zones.append(("BULL FVG", float(l.iloc[i]), float(h.iloc[i-2]), i, "BULL"))
    if bear_fvg_idx:
        i = bear_fvg_idx[-1]
        if len(data) - 1 - i <= zone_lookback:
            zones.append(("BEAR FVG", float(l.iloc[i-2]), float(h.iloc[i]), i, "BEAR"))

    # Simplified OB: last opposite candle within 20 bars before latest MSS break.
    for direction, active, label in (("BULL", bull_mss, "BULL OB"), ("BEAR", bear_mss, "BEAR OB")):
        if not active:
            continue
        opposite = (c < o) if direction == "BULL" else (c > o)
        candidates = [i for i in range(max(0, len(data)-21), len(data)-1) if bool(opposite.iloc[i])]
        if candidates:
            i = candidates[-1]
            zones.append((label, float(h.iloc[i]), float(l.iloc[i]), i, direction))

    active_zones = [z for z in zones if len(data)-1-z[3] <= zone_lookback]
    tapped = []
    for label, top, bottom, idx, direction in active_zones:
        upper, lower = max(top, bottom), min(top, bottom)
        if last_low <= upper and last_high >= lower and (
            (direction == "BULL" and last_close >= float(o.iloc[-1])) or
            (direction == "BEAR" and last_close <= float(o.iloc[-1]))
        ):
            tapped.append((label, direction, upper, lower))
    zone = tapped[-1][0] + " TAP" if tapped else (
        active_zones[-1][0] if active_zones else "—"
    )

    long_risk, long_reward = last_close - prev_low, prev_high - last_close
    short_risk, short_reward = prev_high - last_close, last_close - prev_low
    long_rr = long_reward / long_risk if long_risk > 0 else 0.0
    short_rr = short_reward / short_risk if short_risk > 0 else 0.0

    long_tap = any(z[1] == "BULL" for z in tapped)
    short_tap = any(z[1] == "BEAR" for z in tapped)
    long_signal = bull_sweep and bull_mss and bull_dow and long_tap and long_rr >= min_rr
    short_signal = bear_sweep and bear_mss and bear_dow and short_tap and short_rr >= min_rr

    return {
        "HTF Trend": trend, "Sweep": sweep, "Zone": zone,
        "Signal": "LONG" if long_signal else "SHORT" if short_signal else "WAIT",
        "Price": last_close, "MSS": mss,
        "RR": round(long_rr if long_signal else short_rr if short_signal else max(long_rr, short_rr), 2),
        "Status": "Signal confirmed" if long_signal or short_signal else "Waiting for full setup",
    }


def scan_symbol(symbol: str, timeframe: str = "4H", pivot_len: int = 5,
                mss_lookback: int = 10, zone_lookback: int = 20,
                min_rr: float = 1.5) -> dict[str, Any]:
    """Scan one ticker on the requested HTF and return dashboard fields."""
    interval, resample, period = HTF_OPTIONS[timeframe]
    raw_symbol = str(symbol).strip().upper()
    if ":" in raw_symbol:
        exchange, raw_symbol = raw_symbol.split(":", 1)
        if exchange == "NSE":
            raw_symbol = raw_symbol if raw_symbol.startswith("^") else raw_symbol
        elif exchange == "BSE":
            raw_symbol = raw_symbol if raw_symbol.startswith("^") else raw_symbol + ".BO"
        elif exchange in ("NASDAQ", "NYSE"):
            raw_symbol = raw_symbol
        elif exchange == "BINANCE" and raw_symbol.endswith("USDT"):
            raw_symbol = raw_symbol[:-4] + "-USD"
    ticker = yahoo_ticker(raw_symbol)
    try:
        raw = yf.download(ticker, period=period, interval=interval,
                           auto_adjust=False, progress=False, threads=False,
                           timeout=25)
        frame = _clean(raw)
        if resample and not frame.empty:
            frame = frame.resample(resample, label="right", closed="right").agg({
                "Open": "first", "High": "max", "Low": "min", "Close": "last"
            }).dropna()
        result = _scan_frame(frame, pivot_len, mss_lookback, zone_lookback, min_rr)
        result["Symbol"] = symbol
        result["Yahoo Ticker"] = ticker
        return result
    except Exception as exc:
        return {
            "Symbol": symbol, "Yahoo Ticker": ticker, "HTF Trend": "ERROR",
            "Sweep": "—", "Zone": "—", "Signal": "WAIT", "Price": None,
            "MSS": "—", "RR": None, "Status": f"{type(exc).__name__}: {str(exc)[:140]}",
        }


def scan_symbols(symbols: list[str], timeframe: str = "4H", **kwargs: Any) -> pd.DataFrame:
    """Scan up to 10 symbols and return a sorted results table."""
    unique = list(dict.fromkeys(str(s).strip() for s in symbols if str(s).strip()))[:10]
    rows = [scan_symbol(symbol, timeframe=timeframe, **kwargs) for symbol in unique]
    result = pd.DataFrame(rows)
    if not result.empty:
        result["_rank"] = result["Signal"].map({"LONG": 0, "SHORT": 1, "WAIT": 2}).fillna(3)
        result = result.sort_values(["_rank", "Symbol"]).drop(columns="_rank").reset_index(drop=True)
    return result
