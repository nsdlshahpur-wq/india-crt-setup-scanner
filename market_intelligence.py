"""Free, explainable market-intelligence features for the central CRT assistant.

This module computes indicators from the app's downloaded OHLC data and reads
public Google News RSS headlines. It does not place orders or predict certainty.
"""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
import re
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd
import requests

POSITIVE_WORDS = {
    "beat", "beats", "growth", "upgrade", "upgraded", "profit", "profits",
    "surge", "surges", "record", "buyback", "dividend", "approval", "approved",
    "order", "wins", "inflow", "inflows", "bullish", "strong", "outperform",
    "expansion", "acquisition", "positive", "recovery", "rally",
}
NEGATIVE_WORDS = {
    "miss", "misses", "loss", "losses", "downgrade", "downgraded", "fraud",
    "probe", "investigation", "penalty", "ban", "default", "debt", "fall",
    "falls", "crash", "weak", "weakness", "outflow", "outflows", "bearish",
    "warning", "cuts", "cut", "decline", "negative", "layoff", "resigns",
    "resignation", "recall", "lawsuit",
}


def _clean_prices(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    data = frame.copy()
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = [str(c[-1]).title() for c in data.columns]
    data.columns = [str(c).title() for c in data.columns]
    if not {"Close", "High", "Low"}.issubset(data.columns):
        return pd.DataFrame()
    data.index = pd.to_datetime(data.index, errors="coerce")
    data = data.loc[~data.index.isna()].sort_index()
    if getattr(data.index, "tz", None) is not None:
        data.index = data.index.tz_localize(None)
    for col in ("Close", "High", "Low"):
        data[col] = pd.to_numeric(data[col], errors="coerce")
    return data.dropna(subset=["Close"])


def _rsi(close: pd.Series, period: int = 14) -> float | None:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    loss = -delta.clip(upper=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    if len(close) < period + 1:
        return None
    g, l = float(gain.iloc[-1]), float(loss.iloc[-1])
    if not np.isfinite(g + l):
        return None
    if l == 0:
        return 100.0
    return round(100 - (100 / (1 + g / l)), 2)


def _asset_metrics(symbol: str, frame: pd.DataFrame) -> dict[str, Any] | None:
    data = _clean_prices(frame)
    close = data["Close"].dropna()
    if len(close) < 55:
        return None
    last = float(close.iloc[-1])
    prev = float(close.iloc[-2])
    sma20, sma50 = float(close.tail(20).mean()), float(close.tail(50).mean())
    ret20 = float(close.pct_change(20).iloc[-1] * 100)
    daily_returns = close.pct_change().dropna().tail(20)
    vol20 = float(daily_returns.std(ddof=1) * np.sqrt(252) * 100) if len(daily_returns) > 1 else np.nan
    return {
        "symbol": symbol, "close": round(last, 2),
        "change_1d_pct": round((last / prev - 1) * 100, 2) if prev else None,
        "return_20d_pct": round(ret20, 2),
        "sma20": round(sma20, 2), "sma50": round(sma50, 2),
        "above_sma20": bool(last > sma20), "above_sma50": bool(last > sma50),
        "rsi14": _rsi(close), "annualized_volatility_20d_pct": round(vol20, 2) if np.isfinite(vol20) else None,
        "last_bar": str(close.index[-1]),
    }


def build_market_snapshot(
    price_map: dict[str, pd.DataFrame] | None = None,
    daily_results: pd.DataFrame | None = None,
    mtf_results: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Summarise market breadth, index trend, CRT setup distribution and MTF alignment."""
    price_map = price_map or {}
    metrics = [m for s, f in price_map.items() if (m := _asset_metrics(str(s), f)) is not None]
    frame = pd.DataFrame(metrics)
    breadth: dict[str, Any] = {"symbols_with_55plus_bars": len(frame)}
    if not frame.empty:
        breadth.update({
            "advancers_1d": int((frame.change_1d_pct > 0).sum()),
            "decliners_1d": int((frame.change_1d_pct < 0).sum()),
            "unchanged_1d": int((frame.change_1d_pct == 0).sum()),
            "above_sma20": int(frame.above_sma20.sum()),
            "above_sma50": int(frame.above_sma50.sum()),
            "median_return_20d_pct": round(float(frame.return_20d_pct.median()), 2),
            "median_annualized_volatility_20d_pct": round(float(frame.annualized_volatility_20d_pct.dropna().median()), 2) if frame.annualized_volatility_20d_pct.notna().any() else None,
            "strongest_10": frame.nlargest(10, "return_20d_pct")[["symbol", "return_20d_pct"]].to_dict("records"),
            "weakest_10": frame.nsmallest(10, "return_20d_pct")[["symbol", "return_20d_pct"]].to_dict("records"),
        })
    # Index-level trend takes precedence; breadth is the fallback.
    index_candidates = [m for m in metrics if any(k in m["symbol"].upper() for k in ("^NSEI", "^NSEBANK", "NIFTY"))]
    benchmark = next((m for m in index_candidates if "NSEI" in m["symbol"].upper()), None)
    if benchmark is None and index_candidates:
        benchmark = index_candidates[0]
    above20 = breadth.get("above_sma20", 0)
    total = breadth.get("symbols_with_55plus_bars", 0)
    breadth_ratio = above20 / total if total else None
    if benchmark:
        trend_up = benchmark["close"] > benchmark["sma20"] > benchmark["sma50"]
        trend_down = benchmark["close"] < benchmark["sma20"] < benchmark["sma50"]
        vol = benchmark.get("annualized_volatility_20d_pct")
        regime = "BULL TREND" if trend_up and (breadth_ratio is None or breadth_ratio >= 0.5) else "BEAR TREND" if trend_down and (breadth_ratio is None or breadth_ratio <= 0.5) else "HIGH VOLATILITY / MIXED" if vol is not None and vol >= 25 else "SIDEWAYS / MIXED"
        breadth["benchmark"] = benchmark
    else:
        regime = "BROAD BULLISH" if breadth_ratio is not None and breadth_ratio >= 0.65 else "BROAD BEARISH" if breadth_ratio is not None and breadth_ratio <= 0.35 else "MIXED / SIDEWAYS"
    breadth["regime_rule_based"] = regime
    breadth["above_sma20_ratio"] = round(breadth_ratio, 3) if breadth_ratio is not None else None

    if isinstance(daily_results, pd.DataFrame) and not daily_results.empty:
        for col in ("Setup", "Bias", "Stage"):
            if col in daily_results.columns:
                breadth[f"daily_{col.lower()}_counts"] = daily_results[col].fillna("NA").astype(str).value_counts().head(20).to_dict()
        breadth["daily_scan_rows"] = len(daily_results)
    if isinstance(mtf_results, pd.DataFrame) and not mtf_results.empty:
        if "Signal" in mtf_results.columns:
            breadth["mtf_signal_counts"] = mtf_results["Signal"].fillna("NA").astype(str).value_counts().to_dict()
        if "CRT Pair" in mtf_results.columns:
            breadth["mtf_pair_counts"] = mtf_results["CRT Pair"].fillna("NA").astype(str).value_counts().to_dict()
        if {"Symbol", "Signal"}.issubset(mtf_results.columns):
            orders = mtf_results[mtf_results.Signal.astype(str).str.contains("ORDER", case=False, na=False)]
            breadth["symbols_with_confirmed_mtf_order"] = int(orders.Symbol.nunique())
            breadth["confirmed_mtf_order_samples"] = orders[["Symbol", "CRT Pair", "Signal"]].head(100).to_dict("records") if "CRT Pair" in orders.columns else orders[["Symbol", "Signal"]].head(100).to_dict("records")
    breadth["computed_at_utc"] = datetime.now(timezone.utc).isoformat()
    breadth["data_source"] = "Session OHLC downloaded by the app via Yahoo Finance; breadth covers only symbols with sufficient valid history."
    return breadth


def _lexicon_score(text: str) -> float:
    words = re.findall(r"[a-z]+", (text or "").lower())
    if not words:
        return 0.0
    pos = sum(w in POSITIVE_WORDS for w in words)
    neg = sum(w in NEGATIVE_WORDS for w in words)
    return (pos - neg) / max(pos + neg, 1)


def fetch_google_news_sentiment(query: str = "India stock market Nifty RBI FII", limit: int = 30) -> dict[str, Any]:
    """Fetch public Google News RSS headlines and score them with a transparent finance lexicon."""
    url = "https://news.google.com/rss/search"
    params = {"q": query, "hl": "en-IN", "gl": "IN", "ceid": "IN:en"}
    response = requests.get(url, params=params, timeout=(8, 20), headers={"User-Agent": "Mozilla/5.0 CRT-Market-Research/1.0"})
    response.raise_for_status()
    root = ET.fromstring(response.content)
    items = []
    for item in root.findall(".//item")[:max(1, min(int(limit), 100))]:
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        raw_date = item.findtext("pubDate") or ""
        try:
            published = parsedate_to_datetime(raw_date).isoformat()
        except (TypeError, ValueError, OverflowError):
            published = raw_date
        score = _lexicon_score(title)
        items.append({"title": title, "published": published, "sentiment_score": round(score, 3),
                      "sentiment": "POSITIVE" if score > 0 else "NEGATIVE" if score < 0 else "NEUTRAL"})
    if not items:
        return {"query": query, "articles": [], "article_count": 0, "average_sentiment": 0.0, "label": "NO HEADLINES"}
    avg = float(np.mean([x["sentiment_score"] for x in items]))
    return {
        "query": query, "article_count": len(items), "average_sentiment": round(avg, 3),
        "label": "POSITIVE" if avg > 0.08 else "NEGATIVE" if avg < -0.08 else "MIXED / NEUTRAL",
        "method": "Transparent finance keyword lexicon; headline-only, not FinBERT or an LLM classification.",
        "articles": items,
    }
