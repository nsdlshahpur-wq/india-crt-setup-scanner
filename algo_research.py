"""Research-only technical strategy backtests for Yahoo-mapped Indian indices."""
from __future__ import annotations

import numpy as np
import pandas as pd

ALGO_NAMES = [
    "SMA 20/50 Crossover",
    "EMA 9/21 Crossover",
    "RSI 14 Mean Reversion",
    "MACD 12/26/9",
    "Supertrend 10/3",
    "Bollinger Bands 20/2",
    "Donchian 20 Breakout",
    "20-Day Momentum",
    "Volume Breakout",
    "EMA 20 + RSI Trend Filter",
    "Confluence Combo (10-Indicator)",
]


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _supertrend(data: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.Series:
    high, low, close = data["High"], data["Low"], data["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([(high-low), (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    mid = (high + low) / 2
    upper = mid + multiplier * atr
    lower = mid - multiplier * atr
    direction = pd.Series(0, index=data.index, dtype=int)
    final_upper = upper.copy()
    final_lower = lower.copy()
    for i in range(1, len(data)):
        if pd.isna(atr.iloc[i]):
            continue
        if close.iloc[i-1] <= final_upper.iloc[i-1]:
            final_upper.iloc[i] = min(upper.iloc[i], final_upper.iloc[i-1])
        if close.iloc[i-1] >= final_lower.iloc[i-1]:
            final_lower.iloc[i] = max(lower.iloc[i], final_lower.iloc[i-1])
        if direction.iloc[i-1] <= 0:
            direction.iloc[i] = 1 if close.iloc[i] > final_upper.iloc[i] else -1
        else:
            direction.iloc[i] = -1 if close.iloc[i] < final_lower.iloc[i] else 1
    return direction


def build_signals(data: pd.DataFrame) -> dict[str, pd.Series]:
    frame = data.copy()
    frame.columns = [str(c).title() for c in frame.columns]
    close = pd.to_numeric(frame["Close"], errors="coerce")
    high = pd.to_numeric(frame["High"], errors="coerce")
    low = pd.to_numeric(frame["Low"], errors="coerce")
    volume = pd.to_numeric(frame.get("Volume", pd.Series(0, index=frame.index)), errors="coerce").fillna(0)
    sma20, sma50 = close.rolling(20).mean(), close.rolling(50).mean()
    ema9, ema21, ema20 = close.ewm(span=9, adjust=False).mean(), close.ewm(span=21, adjust=False).mean(), close.ewm(span=20, adjust=False).mean()
    rsi = _rsi(close)
    macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    macd_signal = macd.ewm(span=9, adjust=False).mean()
    std = close.rolling(20).std()
    upper, lower = sma20 + 2 * std, sma20 - 2 * std
    prior_high, prior_low = high.shift(1).rolling(20).max(), low.shift(1).rolling(20).min()
    vol_avg = volume.shift(1).rolling(20).mean()
    signal_map = {
        "SMA 20/50 Crossover": pd.Series(np.where(sma20 > sma50, 1, -1), index=frame.index),
        "EMA 9/21 Crossover": pd.Series(np.where(ema9 > ema21, 1, -1), index=frame.index),
        "RSI 14 Mean Reversion": pd.Series(np.select([rsi < 30, rsi > 70], [1, -1], default=0), index=frame.index),
        "MACD 12/26/9": pd.Series(np.where(macd > macd_signal, 1, -1), index=frame.index),
        "Supertrend 10/3": _supertrend(frame),
        "Bollinger Bands 20/2": pd.Series(np.select([close < lower, close > upper], [1, -1], default=0), index=frame.index),
        "Donchian 20 Breakout": pd.Series(np.select([close > prior_high, close < prior_low], [1, -1], default=0), index=frame.index),
        "20-Day Momentum": pd.Series(np.where(close > close.shift(20), 1, -1), index=frame.index),
        "Volume Breakout": pd.Series(np.select([(close > prior_high) & (volume > vol_avg * 1.5), (close < prior_low) & (volume > vol_avg * 1.5)], [1, -1], default=0), index=frame.index),
        "EMA 20 + RSI Trend Filter": pd.Series(np.select([(close > ema20) & (rsi > 50), (close < ema20) & (rsi < 50)], [1, -1], default=0), index=frame.index),
    }
    # Weighted confluence: five core trend votes plus five confirmations.
    trend_long = ((sma20 > sma50).astype(int) + (ema9 > ema21).astype(int)
        + (macd > macd_signal).astype(int) + (_supertrend(frame) > 0).astype(int)
        + ((close > ema20) & (rsi > 50)).astype(int))
    trend_short = ((sma20 < sma50).astype(int) + (ema9 < ema21).astype(int)
        + (macd < macd_signal).astype(int) + (_supertrend(frame) < 0).astype(int)
        + ((close < ema20) & (rsi < 50)).astype(int))
    confirm_long = ((close > close.shift(20)).astype(int)
        + ((rsi >= 50) & (rsi <= 68)).astype(int) + (close > prior_high).astype(int)
        + ((close > upper) & (volume > vol_avg * 1.2)).astype(int)
        + ((close > sma20) & (close > ema20)).astype(int))
    confirm_short = ((close < close.shift(20)).astype(int)
        + ((rsi <= 50) & (rsi >= 32)).astype(int) + (close < prior_low).astype(int)
        + ((close < lower) & (volume > vol_avg * 1.2)).astype(int)
        + ((close < sma20) & (close < ema20)).astype(int))
    combo = pd.Series(0, index=frame.index, dtype=int)
    combo.loc[(trend_long >= 4) & (confirm_long >= 3) & ((trend_long * 2 + confirm_long) >= 11)] = 1
    combo.loc[(trend_short >= 4) & (confirm_short >= 3) & ((trend_short * 2 + confirm_short) >= 11)] = -1
    signal_map["Confluence Combo (10-Indicator)"] = combo
    return signal_map


def backtest_algo(data: pd.DataFrame, algo_name: str, charges_bps_per_side: float = 12.0, slippage_bps_per_side: float = 5.0) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    """Execute close-generated signals at the next session open; long/short research simulation."""
    frame = data.copy()
    frame.columns = [str(c).title() for c in frame.columns]
    frame = frame.dropna(subset=["Open", "High", "Low", "Close"]).copy()
    signals = build_signals(frame)[algo_name].fillna(0).astype(int)
    # A signal observed at today's close is acted on at the next trading day's open.
    desired = signals.shift(1).fillna(0).astype(int)
    open_price = pd.to_numeric(frame["Open"], errors="coerce")
    daily_returns = desired.shift(1).fillna(0) * open_price.pct_change().fillna(0)
    # Include overnight/open-to-open return after the position is active.
    changes = desired.diff().fillna(desired.iloc[0] if len(desired) else 0)
    friction = (charges_bps_per_side + slippage_bps_per_side) / 10000.0
    costs = changes.abs() * friction
    strategy_returns = (daily_returns - costs).replace([np.inf, -np.inf], np.nan).fillna(0)
    equity = (1 + strategy_returns).cumprod()
    benchmark = open_price / open_price.iloc[0] if len(open_price) and open_price.iloc[0] else pd.Series(1.0, index=frame.index)
    entries = []
    current = 0
    entry_date = None
    entry_price = None
    for i, position in enumerate(desired.tolist()):
        if position != current:
            if current != 0 and entry_date is not None and entry_price:
                exit_price = float(open_price.iloc[i])
                gross = current * (exit_price / entry_price - 1) * 100
                entries.append({"Entry Date": entry_date, "Exit Date": str(frame.index[i].date()), "Side": "LONG" if current > 0 else "SHORT", "Entry Price": entry_price, "Exit Price": exit_price, "Gross Return %": gross, "Status": "CLOSED"})
            if position != 0:
                entry_date = str(frame.index[i].date())
                entry_price = float(open_price.iloc[i])
            else:
                entry_date = entry_price = None
            current = position
    if current != 0 and entry_date is not None:
        last_price = float(open_price.iloc[-1])
        gross = current * (last_price / entry_price - 1) * 100
        entries.append({"Entry Date": entry_date, "Exit Date": str(frame.index[-1].date()), "Side": "LONG" if current > 0 else "SHORT", "Entry Price": entry_price, "Exit Price": last_price, "Gross Return %": gross, "Status": "OPEN"})
    total_return = (float(equity.iloc[-1]) - 1) * 100 if len(equity) else 0.0
    years = max((frame.index[-1] - frame.index[0]).days / 365.25, 1 / 365.25) if len(frame) else 1
    cagr = ((float(equity.iloc[-1]) ** (1 / years)) - 1) * 100 if len(equity) and equity.iloc[-1] > 0 else -100.0
    peak = equity.cummax()
    drawdown = (equity / peak - 1) * 100
    trade_frame = pd.DataFrame(entries)
    if not trade_frame.empty:
        round_trip_cost_pct = 2 * friction * 100
        trade_frame["Net Return %"] = trade_frame["Gross Return %"] - round_trip_cost_pct
        closed_net = trade_frame.loc[trade_frame["Status"] == "CLOSED", "Net Return %"]
        wins = int((closed_net > 0).sum())
        gross_profit = float(closed_net[closed_net > 0].sum())
        gross_loss = float(abs(closed_net[closed_net < 0].sum()))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
        expectancy = float(closed_net.mean()) if len(closed_net) else 0.0
    else:
        wins, profit_factor, expectancy = 0, 0.0, 0.0
        trade_frame["Net Return %"] = pd.Series(dtype=float)
        closed_net = pd.Series(dtype=float)
    closed = len(closed_net)
    summary = {
        "Algo": algo_name, "Total Return %": total_return, "CAGR %": cagr,
        "Max Drawdown %": float(drawdown.min()) if len(drawdown) else 0.0,
        "Win Rate %": wins / max(closed, 1) * 100,
        "Profit Factor": profit_factor, "Expectancy / Trade %": expectancy,
        "Trades": len(trade_frame), "Closed Trades": closed,
        "Exposure %": float((desired != 0).mean() * 100) if len(desired) else 0.0,
        "Benchmark Return %": (float(benchmark.iloc[-1]) - 1) * 100 if len(benchmark) else 0.0,
        "Data Bars": len(frame),
    }
    curve = pd.DataFrame({"Date": frame.index, "Strategy Equity": equity.values, "Benchmark": benchmark.values, "Drawdown %": drawdown.values})
    return summary, trade_frame, curve
