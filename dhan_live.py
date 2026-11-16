"""Optional DhanHQ v2 live market-data connector.

Credentials are read only from Streamlit secrets/environment configuration.
No order, trade, or account-write endpoint is used.
"""
from __future__ import annotations

import os
import struct
import time
from datetime import datetime, timezone
from typing import Any

import websocket


DHAN_WS_BASE = "wss://api-feed.dhan.co"


def _secret(name: str) -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    try:
        import streamlit as st
        return str(st.secrets.get(name, "")).strip()
    except Exception:
        return ""


def dhan_credentials() -> tuple[str, str]:
    """Return (client_id, access_token); never return or log API secret."""
    return _secret("DHAN_CLIENT_ID"), _secret("DHAN_ACCESS_TOKEN")


def parse_dhan_ticker_packet(packet: bytes) -> dict[str, Any] | None:
    """Parse Dhan binary Ticker (response code 2) packet."""
    if not isinstance(packet, (bytes, bytearray)) or len(packet) < 17:
        return None
    response_code = packet[0]
    if response_code != 2:
        return None
    segment = packet[4]
    security_id = struct.unpack_from("<I", packet, 5)[0]
    ltp = struct.unpack_from("<f", packet, 9)[0]
    ltt = struct.unpack_from("<I", packet, 13)[0]
    if ltp <= 0:
        return None
    return {
        "exchange_segment_code": segment,
        "security_id": str(security_id),
        "ltp": float(ltp),
        "last_trade_time": datetime.fromtimestamp(ltt, tz=timezone.utc).isoformat(),
        "received_at": datetime.now(timezone.utc).isoformat(),
        "provider": "DhanHQ v2 WebSocket",
        "status": "LIVE",
    }


def fetch_dhan_live_ticker(exchange_segment: str, security_id: str, timeout: int = 12) -> dict[str, Any]:
    """Connect, subscribe to one instrument, and return its first live ticker packet.

    Requires DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in Streamlit secrets.
    Data API subscription must be active in the Dhan account.
    """
    client_id, access_token = dhan_credentials()
    if not client_id or not access_token:
        raise RuntimeError(
            "Dhan credentials missing. Configure DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN "
            "in Streamlit App Secrets. Do not paste secrets into GitHub code."
        )
    if not exchange_segment or not str(security_id).isdigit():
        raise ValueError("A valid Dhan exchange segment and numeric Security ID are required.")
    url = (
        f"{DHAN_WS_BASE}?version=2&token={access_token}"
        f"&clientId={client_id}&authType=2"
    )
    ws = websocket.create_connection(url, timeout=timeout, enable_multithread=True)
    try:
        ws.send(__import__("json").dumps({
            "RequestCode": 15,
            "InstrumentCount": 1,
            "InstrumentList": [{
                "ExchangeSegment": exchange_segment,
                "SecurityId": str(security_id),
            }],
        }))
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                packet = ws.recv()
            except websocket.WebSocketTimeoutException:
                break
            if isinstance(packet, str):
                # Server text notices/errors are surfaced, never interpreted as a quote.
                continue
            result = parse_dhan_ticker_packet(packet)
            if result and result["security_id"] == str(security_id):
                result["exchange_segment"] = exchange_segment
                return result
        raise TimeoutError(
            "Dhan WebSocket connected but no matching ticker arrived. Check Data API plan, "
            "segment, Security ID, market hours and token validity."
        )
    finally:
        try:
            ws.send(__import__("json").dumps({"RequestCode": 12}))
        except Exception:
            pass
        ws.close()
