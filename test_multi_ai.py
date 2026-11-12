import pandas as pd

from multi_ai import configured_providers, run_multi_ai_consensus


def test_provider_keys_are_optional_and_missing_keys_do_not_break_scan():
    configured = configured_providers({})
    assert set(configured) == {"Gemini", "Groq", "Mistral", "OpenRouter", "Cloudflare"}
    assert not any(configured.values())


def test_cloudflare_requires_both_token_and_account_id():
    assert not configured_providers({"CLOUDFLARE_API_TOKEN": "token"})["Cloudflare"]
    assert configured_providers({
        "CLOUDFLARE_API_TOKEN": "token",
        "CLOUDFLARE_ACCOUNT_ID": "account",
    })["Cloudflare"]


def test_no_confirmed_signals_never_calls_providers():
    frame = pd.DataFrame([{"Symbol": "RELIANCE.NS", "Setup": "Wait Retest", "Stage": 2}])
    result = run_multi_ai_consensus(frame, {})
    assert result["status"] == "no_signals"
    assert result["results"] == {}


def test_missing_api_keys_returns_setup_message_without_network_calls():
    frame = pd.DataFrame([{
        "Symbol": "RELIANCE.NS", "Setup": "BUY", "Stage": 3,
        "Bias": "Bullish", "Entry": 100.0, "SL": 95.0,
    }])
    result = run_multi_ai_consensus(frame, {})
    assert result["signals_sent"] == 1
    assert result["status"] == "partial"
    assert "API keys" in result["message"]
