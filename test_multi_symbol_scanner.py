"""Regression tests for the five-pair multi-symbol CRT scanner."""
import pandas as pd
import multi_symbol_scanner as multi


def test_scan_symbol_delegates_to_all_five_configured_pairs(monkeypatch):
    expected = pd.DataFrame([
        {"HTF → LTF": spec["HTF"] + " → " + spec["LTF"], "Signal": "WAIT"}
        for spec in multi.PAIR_SPECS
    ])
    monkeypatch.setattr(multi, "analyze_mtf_symbol", lambda symbol: (expected, {}))
    frame, errors = multi.scan_symbol("RELIANCE.NS")
    assert len(frame) == 5
    assert list(frame["HTF → LTF"]) == [x["HTF"] + " → " + x["LTF"] for x in multi.PAIR_SPECS]
    assert errors == {}


def test_scan_symbols_combines_each_symbol_and_pair(monkeypatch):
    def fake(symbol):
        return pd.DataFrame([
            {"HTF → LTF": "Monthly → Daily", "Signal": "WAIT"},
            {"HTF → LTF": "Weekly → 4H", "Signal": "WAIT"},
        ]), {}
    monkeypatch.setattr(multi, "analyze_mtf_symbol", fake)
    frame, errors = multi.scan_symbols(["RELIANCE.NS", "TCS.NS", "RELIANCE.NS"])
    assert len(frame) == 4
    assert frame["Symbol"].value_counts().to_dict() == {"RELIANCE.NS": 2, "TCS.NS": 2}
    assert errors == {}


def test_scan_symbols_collects_pair_errors(monkeypatch):
    def fake(symbol):
        return pd.DataFrame([{"HTF → LTF": "Monthly → Daily", "Signal": "WAIT"}]), {
            "Weekly → 4H": "No lower timeframe data"
        }
    monkeypatch.setattr(multi, "analyze_mtf_symbol", fake)
    frame, errors = multi.scan_symbols(["ABC.NS"])
    assert len(frame) == 1
    assert errors == {"ABC.NS | Weekly → 4H": "No lower timeframe data"}


def test_scan_symbols_processes_entire_universe_and_reports_progress(monkeypatch):
    seen = []
    progress = []
    def fake(symbol):
        seen.append(symbol)
        return pd.DataFrame(), {}
    monkeypatch.setattr(multi, "analyze_mtf_symbol", fake)
    multi.scan_symbols(
        [f"S{i}" for i in range(12)],
        progress_callback=lambda done, total, symbol: progress.append((done, total, symbol)),
    )
    assert len(seen) == 12
    assert progress[-1] == (12, 12, "S11")
