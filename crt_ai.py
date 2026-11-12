"""Multi-model Daily CRT outcome ensemble.

Models learn only from completed historical trades. Inputs are restricted to
information available on the entry-confirmation date. Evaluation is chronological;
the final ensemble is refit on all eligible labels after holdout evaluation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.metrics import accuracy_score, balanced_accuracy_score, brier_score_loss

FEATURES = [
    "direction_long", "stop_distance_pct", "target_distance_pct", "reward_risk",
    "zone_fvg", "zone_ifvg", "zone_ob", "zone_bob", "m1_range_pct",
    "sweep_depth_pct", "choch_distance_pct", "zone_width_pct",
    "entry_month_sin", "entry_month_cos",
]


def _num(row: Any, key: str, default: float = np.nan) -> float:
    try:
        value = float(row.get(key, default))
        return value if np.isfinite(value) else default
    except (TypeError, ValueError, AttributeError):
        return default


def _zones(value: Any) -> dict[str, float]:
    tokens = {part.strip() for part in str(value or "").upper().split("+")}
    return {
        "zone_fvg": float("FVG" in tokens), "zone_ifvg": float("IFVG" in tokens),
        "zone_ob": float("OB" in tokens), "zone_bob": float("BOB" in tokens),
    }


def _month(value: Any) -> tuple[float, float]:
    try:
        month = pd.Timestamp(value).month
    except (TypeError, ValueError):
        month = 1
    angle = 2.0 * np.pi * (month - 1) / 12.0
    return float(np.sin(angle)), float(np.cos(angle))


def features_from_trade(row: Any) -> dict[str, float]:
    """Only fields known at entry; no exit/outcome information enters features."""
    entry = _num(row, "Entry Reference", _num(row, "Entry Fill"))
    stop, target = _num(row, "Stop Loss"), _num(row, "Target")
    base = max(abs(entry), 1e-9) if np.isfinite(entry) else np.nan
    stop_pct = abs(entry - stop) / base * 100 if np.isfinite(entry + stop) else np.nan
    target_pct = abs(target - entry) / base * 100 if np.isfinite(entry + target) else np.nan
    sin_m, cos_m = _month(row.get("Entry Date"))
    result = {
        "direction_long": float(str(row.get("Direction", "")).upper() in {"LONG", "BUY"}),
        "stop_distance_pct": stop_pct, "target_distance_pct": target_pct,
        "reward_risk": target_pct / stop_pct if np.isfinite(stop_pct) and stop_pct > 0 and np.isfinite(target_pct) else np.nan,
        "m1_range_pct": _num(row, "M1 Range %"), "sweep_depth_pct": _num(row, "Sweep Depth %"),
        "choch_distance_pct": _num(row, "CHoCH Distance %"), "zone_width_pct": _num(row, "Zone Width %"),
        "entry_month_sin": sin_m, "entry_month_cos": cos_m,
    }
    result.update(_zones(row.get("Entry Zone", "")))
    return result


def features_from_signal(signal: dict[str, Any]) -> pd.DataFrame:
    entry, stop = _num(signal, "Entry"), _num(signal, "SL")
    target = _num(signal, "Target (M1 Monthly H/L)")
    base = max(abs(entry), 1e-9) if np.isfinite(entry) else np.nan
    m1h, m1l = _num(signal, "M1 High"), _num(signal, "M1 Low")
    sweep_l, sweep_h = _num(signal, "Sweep Candle Low"), _num(signal, "Sweep Candle High")
    choch = _num(signal, "CHoCH Reference Level")
    zl, zh = _num(signal, "Zone Low"), _num(signal, "Zone High")
    bullish = str(signal.get("Bias", "")).lower() == "bullish"
    sweep_depth = (
        abs(sweep_l - m1l) / base * 100 if bullish and np.isfinite(sweep_l + m1l)
        else abs(sweep_h - m1h) / base * 100 if not bullish and np.isfinite(sweep_h + m1h)
        else np.nan
    )
    stop_pct = abs(entry - stop) / base * 100 if np.isfinite(entry + stop) else np.nan
    target_pct = abs(target - entry) / base * 100 if np.isfinite(entry + target) else np.nan
    sin_m, cos_m = _month(signal.get("Entry Date", signal.get("Last Candle")))
    values = {
        "direction_long": float(bullish), "stop_distance_pct": stop_pct,
        "target_distance_pct": target_pct,
        "reward_risk": target_pct / stop_pct if np.isfinite(stop_pct) and stop_pct > 0 and np.isfinite(target_pct) else np.nan,
        "m1_range_pct": (m1h - m1l) / base * 100 if np.isfinite(m1h + m1l) else np.nan,
        "sweep_depth_pct": sweep_depth,
        "choch_distance_pct": abs(entry - choch) / base * 100 if np.isfinite(entry + choch) else np.nan,
        "zone_width_pct": abs(zh - zl) / base * 100 if np.isfinite(zh + zl) else np.nan,
        "entry_month_sin": sin_m, "entry_month_cos": cos_m,
    }
    values.update(_zones(signal.get("Entry Zone Type", "")))
    return pd.DataFrame([{key: values.get(key, np.nan) for key in FEATURES}], columns=FEATURES)


def _new_models() -> dict[str, Any]:
    return {
        "Random Forest": RandomForestClassifier(
            n_estimators=350, max_depth=5, min_samples_leaf=3,
            class_weight="balanced_subsample", random_state=42, n_jobs=-1,
        ),
        "Extra Trees": ExtraTreesClassifier(
            n_estimators=350, max_depth=5, min_samples_leaf=3,
            class_weight="balanced", random_state=43, n_jobs=-1,
        ),
        "Gradient Boosting": HistGradientBoostingClassifier(
            max_iter=180, max_leaf_nodes=15, learning_rate=0.06,
            l2_regularization=1.0, random_state=44,
        ),
    }


def _fit_matrix(train_x: pd.DataFrame, other_x: pd.DataFrame | None = None):
    medians = train_x.median(numeric_only=True).fillna(0.0)
    fitted_train = train_x.replace([np.inf, -np.inf], np.nan).fillna(medians).fillna(0.0)
    if other_x is None:
        return fitted_train, medians
    fitted_other = other_x.replace([np.inf, -np.inf], np.nan).fillna(medians).fillna(0.0)
    return fitted_train, fitted_other, medians


@dataclass
class CRTEnsemble:
    models: dict[str, Any]
    medians: pd.Series

    @property
    def classes_(self):
        return np.array([0, 1])

    def predict_proba(self, x: pd.DataFrame) -> np.ndarray:
        clean = x.reindex(columns=FEATURES).replace([np.inf, -np.inf], np.nan)
        clean = clean.fillna(self.medians).fillna(0.0)
        predictions = []
        for model in self.models.values():
            class_index = list(model.classes_).index(1)
            predictions.append(model.predict_proba(clean)[:, class_index])
        positive = np.mean(predictions, axis=0)
        return np.column_stack([1.0 - positive, positive])

    def individual_probabilities(self, x: pd.DataFrame) -> dict[str, float]:
        clean = x.reindex(columns=FEATURES).replace([np.inf, -np.inf], np.nan)
        clean = clean.fillna(self.medians).fillna(0.0)
        return {
            name: float(model.predict_proba(clean)[0, list(model.classes_).index(1)])
            for name, model in self.models.items()
        }


@dataclass
class CRTModelResult:
    model: CRTEnsemble | None
    report: dict[str, Any]
    eligible_trades: pd.DataFrame


def train_crt_model(trades: pd.DataFrame, min_samples: int = 45) -> CRTModelResult:
    """Chronological 75/25 holdout, then fit a 3-model soft-voting ensemble."""
    base = {
        "status": "insufficient_data", "sample_count": 0, "wins": 0, "losses": 0,
        "accuracy": None, "balanced_accuracy": None, "brier_score": None,
    }
    if trades is None or trades.empty or "Outcome" not in trades or "Entry Date" not in trades:
        return CRTModelResult(None, {**base, "message": "Historical CRT trade history is empty or incomplete."}, pd.DataFrame())
    frame = trades.copy()
    frame["Outcome"] = frame["Outcome"].astype(str).str.upper()
    frame = frame[frame["Outcome"].isin(["WIN", "LOSS"])].copy()
    if "Net P&L" in frame:
        frame["Net P&L"] = pd.to_numeric(frame["Net P&L"], errors="coerce")
        frame = frame[frame["Net P&L"].notna() & frame["Net P&L"].ne(0)].copy()
        frame["label"] = (frame["Net P&L"] > 0).astype(int)
    else:
        frame["label"] = (frame["Outcome"] == "WIN").astype(int)
    frame["Entry Date"] = pd.to_datetime(frame["Entry Date"], errors="coerce")
    sort_cols = ["Entry Date"] + (["Symbol"] if "Symbol" in frame else [])
    frame = frame.dropna(subset=["Entry Date"]).sort_values(sort_cols).reset_index(drop=True)
    if frame.empty:
        return CRTModelResult(None, {**base, "message": "No decisive closed WIN/LOSS trades with valid dates."}, frame)
    x = pd.DataFrame([features_from_trade(row) for _, row in frame.iterrows()], columns=FEATURES)
    y = frame["label"].astype(int)
    wins, losses = int(y.sum()), int((y == 0).sum())
    if len(frame) < min_samples or min(wins, losses) < 10:
        return CRTModelResult(None, {**base, "sample_count": len(frame), "wins": wins, "losses": losses,
            "message": f"Need at least {min_samples} decisive trades and 10 examples of each outcome."}, frame)
    split = min(max(int(len(frame) * 0.75), 20), len(frame) - 5)
    train_x, test_x, y_train, y_test = x.iloc[:split], x.iloc[split:], y.iloc[:split], y.iloc[split:]
    if y_train.nunique() < 2 or y_test.nunique() < 2:
        return CRTModelResult(None, {**base, "sample_count": len(frame), "wins": wins, "losses": losses,
            "message": "Both chronological train and test periods must contain WIN and LOSS examples."}, frame)
    fit_train, fit_test, _ = _fit_matrix(train_x, test_x)
    holdout_models = _new_models()
    individual_scores = {}
    holdout_probabilities = []
    for name, model in holdout_models.items():
        model.fit(fit_train, y_train)
        p = model.predict_proba(fit_test)[:, list(model.classes_).index(1)]
        holdout_probabilities.append(p)
        individual_scores[name] = {
            "accuracy": float(accuracy_score(y_test, (p >= 0.5).astype(int))),
            "brier_score": float(brier_score_loss(y_test, p)),
        }
    ensemble_p = np.mean(holdout_probabilities, axis=0)
    ensemble_pred = (ensemble_p >= 0.5).astype(int)
    full_x, medians = _fit_matrix(x)
    final_models = _new_models()
    for model in final_models.values():
        model.fit(full_x, y)
    rf = final_models["Random Forest"]
    importance = sorted(zip(FEATURES, rf.feature_importances_), key=lambda item: item[1], reverse=True)
    report = {
        "status": "ready", "sample_count": len(frame), "wins": wins, "losses": losses,
        "train_count": len(train_x), "test_count": len(test_x),
        "test_start": frame["Entry Date"].iloc[split].date().isoformat(),
        "test_end": frame["Entry Date"].iloc[-1].date().isoformat(),
        "accuracy": float(accuracy_score(y_test, ensemble_pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y_test, ensemble_pred)),
        "brier_score": float(brier_score_loss(y_test, ensemble_p)),
        "test_win_rate": float(y_test.mean()),
        "individual_models": individual_scores,
        "model_names": list(final_models.keys()),
        "feature_importance": [{"feature": k, "importance": float(v)} for k, v in importance],
        "label_definition": "Net P&L after modeled costs > 0; ambiguous/open trades excluded.",
        "ensemble_method": "Equal-weight soft voting of Random Forest, Extra Trees and Histogram Gradient Boosting.",
    }
    return CRTModelResult(CRTEnsemble(final_models, medians), report, frame)


def predict_crt_probability(model: CRTEnsemble, signal: dict[str, Any]) -> float:
    return float(model.predict_proba(features_from_signal(signal))[0, 1])


def score_crt_signals(model: CRTEnsemble, signals: pd.DataFrame) -> pd.DataFrame:
    """Add ensemble score only to fresh, completed Stage-3 CRT confirmations."""
    scored = signals.copy()
    scored["AI Success Probability %"] = np.nan
    scored["AI Model Agreement %"] = np.nan
    scored["AI Model Votes"] = ""
    for idx, row in scored.iterrows():
        if int(row.get("Stage", 0) or 0) != 3 or str(row.get("Setup", "")).upper() not in {"BUY", "SELL"}:
            continue
        signal = row.to_dict()
        x = features_from_signal(signal)
        probs = model.individual_probabilities(x)
        values = np.array(list(probs.values()), dtype=float)
        scored.at[idx, "AI Success Probability %"] = round(float(values.mean()) * 100.0, 1)
        scored.at[idx, "AI Model Agreement %"] = round(float(np.mean((values >= 0.5) == (values.mean() >= 0.5))) * 100.0, 1)
        scored.at[idx, "AI Model Votes"] = " | ".join(f"{name}: {value*100:.1f}%" for name, value in probs.items())
    return scored
