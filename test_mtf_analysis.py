"""Tests for the revised CRT -> 15M CISD -> 5M entry architecture."""
from mtf_analysis import CRT_SPECS, ENTRY_SPECS, PAIR_SPECS


def test_crt_is_detected_only_on_higher_timeframes():
    assert [item["CRT"] for item in CRT_SPECS] == ["1H", "4H", "Daily", "Weekly"]
    assert all(item["CRT"] not in {"5M", "15M"} for item in CRT_SPECS)


def test_15m_and_5m_are_entry_timeframes_only():
    assert set(ENTRY_SPECS) == {"15M", "5M"}
    assert PAIR_SPECS == CRT_SPECS


def test_crt_and_entry_timeframes_are_not_mixed():
    for spec in CRT_SPECS:
        assert "interval" in spec
        assert "duration" in spec
    assert ENTRY_SPECS["15M"]["interval"] == "15m"
    assert ENTRY_SPECS["5M"]["interval"] == "5m"
