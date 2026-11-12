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
