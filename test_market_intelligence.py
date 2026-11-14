import numpy as np
import pandas as pd

from market_intelligence import _lexicon_score, build_market_snapshot


def _prices(start=100.0, periods=90, step=0.5):
    close = start + np.arange(periods) * step
    idx = pd.date_range("2026-01-01", periods=periods, freq="B")
    return pd.DataFrame({
        "Open": close, "High": close + 1, "Low": close - 1,
        "Close": close, "Volume": 1000,
    }, index=idx)


def test_market_snapshot_calculates_breadth_and_trend():
    snapshot = build_market_snapshot(
        {"^NSEI": _prices(), "AAA.NS": _prices(50), "BBB.NS": _prices(80, step=-0.2)}
    )
    assert snapshot["symbols_with_55plus_bars"] == 3
    assert snapshot["advancers_1d"] == 2
    assert snapshot["decliners_1d"] == 1
    assert snapshot["regime_rule_based"] in {
        "BULL TREND", "BEAR TREND", "HIGH VOLATILITY / MIXED", "SIDEWAYS / MIXED"
    }


def test_news_lexicon_sentiment_is_transparent_and_bounded():
    assert _lexicon_score("profit growth beats estimates") > 0
    assert _lexicon_score("fraud probe losses warning") < 0
    assert -1 <= _lexicon_score("market RBI") <= 1


def test_empty_snapshot_reports_missing_data_not_fake_neutral():
    snapshot = build_market_snapshot({})
    assert snapshot["symbols_with_55plus_bars"] == 0
    assert snapshot["regime_rule_based"] == "MIXED / SIDEWAYS"
    assert snapshot["above_sma20_ratio"] is None
