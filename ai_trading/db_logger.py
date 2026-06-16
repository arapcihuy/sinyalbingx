import os
import sqlite3
import logging
from datetime import datetime

logger = logging.getLogger("db_logger")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] (db_logger) %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Path database terisolasi di dalam folder ai_trading
DB_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(DB_DIR, "ai_logs.db")

def get_connection():
    """Membuka koneksi ke SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Membuat tabel ai_validation_logs jika belum ada dan melakukan migrasi kolom baru."""
    try:
        os.makedirs(DB_DIR, exist_ok=True)
        with get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ai_validation_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                    pair TEXT,
                    action TEXT,
                    price REAL,
                    sl REAL,
                    tp1 REAL,
                    tp2 REAL,
                    approved INTEGER,
                    reason TEXT,
                    status TEXT DEFAULT 'pending'
                )
            """)
            
            # Migrasi dinamis untuk kolom saran parameter AI
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(ai_validation_logs)")
            columns = [row[1] for row in cursor.fetchall()]
            
            if "suggested_sl" not in columns:
                conn.execute("ALTER TABLE ai_validation_logs ADD COLUMN suggested_sl REAL")
            if "suggested_tp1" not in columns:
                conn.execute("ALTER TABLE ai_validation_logs ADD COLUMN suggested_tp1 REAL")
            if "suggested_tp2" not in columns:
                conn.execute("ALTER TABLE ai_validation_logs ADD COLUMN suggested_tp2 REAL")
            if "suggested_leverage" not in columns:
                conn.execute("ALTER TABLE ai_validation_logs ADD COLUMN suggested_leverage INTEGER")
                
            conn.commit()
            logger.info(f"Database SQLite diinisialisasi sukses di: {DB_PATH}")
    except Exception as e:
        logger.error(f"Gagal inisialisasi database: {e}")

def log_validation(
    pair: str,
    action: str,
    price: float,
    sl: float,
    tp1: float,
    tp2: float,
    approved: bool,
    reason: str,
    status: str = "pending",
    suggested_sl: float = None,
    suggested_tp1: float = None,
    suggested_tp2: float = None,
    suggested_leverage: int = None
) -> int:
    """Mencatat hasil validasi AI dan saran parameter ke database."""
    try:
        init_db()  # Pastikan DB terbuat
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO ai_validation_logs (
                    timestamp, pair, action, price, sl, tp1, tp2, approved, reason, status,
                    suggested_sl, suggested_tp1, suggested_tp2, suggested_leverage
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                now_str,
                pair,
                action.upper(),
                float(price or 0.0),
                float(sl or 0.0),
                float(tp1 or 0.0),
                float(tp2 or 0.0),
                1 if approved else 0,
                reason,
                status,
                float(suggested_sl) if suggested_sl is not None else None,
                float(suggested_tp1) if suggested_tp1 is not None else None,
                float(suggested_tp2) if suggested_tp2 is not None else None,
                int(suggested_leverage) if suggested_leverage is not None else None
            ))
            conn.commit()
            row_id = cursor.lastrowid
            logger.info(f"Log disimpan | ID: {row_id} | {pair} {action} | Approved: {approved} | Suggested Lev: {suggested_leverage}")
            return row_id
    except Exception as e:
        logger.error(f"Gagal mencatat validasi ke DB: {e}")
        return -1

def update_log_status(row_id: int, status: str):
    """Memperbarui status akhir eksekusi untuk entri dengan ID tertentu."""
    if row_id is None or row_id < 0:
        return
    try:
        with get_connection() as conn:
            conn.execute("""
                UPDATE ai_validation_logs
                SET status = ?
                WHERE id = ?
            """, (status, row_id))
            conn.commit()
            logger.info(f"Log ID {row_id} status diperbarui menjadi: {status}")
    except Exception as e:
        logger.error(f"Gagal memperbarui status log ID {row_id}: {e}")

def get_summary_stats() -> dict:
    """Mengembalikan ringkasan statistik keputusan AI Filter."""
    try:
        init_db()
        with get_connection() as conn:
            cursor = conn.cursor()
            
            # Total sinyal masuk
            cursor.execute("SELECT COUNT(*) FROM ai_validation_logs")
            total = cursor.fetchone()[0]
            
            if total == 0:
                return {
                    "total": 0,
                    "approved": 0,
                    "rejected": 0,
                    "approval_rate": 0.0
                }
                
            # Jumlah disetujui (approved = 1)
            cursor.execute("SELECT COUNT(*) FROM ai_validation_logs WHERE approved = 1")
            approved = cursor.fetchone()[0]
            
            # Jumlah ditolak (approved = 0)
            cursor.execute("SELECT COUNT(*) FROM ai_validation_logs WHERE approved = 0")
            rejected = cursor.fetchone()[0]
            
            approval_rate = (approved / total) * 100
            
            return {
                "total": total,
                "approved": approved,
                "rejected": rejected,
                "approval_rate": round(approval_rate, 2)
            }
    except Exception as e:
        logger.error(f"Gagal mengambil statistik ringkasan: {e}")
        return {"total": 0, "approved": 0, "rejected": 0, "approval_rate": 0.0}

def get_recent_logs(limit: int = 5) -> list:
    """Mengambil daftar riwayat keputusan AI Filter terakhir beserta saran parameternya."""
    try:
        init_db()
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT timestamp, pair, action, price, sl, tp1, tp2, approved, reason, status,
                       suggested_sl, suggested_tp1, suggested_tp2, suggested_leverage
                FROM ai_validation_logs
                ORDER BY id DESC
                LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Gagal mengambil log terbaru: {e}")
        return []
