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


def filter_strong_crt_setups(
    provider: str,
    api_key: str,
    candidates: list[dict],
    model: str = "",
) -> dict:
    """Ask the LLM to validate only the user's explicit CRT checklist.

    Stage 3 is a hard prerequisite produced by the scanner. The LLM may only
    keep or reject supplied symbols; it cannot invent symbols or add indicators.
    """
    import json
    import re

    if not candidates:
        return {"approved": [], "rejected": [], "summary": "No Stage 3 CRT candidates were supplied."}

    allowed = {str(row.get("Symbol", "")) for row in candidates}
    checklist = (
        "You are a strict Candle Range Theory (CRT) validation assistant. "
        "Use ONLY this checklist and supplied scanner evidence: "
        "(1) M1 previous monthly range, (2) M2 liquidity sweep beyond M1 high/low "
        "and close back inside the M1 range, (3) M3 daily CHoCH in the reclaim direction, "
        "(4) same-direction FVG formed after CHoCH, (5) retest of that FVG with a confirming "
        "close, (6) stop at the actual sweep candle low for bullish or high for bearish, "
        "(7) target at opposite M1 monthly liquidity. "
        "Do not use RSI, MACD, EMA, news, fundamentals, volume, IFVG, order blocks, "
        "or any other strategy/filter. Do not invent missing evidence. "
        "Only approve a row if Setup is BUY/SELL, Stage is 3, all required fields "
        "are present and the direction/levels are internally consistent. "
        "If evidence is missing or contradictory, reject and name the missing CRT field. "
        "Return ONLY valid JSON with keys approved (array of objects with Symbol, "
        "Direction, Reason), rejected (array of objects with Symbol, Reason), "
        "summary (string). Use only symbols in the supplied rows."
    )
    raw = generate_market_answer(
        provider,
        api_key,
        "Validate these scanner candidates against the exact CRT checklist. "
        "No new rules.\n\nCANDIDATES:\n" + json.dumps(candidates, ensure_ascii=False, default=str),
        market_context=checklist,
        model=model,
    )
    text = raw.strip()
    text = re.sub(r"^\x60{3}(?:json)?\\s*|\\s*\x60{3}$", "", text, flags=re.I)
    match = re.search(r"\\{.*\\}", text, flags=re.S)
    if not match:
        raise ValueError("AI did not return the required JSON result. Please retry.")
    parsed = json.loads(match.group(0))
    approved = []
    rejected = []
    for row in parsed.get("approved", []):
        symbol = str(row.get("Symbol", ""))
        source = next((item for item in candidates if str(item.get("Symbol", "")) == symbol), None)
        if source and symbol in allowed and int(source.get("Stage", 0)) == 3 and source.get("Setup") in {"BUY", "SELL"}:
            approved.append({"Symbol": symbol, "Direction": source["Setup"], "Reason": str(row.get("Reason", "CRT checklist passed"))})
    for row in parsed.get("rejected", []):
        symbol = str(row.get("Symbol", ""))
        if symbol in allowed:
            rejected.append({"Symbol": symbol, "Reason": str(row.get("Reason", "CRT evidence incomplete"))})
    return {
        "approved": approved,
        "rejected": rejected,
        "summary": str(parsed.get("summary", "AI CRT validation completed.")),
    }
