"""Experimental quantum-kernel market research engine.

Uses a four-qubit state-vector simulator on a classical CPU. It is not quantum
hardware and its class scores are not calibrated probabilities or trade advice.
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


def _indicators(close: pd.Series) -> tuple[np.ndarray, dict[str, float]]:
    returns = close.pct_change()
    sma20, sma50 = close.rolling(20).mean(), close.rolling(50).mean()
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = -delta.clip(upper=0).rolling(14).mean()
    rsi_series = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    vol_series = returns.rolling(20).std()
    row = np.array([
        close.iloc[-1] / sma20.iloc[-1] - 1,
        close.iloc[-1] / sma50.iloc[-1] - 1,
        close.pct_change(5).iloc[-1],
        close.pct_change(20).iloc[-1],
        (rsi_series.iloc[-1] - 50) / 50,
        vol_series.iloc[-1] * 10,
    ], dtype=float)
    info = {
        "last_close": float(close.iloc[-1]),
        "return_5d_pct": float(close.pct_change(5).iloc[-1] * 100),
        "return_20d_pct": float(close.pct_change(20).iloc[-1] * 100),
        "rsi14": float(rsi_series.iloc[-1]),
        "volatility_20d_pct": float(vol_series.iloc[-1] * np.sqrt(252) * 100),
        "above_sma20": bool(close.iloc[-1] > sma20.iloc[-1]),
        "above_sma50": bool(close.iloc[-1] > sma50.iloc[-1]),
    }
    return row, info


def _feature_rows(close: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    returns = close.pct_change()
    sma20, sma50 = close.rolling(20).mean(), close.rolling(50).mean()
    momentum5, momentum20 = close.pct_change(5), close.pct_change(20)
    vol20 = returns.rolling(20).std()
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = -delta.clip(upper=0).rolling(14).mean()
    rsi = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    features = pd.concat([
        (close / sma20 - 1).rename("sma20_gap"),
        (close / sma50 - 1).rename("sma50_gap"),
        momentum5.rename("momentum5"),
        momentum20.rename("momentum20"),
    ], axis=1)
    future_return = close.shift(-5) / close - 1
    labels = pd.Series(np.where(future_return > 0.01, 1, np.where(future_return < -0.01, -1, 0)), index=close.index)
    valid = features.notna().all(axis=1) & vol20.notna() & rsi.notna() & future_return.notna()
    x = features.loc[valid].to_numpy(dtype=float)
    x = np.column_stack([x, (rsi.loc[valid].to_numpy() - 50) / 50, vol20.loc[valid].to_numpy() * 10])
    return x, labels.loc[valid].to_numpy(dtype=int)


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


def _kernel_scores(train_x: np.ndarray, train_y: np.ndarray, test_x: np.ndarray, kind: str) -> np.ndarray:
    if kind == "quantum":
        k_train, k_test = _kernel(train_x, train_x), _kernel(test_x, train_x)
    else:
        # Classical RBF kernel baseline with the same ridge regularisation.
        d_train = np.maximum(0, (train_x ** 2).sum(1)[:, None] + (train_x ** 2).sum(1)[None, :] - 2 * train_x @ train_x.T)
        d_test = np.maximum(0, (test_x ** 2).sum(1)[:, None] + (train_x ** 2).sum(1)[None, :] - 2 * test_x @ train_x.T)
        gamma = 1.0 / max(train_x.shape[1], 1)
        k_train, k_test = np.exp(-gamma * d_train), np.exp(-gamma * d_test)
    classes = np.unique(train_y)
    targets = np.column_stack([(train_y == c).astype(float) for c in classes])
    weights = np.linalg.solve(k_train + 0.15 * np.eye(len(k_train)), targets)
    scores = k_test @ weights
    return classes[np.argmax(scores, axis=1)]


def analyze_quantum_market(
    price_map: dict[str, pd.DataFrame] | None,
    daily_results: pd.DataFrame | None = None,
    mtf_results: pd.DataFrame | None = None,
    max_train: int = 180,
) -> dict[str, Any]:
    """Compare quantum and classical kernels, then classify current symbol snapshots."""
    price_map = price_map or {}
    datasets, latest = [], {}
    for symbol, frame in price_map.items():
        close = _clean_close(frame)
        if len(close) < 85:
            continue
        x, y = _feature_rows(close)
        if len(x) < 25:
            continue
        raw, info = _indicators(close)
        if np.isfinite(raw).all():
            latest[str(symbol)] = (raw, info)
        # Latest five bars are excluded because their five-day labels overlap current data.
        datasets.append((str(symbol), x[:-5], y[:-5]))
    datasets = [(s, x, y) for s, x, y in datasets if len(x)]
    if not datasets or not latest:
        return {"status": "INSUFFICIENT_DATA", "engine": "4-qubit state-vector simulator", "message": "Run the Daily market scan first; at least 85 valid daily bars per symbol are required."}
    X = np.vstack([x for _, x, _ in datasets])
    Y = np.concatenate([y for _, _, y in datasets])
    if len(X) < 50:
        return {"status": "INSUFFICIENT_TRAINING_DATA", "training_rows": int(len(X)), "engine": "4-qubit state-vector simulator"}
    if len(X) > max_train:
        idx = np.linspace(0, len(X) - 1, max_train, dtype=int)
        X, Y = X[idx], Y[idx]
    # Chronological holdout: last 20% is unseen by the training kernel.
    split = max(30, int(len(X) * 0.8))
    split = min(split, len(X) - 10)
    mean, std = X[:split].mean(axis=0), X[:split].std(axis=0)
    train_x, test_x = _normalize(X[:split], mean, std), _normalize(X[split:], mean, std)
    train_y, test_y = Y[:split], Y[split:]
    validation = {}
    if len(np.unique(train_y)) >= 2 and len(test_y):
        for kind in ("quantum", "classical_rbf"):
            pred = _kernel_scores(train_x, train_y, test_x, kind)
            validation[kind] = {
                "accuracy_pct": round(float(np.mean(pred == test_y) * 100), 2),
                "test_rows": int(len(test_y)),
            }
    else:
        validation = {"status": "INSUFFICIENT_CLASS_VARIETY"}
    # Final model uses all sampled historical rows.
    mean, std = X.mean(axis=0), X.std(axis=0)
    Xn = _normalize(X, mean, std)
    labels = np.unique(Y)
    if len(labels) < 2:
        return {"status": "INSUFFICIENT_CLASS_VARIETY", "training_rows": int(len(X)), "engine": "4-qubit state-vector simulator"}
    K = _kernel(Xn, Xn)
    targets = np.column_stack([(Y == c).astype(float) for c in labels])
    weights = np.linalg.solve(K + 0.15 * np.eye(len(K)), targets)
    predictions = []
    for symbol, (raw, info) in latest.items():
        q = _normalize(raw.reshape(1, -1), mean, std)
        scores = (_kernel(q, Xn) @ weights).ravel()
        predicted = int(labels[int(np.argmax(scores))])
        row = {"symbol": symbol, **info,
               "quantum_class": "BULLISH" if predicted == 1 else "BEARISH" if predicted == -1 else "NEUTRAL",
               "class_scores": {str(int(label)): round(float(score), 5) for label, score in zip(labels, scores)}}
        predictions.append(row)
    predictions.sort(key=lambda p: p["return_20d_pct"], reverse=True)
    by_symbol = {str(r.get("Symbol")): r for r in daily_results.to_dict("records")} if isinstance(daily_results, pd.DataFrame) and not daily_results.empty and "Symbol" in daily_results.columns else {}
    mtf_by_symbol: dict[str, list[dict[str, Any]]] = {}
    if isinstance(mtf_results, pd.DataFrame) and not mtf_results.empty and "Symbol" in mtf_results.columns:
        for symbol, group in mtf_results.groupby("Symbol"):
            cols = [c for c in ("CRT Pair", "Signal", "HTF Bias", "HTF Liquidity", "LTF MSS", "Entry Zone", "Retest Zone", "Entry Price", "Stop Loss", "Target", "Entry Status", "Alignment") if c in group.columns]
            mtf_by_symbol[str(symbol)] = group[cols].head(5).to_dict("records")
    enriched = []
    for p in predictions:
        item = dict(p)
        daily = by_symbol.get(p["symbol"], {})
        item["crt_daily_context"] = {k: daily.get(k) for k in ("Setup", "Bias", "Entry", "SL", "T1 (2R)", "Target (M1 Monthly H/L)", "Entry Status", "Target Status") if k in daily}
        item["crt_five_timeframe_context"] = mtf_by_symbol.get(p["symbol"], [])
        enriched.append(item)
    counts = pd.Series([p["quantum_class"] for p in predictions]).value_counts().to_dict()
    return {
        "status": "EXPERIMENTAL_RESULT",
        "engine": "4-qubit state-vector quantum-circuit simulator (NumPy)",
        "hardware": "Classical CPU simulation; no quantum hardware used",
        "training_rows": int(len(X)), "symbols_analyzed": len(predictions),
        "validation": validation,
        "market_class_counts": counts,
        "strongest_20d": [{"symbol": p["symbol"], "return_20d_pct": round(p["return_20d_pct"], 2), "class": p["quantum_class"]} for p in predictions[:10]],
        "weakest_20d": [{"symbol": p["symbol"], "return_20d_pct": round(p["return_20d_pct"], 2), "class": p["quantum_class"]} for p in predictions[-10:][::-1]],
        "predictions": enriched[:200],
        "timeframe_note": "Five CRT pairs are attached from the current MTF screener if it has been run; the quantum kernel itself is trained on Daily OHLC only, not separate intraday quantum circuits.",
        "warning": "Research-only quantum-kernel experiment. Class scores are not probabilities or BUY/SELL instructions. Entry, stop and target are copied only from existing CRT scanner records. Walk-forward holdout is a small research check, not proof of a trading edge.",
    }
