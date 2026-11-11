"""Optional LLM connectors for market-context explanation.

Only market/scanner information supplied by the dashboard is sent. No broker
credentials, account balances, orders or holdings are included automatically.
"""
from __future__ import annotations

import json
import re

import requests


class AIProviderError(RuntimeError):
    """Safe, actionable provider error with secrets removed."""


def _post_provider_json(
    provider: str,
    url: str,
    api_key: str,
    *,
    headers: dict | None = None,
    params: dict | None = None,
    payload: dict,
    timeout: int,
) -> dict:
    try:
        response = requests.post(
            url,
            headers=headers,
            params=params,
            json=payload,
            timeout=timeout,
        )
    except requests.Timeout:
        raise AIProviderError(
            f"{provider} request timed out after {timeout} seconds. Please retry."
        ) from None
    except requests.RequestException:
        raise AIProviderError(
            f"{provider} could not be reached. Check the app network/deployment and retry."
        ) from None

    try:
        data = response.json()
    except ValueError:
        data = {}

    if not response.ok:
        error = data.get("error", {}) if isinstance(data, dict) else {}
        if isinstance(error, dict):
            message = str(error.get("message") or error.get("status") or "")
            code = str(error.get("code") or error.get("type") or "")
        else:
            message, code = str(error), ""
        message = message.replace(api_key, "[hidden API key]").strip()
        code = code.replace(api_key, "[hidden API key]").strip()
        detail = f" — {message[:450]}" if message else ""
        code_part = f" ({code[:100]})" if code else ""
        raise AIProviderError(
            f"{provider} API returned HTTP {response.status_code}{code_part}{detail}"
        )

    if not isinstance(data, dict):
        raise AIProviderError(f"{provider} returned an unexpected response format.")
    return data


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
        data = _post_provider_json(
            "Gemini",
            url,
            api_key,
            params={"key": api_key},
            payload={
                "contents": [{"parts": [{"text": full_prompt}]}],
                "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1800},
            },
            timeout=60,
        )
        candidates = data.get("candidates", [])
        if not candidates:
            raise AIProviderError(
                "Gemini returned no answer. Check model access, API key restrictions and quota."
            )
        parts = candidates[0].get("content", {}).get("parts", [])
        answer = "\n".join(part.get("text", "") for part in parts if part.get("text"))
        if not answer:
            finish_reason = candidates[0].get("finishReason", "unknown")
            raise AIProviderError(
                f"Gemini returned no text (finish reason: {finish_reason}). Check model access and safety response."
            )
        return answer

    if provider == "Groq":
        model_id = model.strip() or "openai/gpt-oss-20b"
        data = _post_provider_json(
            "Groq",
            "https://api.groq.com/openai/v1/chat/completions",
            api_key,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            payload={
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
        choices = data.get("choices", [])
        if not choices:
            raise AIProviderError("Groq returned no answer. Check model access and quota.")
        answer = str(choices[0].get("message", {}).get("content", "")).strip()
        if not answer:
            raise AIProviderError("Groq response did not contain text.")
        return answer

    if provider == "OpenAI":
        model_id = model.strip() or "gpt-5.5"
        data = _post_provider_json(
            "OpenAI",
            "https://api.openai.com/v1/responses",
            api_key,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            payload={
                "model": model_id,
                "instructions": system_prompt,
                "input": full_prompt,
                "max_output_tokens": 1800,
            },
            timeout=90,
        )
        answer = str(data.get("output_text", "")).strip()
        if not answer:
            parts = []
            for item in data.get("output", []):
                if item.get("type") == "message":
                    parts.extend(
                        part.get("text", "")
                        for part in item.get("content", [])
                        if part.get("type") == "output_text"
                    )
            answer = "\n".join(parts).strip()
        if not answer:
            status = data.get("status", "unknown")
            incomplete = data.get("incomplete_details") or {}
            reason = incomplete.get("reason", "")
            detail = f"; reason: {reason}" if reason else ""
            raise AIProviderError(
                f"OpenAI returned no text (response status: {status}{detail}). "
                "Check model access and API project billing."
            )
        return answer

    raise ValueError("Unsupported AI provider. Choose OpenAI, Gemini or Groq.")


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
    candidate_context = checklist + "\n\nCANDIDATES JSON:\n" + json.dumps(candidates, ensure_ascii=False, default=str)
    raw = generate_market_answer(
        provider,
        api_key,
        "Validate every supplied candidate against the exact CRT checklist. Return only the requested JSON. Do not add rules.",
        market_context=candidate_context,
        model=model,
    )
    text = raw.strip()
    text = re.sub(r"^`{3}(?:json)?\s*|\s*`{3}$", "", text, flags=re.I)
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        raise AIProviderError("AI did not return the required JSON result. Please retry.")
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        raise AIProviderError("AI returned invalid JSON for the CRT filter. Please retry.") from None

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
