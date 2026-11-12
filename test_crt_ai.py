import pandas as pd
from crt_ai import FEATURES, features_from_signal, train_crt_model

def test_signal_feature_schema():
    signal = {"Bias":"Bullish","Entry":22000,"SL":21800,"Target (M1 Monthly H/L)":22400,
        "M1 High":22500,"M1 Low":21500,"Sweep Candle Low":21400,"Sweep Candle High":22100,
        "CHoCH Reference Level":21900,"Zone Low":21900,"Zone High":22000,
        "Entry Zone Type":"FVG","Entry Date":"2025-05-15"}
    frame = features_from_signal(signal)
    assert list(frame.columns) == FEATURES
    assert frame.loc[0,"direction_long"] == 1.0
    assert frame.loc[0,"zone_fvg"] == 1.0
    assert frame.loc[0,"stop_distance_pct"] > 0

def test_small_sample_is_not_scored():
    trades = pd.DataFrame([{"Outcome":"WIN","Entry Date":"2024-01-01","Direction":"LONG",
        "Entry Reference":100,"Stop Loss":95,"Target":110,"Entry Zone":"FVG","Net P&L":100}])
    result = train_crt_model(trades)
    assert result.model is None
    assert result.report["status"] == "insufficient_data"

from crt_ai import _zones


def test_zone_flags_do_not_overlap():
    flags = _zones("IFVG+BOB")
    assert flags == {"zone_fvg": 0.0, "zone_ifvg": 1.0, "zone_ob": 0.0, "zone_bob": 1.0}


def test_three_model_ensemble_trains_and_scores():
    rows = []
    for i in range(90):
        long_side = i % 2 == 0
        won = (i % 3 != 0)
        entry = 100.0 + (i % 11)
        rows.append({
            "Symbol": f"S{i % 7}", "Entry Date": (pd.Timestamp("2020-01-01") + pd.Timedelta(days=i * 7)).date().isoformat(),
            "Outcome": "WIN" if won else "LOSS", "Net P&L": 150.0 if won else -100.0,
            "Direction": "LONG" if long_side else "SHORT", "Entry Reference": entry,
            "Stop Loss": entry * (0.97 if long_side else 1.03),
            "Target": entry * (1.06 if long_side else 0.94),
            "Entry Zone": ["FVG", "IFVG", "OB", "BOB"][i % 4],
            "M1 Range %": 4.0 + (i % 5), "Sweep Depth %": 0.5 + (i % 4) / 10,
            "CHoCH Distance %": 0.4 + (i % 6) / 10, "Zone Width %": 0.2 + (i % 3) / 10,
        })
    result = train_crt_model(pd.DataFrame(rows))
    assert result.model is not None
    assert len(result.report["model_names"]) == 3
    assert set(result.report["individual_models"]) == set(result.report["model_names"])
    assert 0.0 <= result.report["accuracy"] <= 1.0
