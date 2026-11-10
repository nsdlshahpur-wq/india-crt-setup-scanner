"""Offline tests for backtesting, local storage and optional AI connectors."""
from pathlib import Path

import pandas as pd

from ai_assistant import generate_market_answer
from backtesting import backtest_symbol, performance_metrics
import storage


def test_backtest_performance_metrics():
    trades = pd.DataFrame({
        "Net P&L": [100.0, -50.0, 50.0],
        "R Multiple": [1.0, -0.5, 0.5],
        "Equity After": [100100.0, 100050.0, 100100.0],
    })
    metrics = performance_metrics(trades, 100000.0)
    assert metrics["total_trades"] == 3
    assert round(metrics["win_rate"], 2) == 66.67
    assert round(metrics["profit_factor"], 2) == 3.0
    assert round(metrics["average_rr"], 2) == 0.33
    assert round(metrics["max_drawdown_amount"], 2) == 50.0


def test_backtest_short_history_returns_empty():
    dates = pd.bdate_range("2026-01-01", periods=50)
    close = pd.Series(range(100, 150), index=dates, dtype=float)
    frame = pd.DataFrame({
        "Open": close, "High": close + 1, "Low": close - 1, "Close": close
    }, index=dates)
    result = backtest_symbol("TEST.NS", "Test", frame)
    assert result["trades"].empty
    assert result["metrics"]["total_trades"] == 0


def test_storage_watchlist_alert_and_trade_journal(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", Path(tmp_path) / "crt_test.sqlite3")
    assert storage.add_watchlist("RELIANCE.NS", "Reliance") is True
    assert storage.add_watchlist("RELIANCE.NS", "Reliance") is False
    assert storage.list_watchlist()["Symbol"].tolist() == ["RELIANCE.NS"]

    assert storage.add_alert("key1", "RELIANCE.NS", "Daily", "ENTRY READY", "Valid CRT") is True
    assert storage.add_alert("key1", "RELIANCE.NS", "Daily", "ENTRY READY", "Valid CRT") is False
    assert len(storage.list_alerts()) == 1

    trade_id = storage.add_trade(
        "RELIANCE.NS", "BUY", "CRT", "Daily", "2026-10-01",
        100.0, 95.0, 110.0, 10, costs=5.0, notes="test",
    )
    result = storage.close_trade(trade_id, "2026-10-02", 110.0, extra_costs=5.0)
    assert result["pnl"] == 90.0
    assert result["r_multiple"] == 1.8
    trades = storage.list_trades()
    assert trades.iloc[0]["Status"] == "CLOSED"


def test_ai_connector_requires_key_without_network():
    try:
        generate_market_answer("Gemini", "", "test")
    except ValueError as exc:
        assert "API key" in str(exc)
    else:
        raise AssertionError("Missing API key should fail before network access.")
