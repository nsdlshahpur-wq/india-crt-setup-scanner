from crt_copilot import INDEXES, PROVIDERS, run_copilot


def test_copilot_has_five_independent_ai_providers():
    assert len(PROVIDERS) == 5
    assert set(PROVIDERS) == {"Gemini", "Groq", "Mistral", "OpenRouter", "Cloudflare"}


def test_market_pulse_covers_benchmarks_vix_and_sectors():
    assert "NIFTY 50" in INDEXES
    assert "BANK NIFTY" in INDEXES
    assert "SENSEX" in INDEXES
    assert "INDIA VIX" in INDEXES
    assert "NIFTY IT" in INDEXES


def test_copilot_without_keys_returns_safe_provider_status_without_network():
    result = run_copilot("Analyse market", "No market data", {})
    assert result["success_count"] == 0
    assert result["configured_count"] == 0
    assert len(result["providers"]) == 5
    assert all(item["status"] == "not_configured" for item in result["providers"].values())
