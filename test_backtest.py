"""Offline tests for the no-look-ahead CRT backtest engine."""
import pandas as pd

import backtest
from backtest import BacktestConfig, _allocate_candidates, _exit_trade, calculate_metrics, run_backtest


def _ohlc(rows, start="2024-01-01"):
    return pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"],
                        index=pd.bdate_range(start, periods=len(rows)), dtype=float)


def test_exit_checks_only_bars_after_entry_and_marks_same_bar_ambiguous():
    data = _ohlc([
        [100, 102, 99, 101],  # entry candle; must not be tested for exit
        [101, 112, 94, 105],  # future bar touches both SL 95 and target 110
        [105, 106, 100, 102],
    ])
    result = _exit_trade(data, 0, 1, 95.0, 110.0)
    assert result["exit_index"] == 1
    assert result["outcome"] == "AMBIGUOUS (SL assumed)"
    assert result["exit_price"] == 95.0


def test_gap_through_stop_uses_worse_open():
    data = _ohlc([
        [100, 102, 99, 101],
        [90, 94, 88, 92],
    ])
    result = _exit_trade(data, 0, 1, 95.0, 110.0)
    assert result["outcome"] == "LOSS"
    assert result["exit_price"] == 90.0


def test_position_sizing_respects_risk_budget_and_available_capital():
    candidates = [{
        "Symbol": "ABC.BO", "Name": "ABC", "Direction": "LONG",
        "Entry Date": "2024-01-01", "Entry Reference": 100.0,
        "Stop Loss": 90.0, "Target": 120.0, "Exit Date": "2024-01-10",
        "Exit Reference": 120.0, "Outcome": "WIN", "Entry Index": 0,
        "Exit Index": 5, "Bars Held": 5, "Entry Zone": "FVG",
        "M1 Month": "2023-10", "M2 Month": "2023-11", "M3 Month": "2023-12",
        "_direction": 1,
    }]
    cfg = BacktestConfig(initial_capital=100_000, risk_pct=1,
                         charges_bps_per_side=0, slippage_bps_per_side=0)
    result = _allocate_candidates(candidates, cfg)
    assert len(result) == 1
    assert result[0]["Quantity"] == 100
    assert result[0]["Entry Fill"] * result[0]["Quantity"] <= 100_000


def test_metrics_win_rate_excludes_ambiguous_and_open_but_pf_includes_conservative_pnl():
    trades = [
        {"Outcome": "WIN", "Net P&L": 200.0, "Charges": 10.0,
         "Entry Date": "2024-01-01", "Exit Date": "2024-01-02"},
        {"Outcome": "LOSS", "Net P&L": -100.0, "Charges": 10.0,
         "Entry Date": "2024-01-03", "Exit Date": "2024-01-04"},
        {"Outcome": "AMBIGUOUS (SL assumed)", "Net P&L": -50.0, "Charges": 5.0,
         "Entry Date": "2024-01-05", "Exit Date": "2024-01-06"},
        {"Outcome": "OPEN", "Net P&L": 25.0, "Charges": 2.0,
         "Entry Date": "2024-01-07", "Exit Date": "2024-01-08"},
    ]
    metrics = calculate_metrics(trades, 100_000)
    assert metrics["total_trades"] == 4
    assert metrics["wins"] == 1
    assert metrics["losses"] == 1
    assert metrics["ambiguous"] == 1
    assert metrics["open"] == 1
    assert metrics["win_rate"] == 50.0
    assert metrics["profit_factor"] == 200 / 150


def test_run_backtest_scanner_sees_only_asof_prefix(monkeypatch):
    data = _ohlc([[100, 101, 99, 100] for _ in range(83)])
    signal_date = data.index[79].date().isoformat()
    seen_last_dates = []

    def fake_scan(symbol, name, prefix, config):
        seen_last_dates.append(prefix.index[-1])
        if prefix.index[-1].date().isoformat() != signal_date:
            return None
        return {
            "Stage": 3, "Setup": "BUY", "Entry Date": signal_date,
            "Entry": 100.0, "SL": 95.0, "Target (M1 Monthly H/L)": 110.0,
            "Entry Zone Type": "FVG", "M1 Month": "2023-10",
            "M2 Month": "2023-11", "M3 Month": "2023-12",
        }

    # The next candle reaches target. The entry bar itself does not.
    data.iloc[80, data.columns.get_loc("High")] = 111.0
    monkeypatch.setattr(backtest, "_three_month_context",
                        lambda prefix: {"monthly_status": "VALID_BULLISH_SWEEP"})
    monkeypatch.setattr(backtest, "scan_symbol", fake_scan)
    result = run_backtest(
        {"ABC.BO": data}, names={"ABC.BO": "ABC"},
        config=BacktestConfig(initial_capital=100_000, risk_pct=1,
                              charges_bps_per_side=0, slippage_bps_per_side=0),
    )
    assert seen_last_dates
    assert max(seen_last_dates) <= data.index[-1]
    assert len(result["trades"]) == 1
    assert result["trades"].iloc[0]["Entry Date"] == signal_date
    assert result["trades"].iloc[0]["Outcome"] == "WIN"
