"""Historical, no-look-ahead backtest for the existing Monthly-Daily CRT scanner.

Signals are discovered by running the unchanged scan_symbol() against an as-of
prefix ending on each completed daily candle. Exits are evaluated only on bars
strictly after the entry confirmation close.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Callable

import numpy as np
import pandas as pd

from scanner import ScanConfig, _normalise_ohlc, scan_symbol


@dataclass(frozen=True)
class BacktestConfig:
    initial_capital: float = 100_000.0
    risk_pct: float = 1.0
    charges_bps_per_side: float = 12.0
    slippage_bps_per_side: float = 5.0
    max_prefix_bars: int = 180


def _exit_trade(
    data: pd.DataFrame,
    entry_index: int,
    direction: int,
    stop: float,
    target: float,
) -> dict[str, Any]:
    """Resolve using future daily bars only; same-bar SL/TP is ambiguous."""
    last_index = len(data) - 1
    for i in range(entry_index + 1, len(data)):
        bar = data.iloc[i]
        if direction == 1:
            hit_stop = float(bar.Low) <= stop
            hit_target = float(bar.High) >= target
        else:
            hit_stop = float(bar.High) >= stop
            hit_target = float(bar.Low) <= target

        if hit_stop and hit_target:
            # Conservative P&L treatment: price the ambiguous candle at SL,
            # but keep its status separate so it is not silently counted as a win.
            return {"exit_index": i, "exit_price": stop, "outcome": "AMBIGUOUS (SL assumed)"}
        if hit_stop:
            # Stop-market orders can gap beyond the stop; use the worse opening price.
            open_price = float(bar.Open)
            if direction == 1 and open_price < stop:
                stop_fill = open_price
            elif direction == -1 and open_price > stop:
                stop_fill = open_price
            else:
                stop_fill = stop
            return {"exit_index": i, "exit_price": stop_fill, "outcome": "LOSS"}
        if hit_target:
            # Conservative limit fill: no assumed price improvement on a gap.
            return {"exit_index": i, "exit_price": target, "outcome": "WIN"}

    return {
        "exit_index": last_index,
        "exit_price": float(data.Close.iloc[last_index]),
        "outcome": "OPEN",
    }


def _trade_costs(entry_fill: float, exit_fill: float, quantity: int, charges_rate: float) -> float:
    return (abs(entry_fill * quantity) + abs(exit_fill * quantity)) * charges_rate


def _make_candidate(
    symbol: str,
    name: str,
    data: pd.DataFrame,
    entry_index: int,
    signal: dict[str, Any],
    cfg: BacktestConfig,
) -> dict[str, Any] | None:
    direction = 1 if signal.get("Setup") == "BUY" else -1
    entry = float(signal["Entry"])
    stop = float(signal["SL"])
    target = float(signal["Target (M1 Monthly H/L)"])
    if not all(np.isfinite(v) and v > 0 for v in (entry, stop, target)):
        return None
    if (direction == 1 and not stop < entry < target) or (
        direction == -1 and not target < entry < stop
    ):
        return None

    exit_info = _exit_trade(data, entry_index, direction, stop, target)
    return {
        "Symbol": symbol,
        "Name": name,
        "Direction": "LONG" if direction == 1 else "SHORT",
        "Entry Date": pd.Timestamp(data.index[entry_index]).date().isoformat(),
        "Entry Reference": entry,
        "Stop Loss": stop,
        "Target": target,
        "Exit Date": pd.Timestamp(data.index[int(exit_info["exit_index"])]).date().isoformat(),
        "Exit Reference": float(exit_info["exit_price"]),
        "Outcome": exit_info["outcome"],
        "Entry Index": int(entry_index),
        "Exit Index": int(exit_info["exit_index"]),
        "Bars Held": int(exit_info["exit_index"] - entry_index),
        "Entry Zone": str(signal.get("Entry Zone Type", "")),
        "M1 Month": str(signal.get("M1 Month", "")),
        "M2 Month": str(signal.get("M2 Month", "")),
        "M3 Month": str(signal.get("M3 Month", "")),
        "_direction": direction,
    }


def _allocate_candidates(candidates: list[dict[str, Any]], cfg: BacktestConfig) -> list[dict[str, Any]]:
    """Risk-size trades, cap aggregate deployed notional at available equity."""
    ordered = sorted(candidates, key=lambda t: (t["Entry Date"], t["Symbol"]))
    equity = float(cfg.initial_capital)
    risk_rate = max(0.0, float(cfg.risk_pct)) / 100.0
    charges_rate = max(0.0, float(cfg.charges_bps_per_side)) / 10_000.0
    slippage_rate = max(0.0, float(cfg.slippage_bps_per_side)) / 10_000.0
    active: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []

    for candidate in ordered:
        entry_date = candidate["Entry Date"]
        still_active = []
        for prior in active:
            if prior["Exit Date"] <= entry_date:
                equity += prior["Net P&L"]
            else:
                still_active.append(prior)
        active = still_active
        reserved = sum(float(t["Entry Fill"]) * int(t["Quantity"]) for t in active)
        available = max(0.0, equity - reserved)

        direction = int(candidate["_direction"])
        entry_ref = float(candidate["Entry Reference"])
        stop = float(candidate["Stop Loss"])
        exit_ref = float(candidate["Exit Reference"])
        entry_fill = entry_ref * (1.0 + direction * slippage_rate)
        exit_fill = exit_ref * (1.0 - direction * slippage_rate)
        risk_budget = equity * risk_rate
        # Include a conservative estimate of round-trip friction in the risk/share.
        risk_per_share = abs(entry_ref - stop) + (entry_ref + stop) * (charges_rate + slippage_rate)
        if risk_per_share <= 0 or entry_fill <= 0:
            continue
        qty_by_risk = math.floor(risk_budget / risk_per_share)
        qty_by_capital = math.floor(available / entry_fill)
        quantity = max(0, min(qty_by_risk, qty_by_capital))
        if quantity < 1:
            continue

        gross = direction * (exit_fill - entry_fill) * quantity
        charges = _trade_costs(entry_fill, exit_fill, quantity, charges_rate)
        net = gross - charges
        trade = {
            **candidate,
            "Entry Fill": entry_fill,
            "Exit Fill": exit_fill,
            "Quantity": quantity,
            "Risk Budget": risk_budget,
            "Gross P&L": gross,
            "Charges": charges,
            "Net P&L": net,
            "Return %": (net / (entry_fill * quantity) * 100.0) if quantity else 0.0,
            "R Multiple": (net / risk_budget) if risk_budget else 0.0,
        }
        accepted.append(trade)
        active.append(trade)

    return accepted


def _equity_curve(trades: list[dict[str, Any]], initial_capital: float) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame(columns=["Date", "Equity", "Drawdown %"])
    dates = sorted({pd.Timestamp(t["Entry Date"]) for t in trades} |
                   {pd.Timestamp(t["Exit Date"]) for t in trades})
    curve_rows = []
    equity = float(initial_capital)
    peak = equity
    for day in dates:
        day_pnl = sum(float(t["Net P&L"]) for t in trades if pd.Timestamp(t["Exit Date"]) == day)
        equity += day_pnl
        peak = max(peak, equity)
        drawdown = ((equity / peak) - 1.0) * 100.0 if peak else 0.0
        curve_rows.append({"Date": day, "Equity": equity, "Drawdown %": drawdown})
    return pd.DataFrame(curve_rows)


def calculate_metrics(trades: list[dict[str, Any]], initial_capital: float) -> dict[str, Any]:
    """Calculate portfolio metrics; ambiguous/open trades are shown separately."""
    frame = pd.DataFrame(trades)
    if frame.empty:
        return {
            "total_trades": 0, "wins": 0, "losses": 0, "ambiguous": 0, "open": 0,
            "win_rate": 0.0, "profit_factor": 0.0, "net_pnl": 0.0,
            "net_return_pct": 0.0, "max_drawdown_pct": 0.0, "ending_equity": initial_capital,
        }
    wins = frame[frame["Outcome"] == "WIN"]
    losses = frame[frame["Outcome"] == "LOSS"]
    ambiguous = frame[frame["Outcome"].str.startswith("AMBIGUOUS")]
    open_trades = frame[frame["Outcome"] == "OPEN"]
    decisive = len(wins) + len(losses)
    gross_profit = float(wins["Net P&L"].clip(lower=0).sum() +
                         ambiguous["Net P&L"].clip(lower=0).sum())
    gross_loss = float(abs(losses["Net P&L"].clip(upper=0).sum()) +
                       abs(ambiguous["Net P&L"].clip(upper=0).sum()))
    curve = _equity_curve(trades, initial_capital)
    net_pnl = float(frame["Net P&L"].sum())
    max_dd = abs(float(curve["Drawdown %"].min())) if not curve.empty else 0.0
    return {
        "total_trades": len(frame),
        "wins": len(wins), "losses": len(losses),
        "ambiguous": len(ambiguous), "open": len(open_trades),
        "win_rate": (len(wins) / decisive * 100.0) if decisive else 0.0,
        "profit_factor": (gross_profit / gross_loss) if gross_loss else (float("inf") if gross_profit else 0.0),
        "net_pnl": net_pnl,
        "net_return_pct": net_pnl / float(initial_capital) * 100.0 if initial_capital else 0.0,
        "max_drawdown_pct": max_dd,
        "ending_equity": float(initial_capital) + net_pnl,
        "gross_profit": gross_profit, "gross_loss": gross_loss,
        "total_charges": float(frame["Charges"].sum()),
    }


def run_backtest(
    price_map: dict[str, pd.DataFrame],
    names: dict[str, str] | None = None,
    config: BacktestConfig | None = None,
    scan_config: ScanConfig | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    """Run 5y daily CRT backtest using only information available on each date.

    The first 80 observations per symbol are warm-up because scan_symbol's
    existing minimum-history requirement is preserved. Each as-of call is
    limited to the current candle and prior candles; future data is used only
    after a signal has been frozen to resolve its exit.
    """
    cfg = config or BacktestConfig()
    scfg = scan_config or ScanConfig()
    name_map = names or {}
    candidates: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    total = max(len(price_map), 1)

    for symbol_number, (symbol, raw) in enumerate(price_map.items(), start=1):
        data = _normalise_ohlc(raw)
        if len(data) < 81:
            errors[symbol] = "Insufficient daily history (need at least 81 bars including warm-up)."
            if progress_callback:
                progress_callback(symbol_number, total, symbol)
            continue
        found_for_symbol: set[str] = set()
        # No-look-ahead: scanner receives a prefix ending exactly on the day being tested.
        for asof_index in range(79, len(data) - 1):
            prefix_start = max(0, asof_index - max(160, int(cfg.max_prefix_bars)) + 1)
            prefix = data.iloc[prefix_start : asof_index + 1]
            signal = scan_symbol(symbol, name_map.get(symbol, symbol), prefix, scfg)
            if not signal or int(signal.get("Stage", 0)) != 3:
                continue
            entry_date = str(signal.get("Entry Date", ""))
            asof_date = pd.Timestamp(data.index[asof_index]).date().isoformat()
            if entry_date != asof_date or entry_date in found_for_symbol:
                continue
            # Scanner only emits Stage 3 when the current completed candle is the
            # confirmation close; assert that before looking at future bars.
            candidate = _make_candidate(symbol, name_map.get(symbol, symbol), data,
                                        asof_index, signal, cfg)
            if candidate:
                candidates.append(candidate)
                found_for_symbol.add(entry_date)
        if progress_callback:
            progress_callback(symbol_number, total, symbol)

    allocated = _allocate_candidates(candidates, cfg)
    metrics = calculate_metrics(allocated, cfg.initial_capital)
    trades_frame = pd.DataFrame(allocated)
    if not trades_frame.empty:
        trades_frame = trades_frame.drop(columns=["_direction", "Entry Index", "Exit Index"], errors="ignore")
        trades_frame = trades_frame.sort_values(["Entry Date", "Symbol"]).reset_index(drop=True)
    curve = _equity_curve(allocated, cfg.initial_capital)
    return {
        "trades": trades_frame,
        "equity_curve": curve,
        "metrics": metrics,
        "errors": errors,
        "candidate_count": len(candidates),
        "config": cfg,
    }
