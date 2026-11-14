"""Multi-symbol, multi-timeframe CRT scanner for all configured HTF/LTF pairs.

Each symbol is evaluated on the same five pairs defined in mtf_analysis.PAIR_SPECS:
Monthly->Daily, Weekly->4H, Daily->1H, 4H->5m and 1H->5m.
The CRT sequence is identical on every pair: HTF M1 range, HTF M2 one-side
sweep/full-range reclaim, then LTF CHoCH, zone retest and directional close.
Read-only; no broker orders are placed.
"""
from __future__ import annotations
from typing import Any
import pandas as pd
from mtf_analysis import PAIR_SPECS, analyze_mtf_symbol


def scan_symbol(symbol: str) -> tuple[pd.DataFrame, dict[str, str]]:
    """Return one row for each configured timeframe pair for a symbol."""
    return analyze_mtf_symbol(str(symbol).strip())


def scan_symbols(symbols: list[str], **kwargs: Any) -> tuple[pd.DataFrame, dict[str, str]]:
    """Scan every supplied symbol across all five timeframe pairs.

    Optional progress_callback(done, total, symbol) reports per-symbol progress.
    No arbitrary ten-symbol cap: All Index / All Stocks covers the full universe.
    """
    unique = list(dict.fromkeys(str(s).strip() for s in symbols if str(s).strip()))
    frames: list[pd.DataFrame] = []
    errors: dict[str, str] = {}
    total = len(unique)
    progress_callback = kwargs.get("progress_callback")
    for position, symbol in enumerate(unique, start=1):
        try:
            frame, symbol_errors = scan_symbol(symbol)
            if not frame.empty:
                frame.insert(0, "Symbol", symbol)
                frames.append(frame)
            for pair, message in symbol_errors.items():
                errors[f"{symbol} | {pair}"] = message
        except Exception as exc:
            errors[f"{symbol} | ALL"] = f"{type(exc).__name__}: {str(exc)[:180]}"
        if callable(progress_callback):
            progress_callback(position, total, symbol)
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return combined, errors
