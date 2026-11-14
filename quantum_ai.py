"""Small CPU-only quantum-circuit simulator for experimental market classification.

This is a genuine state-vector circuit simulator (4 qubits), not quantum hardware.
It builds a fidelity kernel from angle-encoded OHLC features and performs a
chronological kernel-ridge classification. Predictions are experimental and
must be compared with a classical baseline before any trading use.
"""
from __future__ import annotations

from typing import Any
import numpy as np
import pandas as pd


N_QUBITS = 4
DIM = 2 ** N_QUBITS


def _clean_close(frame: pd.DataFrame) -> pd.Series:
    if frame is None or frame.empty or "Close" not in frame.columns:
        return pd.Series(dtype=float)
    close = pd.to_numeric(frame["Close"], errors="coerce").dropna().astype(float)
    return close[~close.index.duplicated(keep="last")].sort_index()


def _feature_rows(close: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    returns = close.pct_change()
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    momentum5 = close.pct_change(5)
    momentum20 = close.pct_change(20)
    vol20 = returns.rolling(20).std()
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = -delta.clip(upper=0).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    features = pd.concat([
        (close / sma20 - 1).rename("sma20_gap"),
        (close / sma50 - 1).rename("sma50_gap"),
        momentum5.rename("momentum5"),
        momentum20.rename("momentum20"),
    ], axis=1)
    # Future five-session return labels: +1 up, -1 down, 0 neutral.
    future_return = close.shift(-5) / close - 1
    labels = pd.Series(np.where(future_return > 0.01, 1, np.where(future_return < -0.01, -1, 0)), index=close.index)
    valid = features.notna().all(axis=1) & vol20.notna() & rsi.notna() & future_return.notna()
    # Use RSI and volatility as bounded stabilising transforms in feature scaling.
    x = features.loc[valid].to_numpy(dtype=float)
    x = np.column_stack([x, (rsi.loc[valid].to_numpy() - 50) / 50, vol20.loc[valid].to_numpy() * 10])
    y = labels.loc[valid].to_numpy(dtype=int)
    return x, y


def _normalize(x: np.ndarray, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    return np.clip((x - mean) / np.maximum(std, 1e-6), -2.0, 2.0)


def _apply_single(state: np.ndarray, qubit: int, gate: np.ndarray) -> np.ndarray:
    out = state.copy()
    bit = 1 << qubit
    for base in range(DIM):
        if not base & bit:
            i0, i1 = base, base | bit
            a, b = state[i0], state[i1]
            out[i0] = gate[0, 0] * a + gate[0, 1] * b
            out[i1] = gate[1, 0] * a + gate[1, 1] * b
    return out


def _cnot(state: np.ndarray, control: int, target: int) -> np.ndarray:
    out = state.copy()
    cb, tb = 1 << control, 1 << target
    for i in range(DIM):
        if i & cb and not i & tb:
            j = i | tb
            out[i], out[j] = state[j], state[i]
    return out


def _quantum_state(features: np.ndarray) -> np.ndarray:
    """Four-qubit angle-embedding circuit with ring entanglement."""
    state = np.zeros(DIM, dtype=np.complex128)
    state[0] = 1.0
    for q, value in enumerate(features[:N_QUBITS]):
        theta = float(value) * np.pi / 2
        rx = np.array([[np.cos(theta / 2), -1j * np.sin(theta / 2)],
                       [-1j * np.sin(theta / 2), np.cos(theta / 2)]], dtype=np.complex128)
        rz = np.array([[np.exp(-1j * theta / 2), 0],
                       [0, np.exp(1j * theta / 2)]], dtype=np.complex128)
        state = _apply_single(state, q, rx)
        state = _apply_single(state, q, rz)
    for q in range(N_QUBITS):
        state = _cnot(state, q, (q + 1) % N_QUBITS)
    return state


def _kernel(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    states_a = [_quantum_state(row) for row in a]
    states_b = [_quantum_state(row) for row in b]
    return np.asarray([[abs(np.vdot(sa, sb)) ** 2 for sb in states_b] for sa in states_a], dtype=float)


def analyze_quantum_market(price_map: dict[str, pd.DataFrame] | None, max_train: int = 240) -> dict[str, Any]:
    """Train on past labelled returns and classify the latest bar for each symbol."""
    price_map = price_map or {}
    datasets = []
    latest = {}
    for symbol, frame in price_map.items():
        close = _clean_close(frame)
        if len(close) < 85:
            continue
        x, y = _feature_rows(close)
        if len(x) < 25:
            continue
        latest_x, _ = _feature_rows(close.iloc[:-5].append(close.iloc[-5:])) if False else (None, None)
        # The last row has no known future label; construct its feature vector directly.
        returns = close.pct_change()
        sma20, sma50 = close.rolling(20).mean(), close.rolling(50).mean()
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = -delta.clip(upper=0).rolling(14).mean()
        rsi = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
        vol = returns.rolling(20).std()
        row = np.array([
            close.iloc[-1] / sma20.iloc[-1] - 1,
            close.iloc[-1] / sma50.iloc[-1] - 1,
            close.pct_change(5).iloc[-1],
            close.pct_change(20).iloc[-1],
            (rsi.iloc[-1] - 50) / 50,
            vol.iloc[-1] * 10,
        ], dtype=float)
        if np.isfinite(row).all():
            latest[str(symbol)] = row
        # Leave the most recent 5 bars out of training to avoid future-label overlap.
        datasets.append((str(symbol), x[:-5], y[:-5]))
    if not datasets or not latest:
        return {"status": "INSUFFICIENT_DATA", "engine": "4-qubit state-vector simulator", "message": "At least 85 valid daily bars per symbol are required."}
    X = np.vstack([x for _, x, _ in datasets if len(x)])
    Y = np.concatenate([y for _, x, y in datasets if len(x)])
    if len(X) < 40:
        return {"status": "INSUFFICIENT_TRAINING_DATA", "training_rows": int(len(X)), "engine": "4-qubit state-vector simulator"}
    # Deterministic evenly spaced sample bounds CPU cost and is reproducible.
    if len(X) > max_train:
        idx = np.linspace(0, len(X) - 1, max_train, dtype=int)
        X, Y = X[idx], Y[idx]
    mean, std = X.mean(axis=0), X.std(axis=0)
    Xn = _normalize(X, mean, std)
    labels = np.unique(Y)
    if len(labels) < 2:
        return {"status": "INSUFFICIENT_CLASS_VARIETY", "training_rows": int(len(X)), "engine": "4-qubit state-vector simulator"}
    K = _kernel(Xn, Xn)
    alpha = np.linalg.solve(K + 0.15 * np.eye(len(K)), np.eye(len(K)))
    predictions = []
    for symbol, raw in latest.items():
        q = _normalize(raw.reshape(1, -1), mean, std)
        k = _kernel(q, Xn)
        scores = (k @ alpha).ravel()
        class_scores = {int(label): float(scores[Y == label].mean()) for label in labels}
        # Kernel ridge score is a similarity-weighted experimental class score.
        predicted = max(class_scores, key=class_scores.get)
        ordered = sorted(class_scores.values(), reverse=True)
        margin = ordered[0] - ordered[1] if len(ordered) > 1 else 0.0
        predictions.append({
            "symbol": symbol, "quantum_class": "BULLISH" if predicted == 1 else "BEARISH" if predicted == -1 else "NEUTRAL",
            "class_scores": {str(k): round(v, 5) for k, v in class_scores.items()},
            "score_margin": round(float(margin), 5),
        })
    counts = pd.Series([p["quantum_class"] for p in predictions]).value_counts().to_dict()
    return {
        "status": "EXPERIMENTAL_RESULT", "engine": "4-qubit state-vector quantum-circuit simulator (NumPy)",
        "hardware": "Classical CPU simulation; no quantum hardware used",
        "training_rows": int(len(X)), "symbols_analyzed": len(predictions),
        "market_class_counts": counts, "predictions": predictions[:200],
        "warning": "Research-only quantum-kernel experiment. Not a validated trading edge, not a calibrated probability, and not a BUY/SELL instruction. Compare against classical baselines and walk-forward backtests.",
    }
