"""CISD + Liquidity Sweep + FVG Retest scanner.

Rules are a mechanical interpretation of the uploaded 56-second lesson:
- Sweep prior session low/high and reclaim back inside.
- CISD line = open of the first candle in the final opposing-colour run
  immediately preceding the sweep.
- Require a candle BODY close across the CISD line (wick-only is invalid).
- Wait for a 3-candle FVG and its retest.
- Entry is next 5-minute candle open after a rejection close.
- User-selected 1:3 RR: prior opposite liquidity must lie at least 3R away;
  otherwise the setup is filtered out. Target is fixed at 3R.
Research tool only; no order placement.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class CISDConfig:
    rr: float = 3.0
    stop_buffer_points: float = 1.0
    min_bars_after_open: int = 3
    one_trade_per_day: bool = True


def resample_1m_to_5m(data: pd.DataFrame) -> pd.DataFrame:
    """Resample naive/IST 1-minute OHLC into NSE-session-aligned 5-minute bars."""
    required = {"Open", "High", "Low", "Close"}
    if data is None or data.empty or not required.issubset(data.columns):
        raise ValueError("1-minute data must contain Open, High, Low and Close.")
    frame = data.copy()
    frame.index = pd.to_datetime(frame.index)
    frame = frame.sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    # Source timestamps are assumed to be exchange-local IST, as in the
    # repository's NIFTY history loader. Do not silently convert timezone.
    frame = frame.between_time("09:15", "15:29")
    chunks = []
    for _, session in frame.groupby(frame.index.date):
        bars = session.resample(
            "5min", origin="start_day", offset="15min",
            label="left", closed="left"
        ).agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"})
        bars = bars.dropna(subset=["Open", "High", "Low", "Close"])
        bars = bars[(bars.index.time >= pd.Timestamp("09:15").time()) &
                    (bars.index.time <= pd.Timestamp("15:25").time())]
        chunks.append(bars)
    if not chunks:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close"])
    result = pd.concat(chunks).sort_index()
    result.index.name = "Timestamp"
    return result


def _is_bear(row: pd.Series) -> bool:
    return float(row["Close"]) < float(row["Open"])


def _is_bull(row: pd.Series) -> bool:
    return float(row["Close"]) > float(row["Open"])


def _run_start(data: pd.DataFrame, sweep_i: int, direction: str) -> int | None:
    """Find earliest candle in the contiguous opposing-colour run before sweep."""
    wanted = _is_bear if direction == "LONG" else _is_bull
    i = sweep_i - 1
    if i < 0 or not wanted(data.iloc[i]):
        return None
    while i > 0 and wanted(data.iloc[i - 1]):
        i -= 1
    return i


def _rr_target(entry: float, stop: float, old_liquidity: float,
               direction: str, rr: float) -> tuple[float | None, float]:
    risk = entry - stop if direction == "LONG" else stop - entry
    if risk <= 0:
        return None, risk
    available = old_liquidity - entry if direction == "LONG" else entry - old_liquidity
    if available + 1e-9 < rr * risk:
        return None, risk
    return (entry + rr * risk if direction == "LONG" else entry - rr * risk), risk


def find_day_setup(day: pd.DataFrame, previous_high: float,
                   previous_low: float, config: CISDConfig | None = None) -> dict[str, Any] | None:
    """Return first valid intraday setup. Entry index is the bar after retest."""
    cfg = config or CISDConfig()
    data = day.dropna(subset=["Open", "High", "Low", "Close"]).copy()
    if len(data) < max(8, cfg.min_bars_after_open + 4):
        return None

    state = None
    setup = None
    for i in range(cfg.min_bars_after_open, len(data) - 1):
        row = data.iloc[i]

        if state is None:
            # Sweep and close back inside the previous session's liquidity.
            bull_sweep = float(row["Low"]) < previous_low and float(row["Close"]) > previous_low
            bear_sweep = float(row["High"]) > previous_high and float(row["Close"]) < previous_high
            if bull_sweep and not bear_sweep:
                run = _run_start(data, i, "LONG")
                if run is not None:
                    state = "WAIT_CISD_LONG"
                    setup = {"side": "LONG", "sweep_i": i,
                             "sweep_extreme": float(row["Low"]),
                             "cisd_line": float(data.iloc[run]["Open"]),
                             "old_liquidity": float(previous_high)}
            elif bear_sweep and not bull_sweep:
                run = _run_start(data, i, "SHORT")
                if run is not None:
                    state = "WAIT_CISD_SHORT"
                    setup = {"side": "SHORT", "sweep_i": i,
                             "sweep_extreme": float(row["High"]),
                             "cisd_line": float(data.iloc[run]["Open"]),
                             "old_liquidity": float(previous_low)}
            continue

        if state == "WAIT_CISD_LONG":
            # Body close above CISD line; a wick through the line is not enough.
            if _is_bull(row) and float(row["Close"]) > setup["cisd_line"]:
                state = "WAIT_FVG_LONG"
                setup["cisd_i"] = i
            continue
        if state == "WAIT_CISD_SHORT":
            if _is_bear(row) and float(row["Close"]) < setup["cisd_line"]:
                state = "WAIT_FVG_SHORT"
                setup["cisd_i"] = i
            continue

        # FVG: three-candle imbalance, formed after CISD confirmation.
        if state == "WAIT_FVG_LONG" and i >= 2:
            if float(row["Low"]) > float(data.iloc[i - 2]["High"]):
                setup["fvg_low"] = float(data.iloc[i - 2]["High"])
                setup["fvg_high"] = float(row["Low"])
                setup["fvg_i"] = i
                state = "WAIT_RETEST_LONG"
            continue
        if state == "WAIT_FVG_SHORT" and i >= 2:
            if float(row["High"]) < float(data.iloc[i - 2]["Low"]):
                setup["fvg_low"] = float(row["High"])
                setup["fvg_high"] = float(data.iloc[i - 2]["Low"])
                setup["fvg_i"] = i
                state = "WAIT_RETEST_SHORT"
            continue

        # Retest must happen after the FVG-formation candle and close in the
        # direction of the reversal. Entry is next bar OPEN, never same bar.
        if state == "WAIT_RETEST_LONG" and i > setup["fvg_i"]:
            touched = float(row["Low"]) <= setup["fvg_high"] and float(row["High"]) >= setup["fvg_low"]
            if touched and _is_bull(row) and float(row["Close"]) > setup["fvg_low"]:
                entry_i = i + 1
                entry = float(data.iloc[entry_i]["Open"])
                stop = setup["sweep_extreme"] - cfg.stop_buffer_points
                target, risk = _rr_target(entry, stop, setup["old_liquidity"], "LONG", cfg.rr)
                if target is not None:
                    return {**setup, "signal_time": data.index[i],
                            "entry_time": data.index[entry_i], "entry_index": entry_i,
                            "entry": entry, "stop": stop, "target": target,
                            "risk_points": risk, "rr": cfg.rr,
                            "fvg_low": setup["fvg_low"], "fvg_high": setup["fvg_high"]}
                return None
        if state == "WAIT_RETEST_SHORT" and i > setup["fvg_i"]:
            touched = float(row["High"]) >= setup["fvg_low"] and float(row["Low"]) <= setup["fvg_high"]
            if touched and _is_bear(row) and float(row["Close"]) < setup["fvg_high"]:
                entry_i = i + 1
                entry = float(data.iloc[entry_i]["Open"])
                stop = setup["sweep_extreme"] + cfg.stop_buffer_points
                target, risk = _rr_target(entry, stop, setup["old_liquidity"], "SHORT", cfg.rr)
                if target is not None:
                    return {**setup, "signal_time": data.index[i],
                            "entry_time": data.index[entry_i], "entry_index": entry_i,
                            "entry": entry, "stop": stop, "target": target,
                            "risk_points": risk, "rr": cfg.rr,
                            "fvg_low": setup["fvg_low"], "fvg_high": setup["fvg_high"]}
                return None
    return None


def backtest_cisd(data_5m: pd.DataFrame, config: CISDConfig | None = None,
                  charges_bps_per_side: float = 0.0,
                  slippage_points_per_side: float = 0.0) -> tuple[pd.DataFrame, dict]:
    """Daily previous-session liquidity backtest; conservative same-bar SL-first."""
    cfg = config or CISDConfig()
    frame = data_5m.dropna(subset=["Open", "High", "Low", "Close"]).copy().sort_index()
    if frame.empty:
        return pd.DataFrame(), {"total_trades": 0, "message": "No 5-minute data."}
    frame["_session"] = pd.Index(frame.index.date)
    sessions = list(frame.groupby("_session", sort=True))
    trades = []
    for day_no in range(1, len(sessions)):
        day_key, day = sessions[day_no]
        _, previous = sessions[day_no - 1]
        setup = find_day_setup(day.drop(columns="_session"), float(previous["High"].max()),
                               float(previous["Low"].min()), cfg)
        if not setup:
            continue
        entry_i = int(setup["entry_index"])
        bars = day.drop(columns="_session").iloc[entry_i:]
        entry = float(setup["entry"]) + (slippage_points_per_side if setup["side"] == "LONG" else -slippage_points_per_side)
        stop, target = float(setup["stop"]), float(setup["target"])
        exit_price, exit_time, result = None, None, "OPEN"
        for ts, bar in bars.iterrows():
            if setup["side"] == "LONG":
                stop_hit = float(bar["Low"]) <= stop
                target_hit = float(bar["High"]) >= target
                if stop_hit:
                    exit_price, exit_time, result = (min(stop, float(bar["Open"])) - slippage_points_per_side), ts, "SL"
                    break
                if target_hit:
                    exit_price, exit_time, result = (target - slippage_points_per_side), ts, "TP"
                    break
            else:
                stop_hit = float(bar["High"]) >= stop
                target_hit = float(bar["Low"]) <= target
                if stop_hit:
                    exit_price, exit_time, result = (max(stop, float(bar["Open"])) + slippage_points_per_side), ts, "SL"
                    break
                if target_hit:
                    exit_price, exit_time, result = (target + slippage_points_per_side), ts, "TP"
                    break
        if exit_price is None:
            last = day.drop(columns="_session").iloc[-1]
            exit_price = float(last["Close"]) - slippage_points_per_side if setup["side"] == "LONG" else float(last["Close"]) + slippage_points_per_side
            exit_time, result = day.index[-1], "EOD"
        gross = (exit_price - entry) if setup["side"] == "LONG" else (entry - exit_price)
        notional = max(abs(entry), 1.0)
        costs = notional * (charges_bps_per_side * 2 / 10000)
        net = gross - costs
        trades.append({k: v for k, v in setup.items() if k not in {"entry_index"}} |
                      {"session": str(day_key), "exit_time": exit_time,
                       "exit": exit_price, "result": result,
                       "gross_points": gross, "estimated_cost_points": costs,
                       "net_points": net})
        if cfg.one_trade_per_day:
            continue

    trades_df = pd.DataFrame(trades)
    if trades_df.empty:
        return trades_df, {"total_trades": 0, "wins": 0, "losses": 0,
                           "win_rate": 0.0, "profit_factor": 0.0,
                           "net_points": 0.0, "max_drawdown_points": 0.0}
    decisive = trades_df[trades_df["result"].isin(["TP", "SL"])]
    wins = decisive[decisive["net_points"] > 0]
    losses = decisive[decisive["net_points"] <= 0]
    gross_profit = wins["net_points"].sum()
    gross_loss = abs(losses["net_points"].sum())
    equity = trades_df["net_points"].cumsum()
    drawdown = equity - equity.cummax()
    metrics = {
        "total_trades": int(len(trades_df)), "wins": int(len(wins)),
        "losses": int(len(losses)), "eod_exits": int((trades_df["result"] == "EOD").sum()),
        "win_rate": float(len(wins) / len(decisive) * 100) if len(decisive) else 0.0,
        "profit_factor": float(gross_profit / gross_loss) if gross_loss else float("inf") if gross_profit else 0.0,
        "net_points": float(trades_df["net_points"].sum()),
        "max_drawdown_points": float(drawdown.min()) if len(drawdown) else 0.0,
        "avg_win_points": float(wins["net_points"].mean()) if len(wins) else 0.0,
        "avg_loss_points": float(losses["net_points"].mean()) if len(losses) else 0.0,
        "rr_target": cfg.rr,
        "win_rate_note": "Win rate is TP/(TP+SL); EOD exits are reported separately."
    }
    return trades_df, metrics
