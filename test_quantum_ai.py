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
