"""Read-only broker profile connectivity checks.

API credentials are read exclusively from Streamlit secrets. No credentials
are persisted in SQLite, displayed, or returned from this module.
"""
from __future__ import annotations

from typing import Any

import requests


def _get_secrets() -> Any:
    try:
        import streamlit as st
        return st.secrets.get("brokers", {})
    except Exception:
        return {}


def _section(name: str) -> Any:
    try:
        return _get_secrets().get(name, {})
    except Exception:
        return {}


def broker_is_configured(name: str) -> bool:
    cfg = _section(name)
    required = {
        "zerodha": ("api_key", "access_token"),
        "upstox": ("access_token",),
        "dhan": ("client_id", "access_token"),
    }
    fields = required.get(name, ())
    return bool(fields) and all(str(cfg.get(field, "")).strip() for field in fields)


def check_broker_profile(name: str) -> tuple[bool, str]:
    """Call only a read-only profile endpoint; never place or modify an order."""
    cfg = _section(name)
    try:
        if name == "zerodha":
            api_key = str(cfg.get("api_key", "")).strip()
            token = str(cfg.get("access_token", "")).strip()
            if not api_key or not token:
                return False, "Streamlit secrets में api_key और access_token नहीं मिले।"
            response = requests.get(
                "https://api.kite.trade/user/profile",
                headers={"Authorization": f"token {api_key}:{token}"},
                timeout=15,
            )
            response.raise_for_status()
            data = response.json().get("data", {})
            display = data.get("user_name") or data.get("user_id") or "Profile verified"
            return True, f"Zerodha profile connected: {display}"

        if name == "upstox":
            token = str(cfg.get("access_token", "")).strip()
            if not token:
                return False, "Streamlit secrets में access_token नहीं मिला।"
            response = requests.get(
                "https://api.upstox.com/v2/user/profile",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=15,
            )
            response.raise_for_status()
            data = response.json().get("data", {})
            display = data.get("user_name") or data.get("user_id") or "Profile verified"
            return True, f"Upstox profile connected: {display}"

        if name == "dhan":
            client_id = str(cfg.get("client_id", "")).strip()
            token = str(cfg.get("access_token", "")).strip()
            if not client_id or not token:
                return False, "Streamlit secrets में client_id और access_token नहीं मिले।"
            response = requests.get(
                "https://api.dhan.co/v2/profile",
                headers={"access-token": token, "dhanClientId": client_id},
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()
            display = data.get("dhanClientName") or data.get("dhanClientId") or "Profile verified"
            return True, f"DhanHQ profile connected: {display}"

        return False, "इस broker का secure profile adapter अभी उपलब्ध नहीं है।"
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "HTTP"
        if status in {401, 403}:
            return False, f"Authentication rejected (HTTP {status}). Token expiry / API app settings जाँचें।"
        return False, f"Broker API ने HTTP {status} लौटाया।"
    except requests.RequestException as exc:
        return False, f"Broker API तक network connection नहीं बन पाया: {type(exc).__name__}"
    except (ValueError, KeyError, TypeError):
        return False, "Broker response पढ़ा नहीं जा सका। API credentials और response format जाँचें।"
