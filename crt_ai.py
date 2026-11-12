"""Daily CRT outcome model.

Learns only from completed historical CRT trades. Features are known on the
signal/entry date; exit labels are used only as targets. Chronological holdout
metrics are reported separately from the final all-history model.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, balanced_accuracy_score, brier_score_loss

FEATURES = ["direction_long", "stop_distance_pct", "target_distance_pct", "reward_risk",
            "zone_fvg", "zone_ifvg", "zone_ob", "zone_bob", "m1_range_pct",
            "sweep_depth_pct", "choch_distance_pct", "zone_width_pct",
            "entry_month_sin", "entry_month_cos"]

def _num(row: Any, key: str, default: float = np.nan) -> float:
    try:
        value = float(row.get(key, default))
        return value if np.isfinite(value) else default
    except (TypeError, ValueError, AttributeError):
        return default

def _zones(value: Any) -> dict[str, float]:
    # Zone types are emitted as '+'-joined tokens; exact matching avoids
    # treating IFVG as FVG or BOB as OB.
    zone_types = {part.strip() for part in str(value or "").upper().split("+")}
    return {"zone_fvg": float("FVG" in zone_types), "zone_ifvg": float("IFVG" in zone_types),
            "zone_ob": float("OB" in zone_types), "zone_bob": float("BOB" in zone_types)}

def _month(value: Any) -> tuple[float, float]:
    try:
        month = pd.Timestamp(value).month
    except (TypeError, ValueError):
        month = 1
    angle = 2.0 * np.pi * (month - 1) / 12.0
    return float(np.sin(angle)), float(np.cos(angle))

def features_from_trade(row: Any) -> dict[str, float]:
    """Only use fields available when the CRT entry was confirmed."""
    entry = _num(row, "Entry Reference", _num(row, "Entry Fill"))
    stop, target = _num(row, "Stop Loss"), _num(row, "Target")
    base = max(abs(entry), 1e-9) if np.isfinite(entry) else np.nan
    stop_pct = abs(entry - stop) / base * 100 if np.isfinite(entry + stop) else np.nan
    target_pct = abs(target - entry) / base * 100 if np.isfinite(entry + target) else np.nan
    sin_m, cos_m = _month(row.get("Entry Date"))
    out = {
        "direction_long": float(str(row.get("Direction", "")).upper() in {"LONG", "BUY"}),
        "stop_distance_pct": stop_pct, "target_distance_pct": target_pct,
        "reward_risk": target_pct / stop_pct if np.isfinite(stop_pct) and stop_pct > 0 and np.isfinite(target_pct) else np.nan,
        "m1_range_pct": _num(row, "M1 Range %"), "sweep_depth_pct": _num(row, "Sweep Depth %"),
        "choch_distance_pct": _num(row, "CHoCH Distance %"), "zone_width_pct": _num(row, "Zone Width %"),
        "entry_month_sin": sin_m, "entry_month_cos": cos_m,
    }
    out.update(_zones(row.get("Entry Zone", "")))
    return out

def features_from_signal(signal: dict[str, Any]) -> pd.DataFrame:
    """Build the same entry-time feature schema for a current scanner result."""
    entry, stop = _num(signal, "Entry"), _num(signal, "SL")
    target = _num(signal, "Target (M1 Monthly H/L)")
    base = max(abs(entry), 1e-9) if np.isfinite(entry) else np.nan
    m1h, m1l = _num(signal, "M1 High"), _num(signal, "M1 Low")
    sweep_l, sweep_h = _num(signal, "Sweep Candle Low"), _num(signal, "Sweep Candle High")
    choch = _num(signal, "CHoCH Reference Level")
    zl, zh = _num(signal, "Zone Low"), _num(signal, "Zone High")
    bullish = str(signal.get("Bias", "")).lower() == "bullish"
    sweep_depth = (abs(sweep_l - m1l) / base * 100 if bullish and np.isfinite(sweep_l + m1l)
                   else abs(sweep_h - m1h) / base * 100 if not bullish and np.isfinite(sweep_h + m1h)
                   else np.nan)
    stop_pct = abs(entry - stop) / base * 100 if np.isfinite(entry + stop) else np.nan
    target_pct = abs(target - entry) / base * 100 if np.isfinite(entry + target) else np.nan
    sin_m, cos_m = _month(signal.get("Entry Date"))
    out = {
        "direction_long": float(bullish), "stop_distance_pct": stop_pct,
        "target_distance_pct": target_pct,
        "reward_risk": target_pct / stop_pct if np.isfinite(stop_pct) and stop_pct > 0 and np.isfinite(target_pct) else np.nan,
        "m1_range_pct": (m1h - m1l) / base * 100 if np.isfinite(m1h + m1l) else np.nan,
        "sweep_depth_pct": sweep_depth,
        "choch_distance_pct": abs(entry - choch) / base * 100 if np.isfinite(entry + choch) else np.nan,
        "zone_width_pct": abs(zh - zl) / base * 100 if np.isfinite(zh + zl) else np.nan,
        "entry_month_sin": sin_m, "entry_month_cos": cos_m,
    }
    out.update(_zones(signal.get("Entry Zone Type", "")))
    return pd.DataFrame([{k: out.get(k, np.nan) for k in FEATURES}], columns=FEATURES)

@dataclass
class CRTModelResult:
    model: RandomForestClassifier | None
    report: dict[str, Any]
    eligible_trades: pd.DataFrame

def train_crt_model(trades: pd.DataFrame, min_samples: int = 30) -> CRTModelResult:
    """Evaluate on the latest chronological 25%, then fit final model on all labels."""
    base_report = {"status": "insufficient_data", "sample_count": 0, "wins": 0, "losses": 0,
                   "accuracy": None, "balanced_accuracy": None, "brier_score": None}
    if trades is None or trades.empty:
        return CRTModelResult(None, {**base_report, "message": "Historical CRT trade history is empty."}, pd.DataFrame())
    frame = trades.copy()
    if "Outcome" not in frame or "Entry Date" not in frame:
        return CRTModelResult(None, {**base_report, "message": "Trade history lacks Outcome or Entry Date."}, pd.DataFrame())
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
        return CRTModelResult(None, {**base_report, "message": "No decisive closed trades with valid dates."}, frame)
    x = pd.DataFrame([features_from_trade(row) for _, row in frame.iterrows()], columns=FEATURES)
    x = x.replace([np.inf, -np.inf], np.nan).fillna(x.median(numeric_only=True)).fillna(0.0)
    y = frame["label"].astype(int)
    wins, losses = int(y.sum()), int((y == 0).sum())
    if len(frame) < min_samples or min(wins, losses) < 8:
        return CRTModelResult(None, {**base_report, "sample_count": len(frame), "wins": wins, "losses": losses,
            "message": f"Need at least {min_samples} decisive trades and 8 examples of each outcome."}, frame)
    split = min(max(int(len(frame) * 0.75), 20), len(frame) - 5)
    x_train, x_test, y_train, y_test = x.iloc[:split], x.iloc[split:], y.iloc[:split], y.iloc[split:]
    if y_train.nunique() < 2 or y_test.nunique() < 2:
        return CRTModelResult(None, {**base_report, "sample_count": len(frame), "wins": wins, "losses": losses,
            "message": "Both chronological train and test periods must contain WIN and LOSS examples."}, frame)
    def new_model():
        return RandomForestClassifier(n_estimators=300, max_depth=4, min_samples_leaf=3,
            class_weight="balanced_subsample", random_state=42, n_jobs=-1)
    holdout = new_model()
    holdout.fit(x_train, y_train)
    positive_index = list(holdout.classes_).index(1)
    probabilities = holdout.predict_proba(x_test)[:, positive_index]
    predictions = (probabilities >= 0.5).astype(int)
    model = new_model()
    model.fit(x, y)
    importance = sorted(zip(FEATURES, model.feature_importances_), key=lambda item: item[1], reverse=True)
    report = {"status": "ready", "sample_count": len(frame), "wins": wins, "losses": losses,
        "train_count": len(x_train), "test_count": len(x_test),
        "test_start": frame["Entry Date"].iloc[split].date().isoformat(),
        "test_end": frame["Entry Date"].iloc[-1].date().isoformat(),
        "accuracy": float(accuracy_score(y_test, predictions)),
        "balanced_accuracy": float(balanced_accuracy_score(y_test, predictions)),
        "brier_score": float(brier_score_loss(y_test, probabilities)),
        "test_win_rate": float(y_test.mean()),
        "feature_importance": [{"feature": k, "importance": float(v)} for k, v in importance],
        "label_definition": "Net P&L after modeled costs > 0; ambiguous/open trades excluded."}
    return CRTModelResult(model, report, frame)

def predict_crt_probability(model: RandomForestClassifier, signal: dict[str, Any]) -> float:
    x = features_from_signal(signal).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    classes = list(model.classes_)
    return float(model.predict_proba(x)[0, classes.index(1)]) if 1 in classes else 0.0
