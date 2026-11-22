import numpy as np
import pandas as pd

from algo_research import ALGO_NAMES, backtest_algo, build_signals


def _sample_ohlc(n=700):
    rng = np.random.default_rng(17)
    dates = pd.bdate_range("2022-01-03", periods=n)
    returns = rng.normal(0.0005, 0.012, n)
    close = 1000 * np.exp(np.cumsum(returns))
    open_ = close * (1 + rng.normal(0, 0.002, n))
    high = np.maximum(open_, close) * 1.006
    low = np.minimum(open_, close) * 0.994
    volume = rng.integers(100000, 500000, n)
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=dates,
    )


def test_confluence_combo_is_registered_and_returns_only_valid_positions():
    frame = _sample_ohlc()
    assert "Confluence Combo (10-Indicator)" in ALGO_NAMES
    signal = build_signals(frame)["Confluence Combo (10-Indicator)"]
    assert set(signal.dropna().unique()).issubset({-1, 0, 1})


def test_confluence_backtest_reports_net_metrics_and_curve():
    frame = _sample_ohlc()
    summary, trades, curve = backtest_algo(
        frame,
        "Confluence Combo (10-Indicator)",
        charges_bps_per_side=12,
        slippage_bps_per_side=5,
    )
    assert summary["Algo"] == "Confluence Combo (10-Indicator)"
    assert "Profit Factor" in summary
    assert "Expectancy / Trade %" in summary
    assert "Win Rate %" in summary
    assert "Net Return %" in trades.columns
    assert {"Strategy Equity", "Benchmark", "Drawdown %"}.issubset(curve.columns)
    assert np.isfinite(summary["Total Return %"])
