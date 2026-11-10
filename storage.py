"""Small SQLite storage layer for watchlist, alert history and trade journal.

The SQLite file stays on the machine/container where Streamlit runs. On
ephemeral hosting, configure persistent storage or migrate this layer to a
managed database before relying on it as the only copy of trading records.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pandas as pd

DB_PATH = Path(os.environ.get("CRT_APP_DB", Path(__file__).resolve().parent / "data" / "crt_dashboard.sqlite3"))


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def _connection():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with _connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS watchlist (
                symbol TEXT PRIMARY KEY,
                label TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS alert_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dedupe_key TEXT NOT NULL UNIQUE,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS trade_journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                setup TEXT NOT NULL DEFAULT 'CRT',
                timeframe TEXT NOT NULL DEFAULT 'Daily',
                trade_date TEXT NOT NULL,
                entry REAL NOT NULL,
                stop_loss REAL,
                target REAL,
                quantity INTEGER NOT NULL DEFAULT 1,
                exit_date TEXT,
                exit_price REAL,
                costs REAL NOT NULL DEFAULT 0,
                pnl REAL,
                r_multiple REAL,
                status TEXT NOT NULL DEFAULT 'OPEN',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )


def add_watchlist(symbol: str, label: str = "") -> bool:
    init_db()
    clean = symbol.strip().upper()
    if not clean:
        raise ValueError("Symbol is required.")
    with _connection() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO watchlist(symbol, label, active) VALUES(?,?,1)",
            (clean, label.strip()),
        )
        return cur.rowcount > 0


def remove_watchlist(symbol: str) -> None:
    init_db()
    with _connection() as conn:
        conn.execute("DELETE FROM watchlist WHERE symbol=?", (symbol.strip().upper(),))


def list_watchlist() -> pd.DataFrame:
    init_db()
    with _connection() as conn:
        rows = conn.execute("SELECT symbol AS Symbol, label AS Name, active AS Active, created_at AS Added FROM watchlist ORDER BY symbol").fetchall()
    return pd.DataFrame([dict(r) for r in rows], columns=["Symbol", "Name", "Active", "Added"])


def add_alert(dedupe_key: str, symbol: str, timeframe: str, status: str, message: str) -> bool:
    init_db()
    with _connection() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO alert_log(dedupe_key,symbol,timeframe,status,message) VALUES(?,?,?,?,?)",
            (dedupe_key, symbol, timeframe, status, message),
        )
        return cur.rowcount > 0


def list_alerts(limit: int = 250) -> pd.DataFrame:
    init_db()
    with _connection() as conn:
        rows = conn.execute(
            "SELECT created_at AS Time, symbol AS Symbol, timeframe AS Timeframe, status AS Status, message AS Alert FROM alert_log ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows], columns=["Time", "Symbol", "Timeframe", "Status", "Alert"])


def add_trade(
    symbol: str, side: str, setup: str, timeframe: str, trade_date: str,
    entry: float, stop_loss: float | None, target: float | None,
    quantity: int, costs: float = 0.0, notes: str = "",
) -> int:
    init_db()
    clean_symbol = symbol.strip().upper()
    if not clean_symbol or side not in {"BUY", "SELL"}:
        raise ValueError("Valid symbol and BUY/SELL side are required.")
    if entry <= 0 or quantity < 1 or costs < 0:
        raise ValueError("Entry, quantity or costs are invalid.")
    with _connection() as conn:
        cur = conn.execute(
            """INSERT INTO trade_journal
            (symbol,side,setup,timeframe,trade_date,entry,stop_loss,target,quantity,costs,notes)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (clean_symbol, side, setup, timeframe, trade_date, entry, stop_loss, target, quantity, costs, notes),
        )
        return int(cur.lastrowid)


def list_trades(status: str | None = None) -> pd.DataFrame:
    init_db()
    sql = """SELECT id AS ID, symbol AS Symbol, side AS Side, setup AS Setup,
             timeframe AS Timeframe, trade_date AS Entry_Date, entry AS Entry,
             stop_loss AS SL, target AS Target, quantity AS Qty,
             exit_date AS Exit_Date, exit_price AS Exit, costs AS Costs,
             pnl AS PnL, r_multiple AS R, status AS Status, notes AS Notes
             FROM trade_journal"""
    params: tuple[Any, ...] = ()
    if status in {"OPEN", "CLOSED"}:
        sql += " WHERE status=?"
        params = (status,)
    sql += " ORDER BY id DESC"
    with _connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def close_trade(trade_id: int, exit_date: str, exit_price: float, extra_costs: float = 0.0) -> dict[str, float]:
    init_db()
    if exit_price <= 0 or extra_costs < 0:
        raise ValueError("Exit price and costs are invalid.")
    with _connection() as conn:
        row = conn.execute("SELECT * FROM trade_journal WHERE id=? AND status='OPEN'", (int(trade_id),)).fetchone()
        if row is None:
            raise ValueError("Open trade not found.")
        direction = 1 if row["side"] == "BUY" else -1
        gross = (float(exit_price) - float(row["entry"])) * direction * int(row["quantity"])
        total_costs = float(row["costs"]) + float(extra_costs)
        pnl = gross - total_costs
        per_share_risk = abs(float(row["entry"]) - float(row["stop_loss"])) if row["stop_loss"] is not None else 0.0
        total_risk = per_share_risk * int(row["quantity"])
        r_multiple = pnl / total_risk if total_risk > 0 else 0.0
        conn.execute(
            """UPDATE trade_journal SET exit_date=?, exit_price=?, costs=?, pnl=?,
               r_multiple=?, status='CLOSED' WHERE id=?""",
            (exit_date, exit_price, total_costs, pnl, r_multiple, int(trade_id)),
        )
    return {"gross_pnl": gross, "costs": total_costs, "pnl": pnl, "r_multiple": r_multiple}
