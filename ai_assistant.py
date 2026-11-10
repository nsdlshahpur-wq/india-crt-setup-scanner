"""Optional LLM connectors for market-context explanation.

Only market/scanner information supplied by the dashboard is sent. No broker
credentials, account balances, orders or holdings are included automatically.
"""
from __future__ import annotations

import requests


def generate_market_answer(
    provider: str,
    api_key: str,
    prompt: str,
    market_context: str = "",
    model: str = "",
) -> str:
    if not api_key.strip():
        raise ValueError("API key is not configured in Streamlit secrets.")
    system_prompt = (
        "You are a cautious market research assistant. Analyse only the data included below. "
        "Do not invent live prices, news, indicators or broker data. Distinguish observed facts from "
        "hypotheses, state missing data, and never claim a trade is guaranteed. Do not place or suggest "
        "automatic orders. This is educational market information, not personalised investment advice. "
        "Respond in clear Hindi/Hinglish when the user writes in Hindi/Hinglish."
    )
    full_prompt = (
        f"{system_prompt}\n\nMARKET CONTEXT:\n{market_context[:18000]}\n\n"
        f"USER QUESTION:\n{prompt[:4000]}"
    )

    if provider == "Gemini":
        model_id = model.strip() or "gemini-3.5-flash-lite"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent"
        response = requests.post(
            url,
            params={"key": api_key},
            json={
                "contents": [{"parts": [{"text": full_prompt}]}],
                "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1800},
            },
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        candidates = data.get("candidates", [])
        if not candidates:
            raise RuntimeError("Gemini returned no answer. Check model access and free-tier quota.")
        parts = candidates[0].get("content", {}).get("parts", [])
        answer = "\n".join(part.get("text", "") for part in parts if part.get("text"))
        if not answer:
            raise RuntimeError("Gemini response did not contain text.")
        return answer

    if provider == "Groq":
        model_id = model.strip() or "openai/gpt-oss-20b"
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model_id,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"MARKET CONTEXT:\n{market_context[:18000]}\n\nUSER QUESTION:\n{prompt[:4000]}"},
                ],
                "temperature": 0.2,
                "max_tokens": 1800,
            },
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError("Groq returned no answer. Check model access and free-tier quota.")
        return str(choices[0].get("message", {}).get("content", "")).strip()

    raise ValueError("Unsupported AI provider. Choose Gemini or Groq.")
