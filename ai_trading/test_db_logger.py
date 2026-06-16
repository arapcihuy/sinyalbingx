import os
import sys
import shutil

# Setup path agar bisa import db_logger
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

import db_logger

def test_db_operations():
    print("🧪 MEMULAI PENGUJIAN UNIT DATABASE LOGGER...")
    
    # 1. Path Database Uji Coba
    db_path_original = db_logger.DB_PATH
    db_logger.DB_PATH = os.path.join(current_dir, "test_ai_logs.db")
    
    # Hapus DB uji coba jika sebelumnya ada sisa
    if os.path.exists(db_logger.DB_PATH):
        os.remove(db_logger.DB_PATH)
        
    try:
        # 2. Uji inisialisasi
        print("\n1. Menguji init_db()...")
        db_logger.init_db()
        assert os.path.exists(db_logger.DB_PATH), "File database tidak terbuat!"
        print("✅ Database terbuat sukses.")

        # 3. Uji pencatatan validasi (Approved)
        print("\n2. Menguji log_validation() untuk sinyal APPROVED...")
        row_id_1 = db_logger.log_validation(
            pair="BTC-USDT",
            action="BUY",
            price=67000.0,
            sl=65500.0,
            tp1=69000.0,
            tp2=70000.0,
            approved=True,
            reason="Tren bullish terkonfirmasi Higher High.",
            status="pending"
        )
        print(f"Row ID hasil entry 1: {row_id_1}")
        assert row_id_1 > 0, "Gagal mengembalikan row ID yang valid!"
        
        # 4. Uji pencatatan validasi (Rejected)
        print("\n3. Menguji log_validation() untuk sinyal REJECTED...")
        row_id_2 = db_logger.log_validation(
            pair="ETH-USDT",
            action="BUY",
            price=3400.0,
            sl=3300.0,
            tp1=3600.0,
            tp2=3700.0,
            approved=False,
            reason="Tren bearish kuat di timeframe 15m.",
            status="rejected_by_ai"
        )
        print(f"Row ID hasil entry 2: {row_id_2}")
        assert row_id_2 > 0, "Gagal mengembalikan row ID yang valid!"

        # 5. Uji update status
        print("\n4. Menguji update_log_status()...")
        db_logger.update_log_status(row_id_1, "success_paper")
        
        # Verifikasi data masuk
        conn = db_logger.get_connection()
        row = conn.execute("SELECT * FROM ai_validation_logs WHERE id = ?", (row_id_1,)).fetchone()
        assert row["status"] == "success_paper", "Status gagal diperbarui!"
        print("✅ Status log 1 sukses diperbarui menjadi 'success_paper'.")

        # 6. Uji Penarikan Statistik Ringkasan
        print("\n5. Menguji get_summary_stats()...")
        stats = db_logger.get_summary_stats()
        print(f"Statistik: {stats}")
        assert stats["total"] == 2, "Jumlah total log salah!"
        assert stats["approved"] == 1, "Jumlah log disetujui salah!"
        assert stats["rejected"] == 1, "Jumlah log ditolak salah!"
        assert stats["approval_rate"] == 50.0, "Rasio persetujuan salah!"
        print("✅ Statistik penarikan data sesuai.")

        # 7. Uji Penarikan Log Terbaru
        print("\n6. Menguji get_recent_logs()...")
        recent = db_logger.get_recent_logs(limit=2)
        print(f"Total log ditarik: {len(recent)}")
        for log in recent:
            print(f"- Time: {log['timestamp']} | Pair: {log['pair']} | Action: {log['action']} | Approved: {log['approved']} | Status: {log['status']}")
        assert len(recent) == 2, "Jumlah log ditarik tidak sesuai limit!"
        print("✅ Riwayat log berhasil ditarik.")

        print("\n🎉 SEMUA PENGUJIAN UNIT DATABASE SUKSES!")

    finally:
        # Bersihkan DB Uji Coba
        if os.path.exists(db_logger.DB_PATH):
            os.remove(db_logger.DB_PATH)
        # Kembalikan path DB asli
        db_logger.DB_PATH = db_path_original

if __name__ == "__main__":
    test_db_operations()
