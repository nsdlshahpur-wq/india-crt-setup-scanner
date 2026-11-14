"""Scheduled read-only MTF CRT scanner for the full Indian market universe.

GitHub Actions invokes this every five minutes during the Indian cash session.
To avoid hammering Yahoo Finance, each run scans a rotating batch of the full
NSE/BSE/SME + mapped-index universe. It is NOT a full-universe refresh every
five minutes. Telegram delivery is optional via repository Actions secrets.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from mtf_analysis import analyze_mtf_symbol
from universe import make_universe

IST = ZoneInfo("Asia/Kolkata")
STATE_PATH = Path(".auto_mtf_state/seen.json")
OUTPUT_PATH = Path("automatic_mtf_scan.csv")
BATCH_SIZE = max(1, int(os.getenv("AUTO_MTF_BATCH_SIZE", "20")))


def load_seen() -> set[str]:
    try:
        return set(json.loads(STATE_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return set()


def save_seen(seen: set[str]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Bound state growth while retaining recent de-duplication keys.
    STATE_PATH.write_text(json.dumps(sorted(seen)[-20000:], indent=2), encoding="utf-8")


def send_telegram(message: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("Telegram secrets not configured; signals will be available in the CSV artifact.")
        return
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": message, "disable_web_page_preview": True},
        timeout=20,
    )
    response.raise_for_status()


def main() -> int:
    now = datetime.now(IST)
    if now.weekday() >= 5 or not (time(9, 15) <= now.time() <= time(15, 30)):
        print(f"Outside Indian cash-market session: {now.isoformat()}")
        return 0

    universe = make_universe("All India stocks + indices")
    if universe.empty:
        raise RuntimeError("All India stocks + indices universe is empty")
    universe = universe[
        universe["Symbol"].fillna("").astype(str).str.strip().ne("")
    ].drop_duplicates(subset=["Symbol"]).reset_index(drop=True)

    # Rotate through the entire universe on successive 5-minute slots.
    # GitHub scheduled jobs can be delayed, so the slot is time-derived rather
    # than relying on a mutable cursor file.
    total = len(universe)
    batches = max(1, (total + BATCH_SIZE - 1) // BATCH_SIZE)
    slot = int(now.timestamp() // 300)
    batch_no = slot % batches
    start = batch_no * BATCH_SIZE
    selected = universe.iloc[start : min(start + BATCH_SIZE, total)]
    print(
        f"Universe={total}; batch={batch_no + 1}/{batches}; "
        f"scanning={len(selected)} symbols; time={now.isoformat()}"
    )

    seen = load_seen()
    rows: list[dict] = []
    fresh: list[dict] = []
    errors: list[dict] = []
    for item in selected.itertuples(index=False):
        symbol = str(item.Symbol)
        name = str(getattr(item, "Name", symbol))
        try:
            result, symbol_errors = analyze_mtf_symbol(symbol)
            if symbol_errors:
                errors.extend(
                    {"Symbol": symbol, "Timeframe": pair, "Error": message}
                    for pair, message in symbol_errors.items()
                )
            if result.empty:
                continue
            result.insert(0, "Name", name)
            result.insert(0, "Symbol", symbol)
            rows.extend(result.to_dict("records"))
            for record in result.to_dict("records"):
                signal = str(record.get("Signal", "WAIT"))
                if signal not in {"BULL ORDER", "BEAR ORDER", "BUY", "SELL"}:
                    continue
                candle = str(record.get("LTF Candle", ""))
                key = f"{symbol}|{record.get('HTF → LTF')}|{signal}|{candle}"
                if key in seen:
                    continue
                seen.add(key)
                fresh.append({
                    "symbol": symbol,
                    "name": name,
                    "pair": record.get("HTF → LTF", ""),
                    "signal": "BUY" if signal in {"BULL ORDER", "BUY"} else "SELL",
                    "liquidity": record.get("LTF Liquidity", ""),
                    "choch": record.get("LTF MSS", ""),
                    "zone": record.get("Retest Zone", record.get("Entry Zone", "")),
                    "entry": record.get("Entry Price"),
                    "candle": candle,
                })
        except Exception as exc:
            errors.append({"Symbol": symbol, "Timeframe": "ALL", "Error": f"{type(exc).__name__}: {str(exc)[:180]}"})

    columns = [
        "Symbol", "Name", "HTF → LTF", "HTF Liquidity", "HTF MSS",
        "LTF Liquidity", "LTF MSS", "Entry Zone", "Retest Zone",
        "Retest Price", "Entry Price", "Entry Time", "Alignment",
        "Entry Status", "Signal", "HTF Close", "LTF Close",
        "HTF Candle", "LTF Candle",
    ]
    pd.DataFrame(rows, columns=columns).to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    if errors:
        pd.DataFrame(errors).to_csv("automatic_mtf_errors.csv", index=False, encoding="utf-8-sig")
    save_seen(seen)

    print(f"Rows={len(rows)}; fresh confirmed signals={len(fresh)}; errors={len(errors)}")
    if fresh:
        lines = [
            "🇮🇳 AUTOMATIC MTF CRT SCANNER",
            f"Time: {now.strftime('%d-%b-%Y %I:%M %p IST')}",
            f"Batch: {batch_no + 1}/{batches} ({len(selected)} symbols)",
            "",
        ]
        for item in fresh[:35]:
            lines.append(
                f"{item['signal']} | {item['symbol']} — {item['name']} | {item['pair']} | "
                f"{item['liquidity']} | {item['choch']} | Zone: {item['zone']} | "
                f"Entry: {item['entry']} | Candle: {item['candle']}"
            )
        if len(fresh) > 35:
            lines.append(f"...plus {len(fresh) - 35} more new signals.")
        lines.append("Read-only screening alert; verify chart/data. No broker orders are placed.")
        send_telegram("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
