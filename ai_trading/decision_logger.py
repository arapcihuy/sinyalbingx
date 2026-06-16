import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(BASE_DIR, "database")
DB_PATH = os.path.join(DB_DIR, "ai_logs.db")


def init_db(db_path: str = DB_PATH) -> str:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with sqlite3.connect(db_path, timeout=5) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_decision_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                pair TEXT NOT NULL,
                action TEXT NOT NULL,
                price REAL,
                sl REAL,
                tp1 REAL,
                tp2 REAL,
                source TEXT NOT NULL,
                approved INTEGER NOT NULL,
                reason TEXT,
                latency_ms INTEGER,
                raw_error TEXT
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ai_decision_logs_created_at ON ai_decision_logs(created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ai_decision_logs_pair_action ON ai_decision_logs(pair, action)"
        )
    return db_path


def log_decision(
    pair: str,
    action: str,
    price: float,
    sl: float,
    tp1: float,
    tp2: float,
    source: str,
    approved: bool,
    reason: str,
    latency_ms: Optional[int] = None,
    raw_error: Optional[str] = None,
    db_path: str = DB_PATH,
) -> bool:
    """Best-effort SQLite audit log. Never raise to trading flow."""
    try:
        init_db(db_path)
        created_at = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(db_path, timeout=5) as conn:
            conn.execute(
                """
                INSERT INTO ai_decision_logs (
                    created_at, pair, action, price, sl, tp1, tp2,
                    source, approved, reason, latency_ms, raw_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    pair,
                    action,
                    price,
                    sl,
                    tp1,
                    tp2,
                    source,
                    1 if approved else 0,
                    reason,
                    latency_ms,
                    raw_error,
                ),
            )
        return True
    except Exception:
        return False


def summarize_recent(limit: int = 20, db_path: str = DB_PATH) -> list[dict]:
    init_db(db_path)
    with sqlite3.connect(db_path, timeout=5) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT * FROM ai_decision_logs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]
