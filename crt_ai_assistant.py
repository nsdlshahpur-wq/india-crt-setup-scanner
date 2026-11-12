"""CRT assistant: rule-grounded setup verification and optional LLM explanation."""
from __future__ import annotations

import json
import os
from typing import Any

import pandas as pd
import requests


def verify_setup(row: dict[str, Any]) -> dict[str, Any]:
    """Verify the scanner's own CRT stages; never upgrade an incomplete setup."""
    setup = str(row.get("Setup", ""))
    stage = int(row.get("Stage", 0) or 0)
    monthly = str(row.get("Monthly Status", ""))
    checks = [
        ("M1/M2 liquidity sweep + reclaim", monthly == "VALID_BULLISH_SWEEP" or monthly == "VALID_BEARISH_SWEEP",
         monthly or "Monthly context unavailable"),
        ("M3 Daily CHoCH", pd.notna(row.get("CHoCH Date")), str(row.get("CHoCH Rule", "Not confirmed"))),
        ("FVG / IFVG / OB / BOB zone", bool(str(row.get("Entry Zone Type", "")).strip()),
         str(row.get("Entry Zone Type", "No active entry zone"))),
        ("Retest + directional candle close", pd.notna(row.get("Entry Date")),
         str(row.get("Entry Confirmation Rule", "Entry confirmation pending"))),
        ("Risk levels", pd.notna(row.get("Entry")) and pd.notna(row.get("SL")) and pd.notna(row.get("Target (M1 Monthly H/L)")),
         "Entry / SL / opposite M1 target availability"),
    ]
    passed = sum(1 for _, ok, _ in checks if ok)
    if stage == 6 or "Ambiguous" in setup:
        status = "AMBIGUOUS — NO TRADE"
    elif stage == 3 and setup in {"BUY", "SELL"} and passed == 5:
        status = "VALID — CONFIRMED"
    elif passed >= 2:
        status = "INCOMPLETE — WAIT"
    else:
        status = "INVALID / NO CRT SETUP"
    return {"status": status, "passed": passed, "total": len(checks), "checks": checks,
            "direction": str(row.get("Setup", "WAIT")), "reason": str(row.get("Setup Reason", ""))}


def explain_setup(row: dict[str, Any], question: str = "") -> str:
    """Use OpenAI when a key is configured; otherwise return deterministic grounded analysis."""
    verdict = verify_setup(row)
    payload = {
        "symbol": str(row.get("Symbol", row.get("Name", "Unknown"))),
        "setup": verdict["direction"], "status": verdict["status"],
        "checks": [{"name": n, "passed": ok, "detail": detail} for n, ok, detail in verdict["checks"]],
        "entry": row.get("Entry"), "stop_loss": row.get("SL"),
        "target": row.get("Target (M1 Monthly H/L)"), "last_candle": row.get("Last Candle"),
        "setup_reason": verdict["reason"], "question": question,
    }
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        try:
            import streamlit as st
            api_key = str(st.secrets.get("OPENAI_API_KEY", "")).strip()
        except Exception:
            api_key = ""
    if not api_key:
        return format_local_analysis(payload)
    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": os.getenv("CRT_AI_MODEL", "gpt-4o-mini"),
                  "temperature": 0.1,
                  "messages": [
                      {"role": "system", "content": (
                          "You are a cautious Indian-market CRT setup auditor. Use only supplied facts. "
                          "Do not invent candle data, indicators, prices, or probabilities. "
                          "Explain which mechanical CRT rules pass/fail. Never promise profit or issue "
                          "a guaranteed buy/sell instruction. If any required rule is missing, say WAIT."
                      )},
                      {"role": "user", "content": json.dumps(payload, default=str)},
                  ]},
            timeout=25,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        return format_local_analysis(payload) + f"\n\nAI API उपलब्ध नहीं हुआ; local rule-check दिखाया गया। ({str(exc)[:160]})"


def format_local_analysis(payload: dict[str, Any]) -> str:
    lines = [
        f"**निष्कर्ष: {payload['status']}**",
        f"**दिशा / Setup:** {payload['setup']}",
        f"**CRT नियम:** {sum(bool(c['passed']) for c in payload['checks'])}/{len(payload['checks'])} शर्तें पूरी।",
        "",
    ]
    for item in payload["checks"]:
        mark = "✅" if item["passed"] else "⏳"
        lines.append(f"- {mark} **{item['name']}** — {item['detail']}")
    lines += ["", f"**Entry:** {payload['entry']}  |  **SL:** {payload['stop_loss']}  |  **M1 Target:** {payload['target']}",
              f"**Last candle:** {payload['last_candle']}",
              "", "यह जाँच उपलब्ध Daily OHLC और scanner के mechanical rules पर आधारित है; यह live tick-data या लाभ की गारंटी नहीं है."]
    if payload.get("question"):
        lines += ["", f"**आपका सवाल:** {payload['question']}",
                  "इस सवाल का उत्तर केवल ऊपर उपलब्ध scanner data से दिया जा सकता है; अतिरिक्त timeframe/candle data यहाँ उपलब्ध नहीं है।"]
    return "\n".join(lines)
