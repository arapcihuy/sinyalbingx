"""
db_logger.py — Database logger mandiri untuk SinyalBingX.
Pengganti ai_trading.db_logger. Menyimpan log validasi sinyal ke signals.db.
"""
import os
import sqlite3
import time
import logging

logger = logging.getLogger(__name__)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "signals.db")


def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    try:
        conn = _get_conn()
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS ai_signal_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT DEFAULT (datetime('now','localtime')),
                pair TEXT,
                action TEXT,
                price REAL,
                sl REAL,
                tp1 REAL,
                tp2 REAL,
                approved INTEGER DEFAULT 0,
                reason TEXT,
                status TEXT DEFAULT 'pending',
                suggested_sl REAL,
                suggested_tp1 REAL,
                suggested_tp2 REAL,
                suggested_leverage INTEGER
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"db_logger init error: {e}")


_init_db()


def log_validation(pair, action, price, sl, tp1, tp2,
                   approved, reason, status,
                   suggested_sl=None, suggested_tp1=None,
                   suggested_tp2=None, suggested_leverage=None):
    """Catat log validasi sinyal ke DB. Return row id."""
    try:
        conn = _get_conn()
        c = conn.cursor()
        c.execute("""
            INSERT INTO ai_signal_logs
                (pair, action, price, sl, tp1, tp2, approved, reason, status,
                 suggested_sl, suggested_tp1, suggested_tp2, suggested_leverage)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (pair, action, float(price or 0), float(sl or 0),
              float(tp1 or 0), float(tp2 or 0),
              1 if approved else 0, reason, status,
              suggested_sl, suggested_tp1, suggested_tp2, suggested_leverage))
        conn.commit()
        row_id = c.lastrowid
        conn.close()
        logger.info(f"Log disimpan | ID: {row_id} | {pair} {action} | Approved: {approved} | Suggested Lev: {suggested_leverage}")
        return row_id
    except Exception as e:
        logger.error(f"db_logger log_validation error: {e}")
        return -1


def update_log_status(row_id, status):
    """Update status eksekusi by row_id."""
    try:
        conn = _get_conn()
        c = conn.cursor()
        c.execute("UPDATE ai_signal_logs SET status = ? WHERE id = ?", (status, row_id))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"db_logger update_log_status error: {e}")


def get_summary_stats():
    """Return statistik ringkasan AI filter."""
    try:
        conn = _get_conn()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) as total FROM ai_signal_logs")
        total = c.fetchone()["total"]
        c.execute("SELECT COUNT(*) as approved FROM ai_signal_logs WHERE approved = 1")
        approved = c.fetchone()["approved"]
        c.execute("SELECT COUNT(*) as rejected FROM ai_signal_logs WHERE approved = 0")
        rejected = c.fetchone()["rejected"]
        conn.close()
        approval_rate = round((approved / total * 100), 1) if total > 0 else 0.0
        return {
            "total": total,
            "approved": approved,
            "rejected": rejected,
            "approval_rate": approval_rate
        }
    except Exception as e:
        logger.error(f"db_logger get_summary_stats error: {e}")
        return {"total": 0, "approved": 0, "rejected": 0, "approval_rate": 0.0}


def get_recent_logs(limit=5):
    """Return list of dict untuk log terbaru."""
    try:
        conn = _get_conn()
        c = conn.cursor()
        c.execute("""
            SELECT * FROM ai_signal_logs
            ORDER BY id DESC LIMIT ?
        """, (limit,))
        rows = c.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"db_logger get_recent_logs error: {e}")
        return []