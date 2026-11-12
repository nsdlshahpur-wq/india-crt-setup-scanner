"""Scheduled, read-only CRT signal monitor. Telegram delivery is optional."""
from __future__ import annotations

import json
import os
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from data_fetch import download_market_data
from scanner import ScanConfig, scan_symbol
from universe import make_universe

IST = ZoneInfo("Asia/Kolkata")
STATE_PATH = Path(".bot_state/seen_signals.json")


def telegram_send(message: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("Telegram not configured; signal output follows.")
        print(message)
        return
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": message, "disable_web_page_preview": True},
        timeout=20,
    )
    response.raise_for_status()


def ai_summary(signals: list[dict]) -> str:
    """Optional OpenAI summary; deterministic signal rules remain the source of truth."""
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or not signals:
        return ""
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    payload = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": "Summarise these rule-based Indian equity CRT scan results in concise Hindi. "
                "Do not invent prices, predict certainty, or recommend automatic execution. "
                "State that this is a screening alert, not investment advice."
            },
            {"role": "user", "content": json.dumps(signals, ensure_ascii=False)}
        ],
        "max_output_tokens": 350,
    }
    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    body = response.json()
    parts = []
    for item in body.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                parts.append(content.get("text", ""))
    return "\n".join(parts).strip()


def load_state() -> set[str]:
    try:
        return set(json.loads(STATE_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return set()


def save_state(seen: set[str]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(sorted(seen), indent=2), encoding="utf-8")


def main() -> int:
    now = datetime.now(IST)
    # Run on weekdays only; GitHub Actions cron is UTC and may be delayed.
    if now.weekday() >= 5:
        print("Weekend: no market scan.")
        return 0

    universe = make_universe("All BSE EQ stocks")
    if universe.empty:
        raise RuntimeError("BSE EQ universe is empty")
    universe = universe[universe["Symbol"].astype(str).str.strip().ne("")]
    symbols = universe["Symbol"].drop_duplicates().tolist()
    print(f"Scanning {len(symbols)} BSE EQ symbols at {now.isoformat()}")

    price_map, errors = download_market_data(symbols, period="1y", batch_size=80)
    cfg = ScanConfig()
    seen = load_state()
    fresh: list[dict] = []
    for row in universe.itertuples(index=False):
        frame = price_map.get(row.Symbol)
        if frame is None or frame.empty:
            continue
        result = scan_symbol(row.Symbol, row.Name, frame, cfg)
        if not result or result.get("Setup") not in {"BUY", "SELL"} or int(result.get("Stage", 0)) != 3:
            continue
        last_candle = str(result.get("Last Candle", ""))
        key = f"{row.Symbol}|{result.get('Setup')}|{last_candle}|{result.get('Entry')}"
        if key in seen:
            continue
        fresh.append({
            "symbol": row.Symbol,
            "name": row.Name,
            "exchange": "BSE",
            "setup": result.get("Setup"),
            "last_candle": last_candle,
            "entry": round(float(result["Entry"]), 2),
            "sl": round(float(result["SL"]), 2),
            "target": round(float(result["Target (M1 Monthly H/L)"]), 2),
            "zone": result.get("Entry Zone Type", ""),
            "reason": result.get("Setup Reason", ""),
        })
        seen.add(key)

    save_state(seen)
    print(f"Downloaded {len(price_map)}/{len(symbols)} symbols; errors={len(errors)}; fresh signals={len(fresh)}")
    if not fresh:
        print("No new confirmed CRT entries.")
        return 0

    lines = [
        "🇮🇳 BSE CRT BOT — NEW CONFIRMED DAILY SETUP",
        f"Scan time: {now.strftime('%d-%b-%Y %I:%M %p IST')}",
        "",
    ]
    for item in fresh[:30]:
        lines.extend([
            f"{item['setup']} | {item['symbol']} — {item['name']}",
            f"Entry ₹{item['entry']:.2f} | SL ₹{item['sl']:.2f} | M1 Target ₹{item['target']:.2f}",
            f"Zone: {item['zone']} | Candle: {item['last_candle']}",
            "",
        ])
    if len(fresh) > 30:
        lines.append(f"...and {len(fresh) - 30} more signals.")
    lines.append("Read-only alert. Verify chart/data; no orders are placed.")
    message = "\n".join(lines)
    summary = ai_summary(fresh)
    if summary:
        message += "\n\n🤖 AI summary (optional):\n" + summary
    telegram_send(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
