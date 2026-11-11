"""Optional LLM connectors for market-context explanation.

Only market/scanner information supplied by the dashboard is sent. No broker
credentials, account balances, orders or holdings are included automatically.
"""
from __future__ import annotations

import json
import re
from datetime import date

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


def _candidate_crt_errors(row: dict) -> list[str]:
    """Deterministic safety gate: reject incomplete or internally inconsistent CRT rows."""
    errors: list[str] = []
    required_text = [
        "Symbol", "Setup", "Entry Status", "Target Status", "Monthly Status",
        "Sweep Date", "CHoCH Date", "Retest Date", "Entry Date", "Entry Zone Type",
    ]
    for field in required_text:
        value = row.get(field)
        if value is None or str(value).strip() in {"", "nan", "None"}:
            errors.append(f"{field} missing")

    try:
        sweep_date = date.fromisoformat(str(row.get("Sweep Date")))
        choch_date = date.fromisoformat(str(row.get("CHoCH Date")))
        retest_date = date.fromisoformat(str(row.get("Retest Date")))
        entry_date = date.fromisoformat(str(row.get("Entry Date")))
        if not sweep_date < choch_date <= retest_date <= entry_date:
            errors.append("Date sequence must be Sweep < CHoCH <= Retest <= Entry")
    except (TypeError, ValueError):
        errors.append("CRT event dates must be valid ISO dates")

    allowed_zones = {"FVG", "IFVG", "OB", "BOB"}
    zone_types = {item.strip() for item in str(row.get("Entry Zone Type", "")).split("+") if item.strip()}
    if not zone_types or not zone_types.issubset(allowed_zones):
        errors.append("Entry Zone Type must be FVG, IFVG, OB or BOB")

    numeric_fields = [
        "Entry", "SL", "Target (M1 Monthly H/L)", "M1 High", "M1 Low",
        "M2 Close", "Sweep Candle High", "Sweep Candle Low", "Zone Low", "Zone High",
    ]
    numbers: dict[str, float] = {}
    for field in numeric_fields:
        try:
            value = float(row.get(field))
            if value != value or value in {float("inf"), float("-inf")}:
                raise ValueError
            numbers[field] = value
        except (TypeError, ValueError):
            errors.append(f"{field} missing or not numeric")

    if int(row.get("Stage", 0) or 0) != 3:
        errors.append("Stage must be 3 (active entry)")
    if row.get("Setup") not in {"BUY", "SELL"}:
        errors.append("Setup must be BUY or SELL")
    if row.get("Entry Status") != "TRIGGERED":
        errors.append("Entry is not triggered")
    if row.get("Target Status") != "TARGET PENDING":
        errors.append("Target is not pending")
    if row.get("Setup") == "BUY" and row.get("Monthly Status") != "VALID_BULLISH_SWEEP":
        errors.append("Monthly status is not a valid bullish sweep")
    if row.get("Setup") == "SELL" and row.get("Monthly Status") != "VALID_BEARISH_SWEEP":
        errors.append("Monthly status is not a valid bearish sweep")

    if len(numbers) == len(numeric_fields):
        entry, stop, target = numbers["Entry"], numbers["SL"], numbers["Target (M1 Monthly H/L)"]
        m1_high, m1_low, m2_close = numbers["M1 High"], numbers["M1 Low"], numbers["M2 Close"]
        sweep_high, sweep_low = numbers["Sweep Candle High"], numbers["Sweep Candle Low"]
        zone_low, zone_high = numbers["Zone Low"], numbers["Zone High"]
        if not m1_low < m2_close < m1_high:
            errors.append("M2 close is not inside the full M1 range")
        if not zone_low < zone_high:
            errors.append("Entry zone bounds are invalid")
        if row.get("Setup") == "BUY":
            if not sweep_low < m1_low:
                errors.append("BUY sweep candle low did not pierce M1 low")
            if not stop < entry < target:
                errors.append("BUY levels must satisfy SL < Entry < M1 target")
            if abs(stop - sweep_low) > max(0.01, abs(sweep_low) * 1e-6):
                errors.append("BUY SL does not match the actual sweep candle low")
            if abs(target - m1_high) > max(0.01, abs(m1_high) * 1e-6):
                errors.append("BUY target does not match M1 high liquidity")
            if entry <= zone_high:
                errors.append("BUY confirmation close is not above the retested zone")
        elif row.get("Setup") == "SELL":
            if not sweep_high > m1_high:
                errors.append("SELL sweep candle high did not pierce M1 high")
            if not target < entry < stop:
                errors.append("SELL levels must satisfy M1 target < Entry < SL")
            if abs(stop - sweep_high) > max(0.01, abs(sweep_high) * 1e-6):
                errors.append("SELL SL does not match the actual sweep candle high")
            if abs(target - m1_low) > max(0.01, abs(m1_low) * 1e-6):
                errors.append("SELL target does not match M1 low liquidity")
            if entry >= zone_low:
                errors.append("SELL confirmation close is not below the retested zone")

    return list(dict.fromkeys(errors))


def filter_strong_crt_setups(
    provider: str,
    api_key: str,
    candidates: list[dict],
    model: str = "",
) -> dict:
    """AI review is restricted to deterministic active CRT entries from the scanner."""
    if not candidates:
        return {"approved": [], "rejected": [], "summary": "No active CRT entries were supplied."}

    eligible: list[dict] = []
    rejected: list[dict] = []
    for candidate in candidates:
        errors = _candidate_crt_errors(candidate)
        if errors:
            rejected.append({
                "Symbol": str(candidate.get("Symbol", "Unknown")),
                "Reason": "; ".join(errors),
            })
        else:
            eligible.append(candidate)

    if not eligible:
        return {
            "approved": [],
            "rejected": rejected,
            "summary": "No candidate passed the deterministic Monthly-Daily CRT evidence checks.",
        }

    allowed = {str(row["Symbol"]): row for row in eligible}
    checklist = (
        "You are a conservative reviewer of a Monthly (1M) to Daily (1D) CRT scanner. "
        "Review ONLY the supplied active scanner rows. M1 is the previous completed monthly range. "
        "M2 must sweep exactly one side of M1 and close back inside the FULL M1 high-low range. "
        "If both sides were swept, reject. M3 Daily structure must show CHoCH in the sweep-reclaim direction. "
        "After CHoCH, entry must have a retest in ANY ONE of these four permitted zones: "
        "FVG (directional three-candle gap), IFVG (opposite gap closed through and then flipped), "
        "OB (last counter-direction candle before the CHoCH break), or BOB (a broken opposing block "
        "reclaimed through its far edge). A retest must be followed within the scanner confirmation window "
        "by a confirming Daily close in the trade direction. Stop is the actual sweep candle low for BUY "
        "or high for SELL. Target is opposite M1 monthly liquidity. The candidate must have Stage 3, "
        "Entry Status TRIGGERED and Target Status TARGET PENDING. "
        "Do not add RSI, MACD, EMA, volume, news, fundamentals, or extra filters. "
        "Do not invent data or symbols. You may only approve or reject supplied symbols. "
        "Return ONLY JSON with approved (array: Symbol, Reason), rejected (array: Symbol, Reason), "
        "and summary (string)."
    )
    raw = generate_market_answer(
        provider,
        api_key,
        "Review each supplied row against the exact Monthly-Daily CRT checklist. Return only the requested JSON.",
        market_context=checklist + "\n\nACTIVE CRT CANDIDATES:\n" + json.dumps(eligible, ensure_ascii=False, default=str),
        model=model,
    )
    raw_text = raw.strip()
    fence = chr(96) * 3
    raw_text = re.sub(r"^" + fence + r"(?:json)?\s*|\s*" + fence + r"$", "", raw_text, flags=re.I)
    match = re.search(r"\{.*\}", raw_text, flags=re.S)
    if not match:
        raise AIProviderError("AI did not return the required JSON result. Please retry.")
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        raise AIProviderError("AI returned invalid JSON for the CRT filter. Please retry.") from None

    approved = []
    ai_rejected = []
    for item in parsed.get("approved", []):
        symbol = str(item.get("Symbol", ""))
        if symbol in allowed:
            source = allowed[symbol]
            approved.append({
                "Symbol": symbol,
                "Direction": source["Setup"],
                "Entry Zone Type": source["Entry Zone Type"],
                "Entry": source["Entry"],
                "SL": source["SL"],
                "Target": source["Target (M1 Monthly H/L)"],
                "Reason": str(item.get("Reason", "Scanner evidence passed; AI reviewed.")),
            })
    for item in parsed.get("rejected", []):
        symbol = str(item.get("Symbol", ""))
        if symbol in allowed:
            ai_rejected.append({
                "Symbol": symbol,
                "Reason": str(item.get("Reason", "AI marked the supplied CRT evidence for manual review.")),
            })

    covered = {item["Symbol"] for item in approved + ai_rejected}
    for symbol in sorted(set(allowed) - covered):
        ai_rejected.append({"Symbol": symbol, "Reason": "AI did not return a decision; manual review required."})

    return {
        "approved": approved,
        "rejected": rejected + ai_rejected,
        "summary": str(parsed.get("summary", "Monthly-Daily CRT review completed.")),
    }
