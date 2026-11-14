import numpy as np
import pandas as pd

from quantum_ai import _quantum_state, analyze_quantum_market


def test_four_qubit_state_is_normalized():
    state = _quantum_state(np.array([0.1, -0.2, 0.4, 0.8]))
    assert state.shape == (16,)
    assert np.isclose(np.vdot(state, state).real, 1.0)


def test_quantum_engine_reports_insufficient_data_without_fabricating_signal():
    result = analyze_quantum_market({
        "SHORT.NS": pd.DataFrame({"Close": np.arange(20) + 100.0})
    })
    assert result["status"] == "INSUFFICIENT_DATA"
    assert "predictions" not in result


def test_quantum_and_classical_kernel_validation_return_class_labels():
    from quantum_ai import _kernel_scores

    train_x = np.array([
        [-0.8, -0.5, -0.4, -0.2],
        [-0.6, -0.4, -0.3, -0.1],
        [0.6, 0.4, 0.3, 0.1],
        [0.8, 0.5, 0.4, 0.2],
    ])
    train_y = np.array([-1, -1, 1, 1])
    test_x = np.array([[-0.7, -0.3, -0.2, -0.1], [0.7, 0.3, 0.2, 0.1]])
    for kind in ("quantum", "classical_rbf"):
        predicted = _kernel_scores(train_x, train_y, test_x, kind)
        assert predicted.shape == (2,)
        assert set(predicted).issubset({-1, 1})


def test_quantum_report_includes_holdout_and_crt_context():
    from quantum_ai import analyze_quantum_market

    index = pd.date_range("2024-01-01", periods=150, freq="B")
    close = pd.Series(100 * np.cumprod(1 + 0.001 + 0.01 * np.sin(np.arange(150) / 5)), index=index)
    prices = pd.DataFrame({
        "Open": close, "High": close * 1.01, "Low": close * 0.99,
        "Close": close, "Volume": 100000,
    }, index=index)
    daily = pd.DataFrame([{"Symbol": "TEST.NS", "Setup": "BUY", "Entry": 110.0, "SL": 105.0}])
    mtf = pd.DataFrame([
        {"Symbol": "TEST.NS", "CRT Pair": pair, "Signal": "WAIT"}
        for pair in ("Monthly→Daily", "Weekly→4H", "Daily→1H", "4H→5m", "1H→5m")
    ])
    result = analyze_quantum_market({"TEST.NS": prices}, daily, mtf, max_train=80)
    assert result["status"] in {"EXPERIMENTAL_RESULT", "INSUFFICIENT_CLASS_VARIETY"}
    if result["status"] == "EXPERIMENTAL_RESULT":
        assert "validation" in result
        assert result["predictions"][0]["crt_daily_context"]["Setup"] == "BUY"
        assert len(result["predictions"][0]["crt_five_timeframe_context"]) == 5
