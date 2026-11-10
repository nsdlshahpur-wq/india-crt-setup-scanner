"""Historical backtest for the main daily three-month CRT scanner.

Signals are evaluated on completed daily candles. Entries are simulated at the
next session open to avoid look-ahead fills. If SL and target are both reached
inside one daily candle, SL is assumed to fill first (conservative OHLC rule).
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from scanner import ScanConfig, _normalise_ohlc, scan_symbol

TRADE_COLUMNS = [
    "Symbol", "Side", "Signal Date", "Entry Date", "Entry", "Stop Loss",
    "Target 2R", "Exit Date", "Exit", "Exit Reason", "Quantity",
    "Gross P&L", "Costs", "Net P&L", "R Multiple", "Equity After",
]


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def performance_metrics(trades: pd.DataFrame, initial_capital: float) -> dict[str, float | int | None]:
    if trades is None or trades.empty:
        return {
            "total_trades": 0, "win_rate": 0.0, "profit_factor": 0.0,
            "average_rr": 0.0, "max_drawdown_pct": 0.0,
            "max_drawdown_amount": 0.0, "net_pnl": 0.0,
            "ending_equity": float(initial_capital),
        }

    pnl = pd.to_numeric(trades["Net P&L"], errors="coerce").fillna(0.0)
    gross_profit = float(pnl[pnl > 0].sum())
    gross_loss = float(-pnl[pnl < 0].sum())
    profit_factor: float | None = gross_profit / gross_loss if gross_loss > 0 else (None if gross_profit > 0 else 0.0)

    equity = pd.to_numeric(trades["Equity After"], errors="coerce").fillna(initial_capital)
    equity_path = pd.concat([pd.Series([float(initial_capital)]), equity.reset_index(drop=True)], ignore_index=True)
    peaks = equity_path.cummax()
    dd_amount = peaks - equity_path
    dd_pct = dd_amount / peaks.replace(0, np.nan)
    return {
        "total_trades": int(len(trades)),
        "win_rate": float((pnl > 0).sum() / len(pnl) * 100),
        "profit_factor": profit_factor,
        "average_rr": float(pd.to_numeric(trades["R Multiple"], errors="coerce").fillna(0).mean()),
        "max_drawdown_pct": float(dd_pct.max() * 100) if dd_pct.notna().any() else 0.0,
        "max_drawdown_amount": float(dd_amount.max()) if not dd_amount.empty else 0.0,
        "net_pnl": float(pnl.sum()),
        "ending_equity": float(initial_capital + pnl.sum()),
    }


def backtest_symbol(
    symbol: str,
    name: str,
    raw_data: pd.DataFrame,
    config: ScanConfig | None = None,
    lookback_bars: int = 252,
    initial_capital: float = 100_000.0,
    risk_per_trade_pct: float = 1.0,
    target_r: float = 2.0,
    max_holding_bars: int = 20,
    round_trip_cost_bps: float = 10.0,
) -> dict[str, Any]:
    """Backtest BUY/SELL signals from scanner.scan_symbol on one daily symbol."""
    if initial_capital <= 0:
        raise ValueError("Initial capital must be greater than zero.")
    if not 0 < risk_per_trade_pct <= 10:
        raise ValueError("Risk per trade must be > 0 and <= 10 percent.")
    if target_r <= 0 or max_holding_bars < 1 or round_trip_cost_bps < 0:
        raise ValueError("Target R, holding bars and transaction costs must be valid.")

    data = _normalise_ohlc(raw_data)
    empty = pd.DataFrame(columns=TRADE_COLUMNS)
    if data.empty or len(data) < 100:
        return {
            "trades": empty,
            "metrics": performance_metrics(empty, initial_capital),
            "equity_curve": pd.DataFrame([{"Date": None, "Equity": initial_capital}]),
            "message": "कम से कम 100 daily candles उपलब्ध होने चाहिए।",
        }

    now = pd.Timestamp.now(tz="Asia/Kolkata")
    last_index = data.index[-1]
    if getattr(last_index, "tz", None) is None:
        local_last = last_index.tz_localize("Asia/Kolkata")
    else:
        local_last = last_index.tz_convert("Asia/Kolkata")
    if local_last.date() == now.date() and now.hour * 60 + now.minute < 15 * 60 + 40:
        data = data.iloc[:-1]
    if len(data) < 100:
        return {
            "trades": empty,
            "metrics": performance_metrics(empty, initial_capital),
            "equity_curve": pd.DataFrame([{"Date": None, "Equity": initial_capital}]),
            "message": "अधूरी current-day candle हटाने के बाद पर्याप्त historical data नहीं बचा।",
        }

    cfg = config or ScanConfig()
    lookback = max(1, min(int(lookback_bars), len(data) - 80))
    first_signal = max(80, len(data) - lookback - 1)
    equity = float(initial_capital)
    trade_rows: list[dict[str, Any]] = []
    equity_rows: list[dict[str, Any]] = [
        {"Date": data.index[first_signal].date().isoformat(), "Equity": equity}
    ]
    i = first_signal

    while i < len(data) - 1:
        # Only data through candle i is visible to the strategy at signal time.
        prefix = data.iloc[: i + 1]
        signal = scan_symbol(symbol, name, prefix, cfg)
        signal_date = data.index[i].date().isoformat()
        fresh = (
            signal is not None
            and signal.get("Setup") in {"BUY", "SELL"}
            and signal.get("Entry Date") == signal_date
            and _finite(signal.get("SL"))
        )
        if not fresh:
            i += 1
            continue

        side = str(signal["Setup"])
        direction = 1 if side == "BUY" else -1
        entry_i = i + 1
        entry = float(data["Open"].iloc[entry_i])
        stop = float(signal["SL"])
        risk_per_share = (entry - stop) * direction
        if not _finite(entry) or entry <= 0 or risk_per_share <= 0:
            i += 1
            continue

        cash_risk = equity * (risk_per_trade_pct / 100.0)
        qty_by_risk = int(math.floor(cash_risk / risk_per_share))
        qty_by_cash = int(math.floor(equity / entry))
        quantity = min(qty_by_risk, qty_by_cash)
        if quantity < 1:
            i += 1
            continue

        target = entry + direction * risk_per_share * target_r
        last_hold_i = min(len(data) - 1, entry_i + max_holding_bars - 1)
        exit_i = last_hold_i
        exit_price = float(data["Close"].iloc[last_hold_i])
        exit_reason = "End of Data" if last_hold_i == len(data) - 1 else "Time Exit"

        for k in range(entry_i, last_hold_i + 1):
            bar = data.iloc[k]
            o, h, low = float(bar["Open"]), float(bar["High"]), float(bar["Low"])

            # Gaps execute at the opening price (worse if beyond SL).
            if direction == 1 and o <= stop:
                exit_i, exit_price, exit_reason = k, o, "Gap through SL"
                break
            if direction == -1 and o >= stop:
                exit_i, exit_price, exit_reason = k, o, "Gap through SL"
                break
            if direction == 1 and o >= target:
                exit_i, exit_price, exit_reason = k, target, "Target"
                break
            if direction == -1 and o <= target:
                exit_i, exit_price, exit_reason = k, target, "Target"
                break

            stop_hit = low <= stop if direction == 1 else h >= stop
            target_hit = h >= target if direction == 1 else low <= target
            if stop_hit:  # conservative when both are touched on the same daily candle
                exit_i, exit_price, exit_reason = k, stop, "Stop Loss"
                break
            if target_hit:
                exit_i, exit_price, exit_reason = k, target, "Target"
                break

        gross = (exit_price - entry) * direction * quantity
        costs = (entry + exit_price) * quantity * (round_trip_cost_bps / 10_000.0)
        net = gross - costs
        risk_amount = risk_per_share * quantity
        r_multiple = net / risk_amount if risk_amount > 0 else 0.0
        equity += net
        trade_rows.append({
            "Symbol": symbol,
            "Side": side,
            "Signal Date": signal_date,
            "Entry Date": data.index[entry_i].date().isoformat(),
            "Entry": entry,
            "Stop Loss": stop,
            "Target 2R": target,
            "Exit Date": data.index[exit_i].date().isoformat(),
            "Exit": exit_price,
            "Exit Reason": exit_reason,
            "Quantity": quantity,
            "Gross P&L": gross,
            "Costs": costs,
            "Net P&L": net,
            "R Multiple": r_multiple,
            "Equity After": equity,
        })
        equity_rows.append({"Date": data.index[exit_i].date().isoformat(), "Equity": equity})
        # One active position per symbol; no overlapping backtest trades.
        i = exit_i + 1

    trades = pd.DataFrame(trade_rows, columns=TRADE_COLUMNS)
    metrics = performance_metrics(trades, initial_capital)
    return {
        "trades": trades,
        "metrics": metrics,
        "equity_curve": pd.DataFrame(equity_rows),
        "message": "Signals use scanner rules; next-session open entries; conservative same-bar SL-first execution; cost assumption applied.",
    }
