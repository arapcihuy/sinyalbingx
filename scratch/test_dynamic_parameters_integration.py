import os
import sys
import time
import logging

# Set project root in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

from webhook_server import run_async_execution, handle_aistats
from ai_trading import db_logger
import order_manager

class MockMessage:
    def __init__(self, text):
        self.text = text
        self.chat = MockChat()

class MockChat:
    def __init__(self):
        self.id = 123456

class MockBot:
    def __init__(self):
        self.replies = []

    def reply_to(self, message, text, parse_mode=None):
        self.replies.append(text)
        print(f"\n📢 [MOCK TELEGRAM BOT REPLY]:\n{text}\n")

def test_dynamic_parameters_integration():
    print("🚀 MEMULAI PENGUJIAN INTEGRASI PARAMETER DINAMIS...")
    
    # 1. Setup Environment & DB Uji Coba
    os.environ["TELEGRAM_ADMIN_ID"] = "123456"
    os.environ["PAPER_MODE"] = "True"
    os.environ["USE_DEMO"] = "True"
    
    original_db = db_logger.DB_PATH
    db_logger.DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ai_trading", "test_ai_logs.db")
    if os.path.exists(db_logger.DB_PATH):
        os.remove(db_logger.DB_PATH)
        
    db_logger.init_db()
    
    # 2. Mock order_manager.execute_signal untuk merekam parameter yang masuk
    captured_execution_args = []
    def mock_execute_signal(data):
        captured_execution_args.append(data)
        # return dummy success
        return {"status": "success_paper", "symbol": data.get("symbol")}
        
    original_execute_signal = order_manager.execute_signal
    order_manager.execute_signal = mock_execute_signal
    
    try:
        # Mock global bot
        import webhook_server
        original_bot = webhook_server.bot
        mock_bot = MockBot()
        webhook_server.bot = mock_bot
        
        # 3. Jalankan Eksekusi Webhook dengan input lilin mock bullish (supaya disetujui AI)
        from ai_trading.test_filter import generate_mock_klines
        mock_klines = generate_mock_klines(65000, 67000)
        
        # Inject mock_klines ke validate_signal agar tidak hit API BingX langsung
        import ai_trading.gemini_filter
        original_validate_signal = ai_trading.gemini_filter.validate_signal
        
        def mock_validate_signal(pair, action, price, sl, tp1, tp2, mock_klines=None):
            # Selalu panggil dengan mock klines bullish yang sudah didefinisikan
            return original_validate_signal(pair, action, price, sl, tp1, tp2, mock_klines=mock_klines)
            
        ai_trading.gemini_filter.validate_signal = lambda *args, **kwargs: original_validate_signal(*args, mock_klines=mock_klines, **kwargs)
        
        print("\nKirim sinyal simulasi BUY BTC-USDT...")
        run_async_execution(
            data={},
            pair="BTC-USDT",
            signal="BUY",
            price=67000.0,
            sl=65500.0,
            tp1=69000.0,
            tp2=70000.0,
            tp3=0.0,
            tp4=0.0,
            TG_TOKEN="",
            TG_CHAT_ID=""
        )
        
        # Tunggu eksekusi asinkron selesai
        time.sleep(12)
        
        # 4. Verifikasi parameter hasil timpaan (override) AI
        assert len(captured_execution_args) == 1, "Sinyal tidak sampai ke order manager!"
        executed_data = captured_execution_args[0]
        print(f"\n📊 PARAMETER YANG DIKIRIM KE BURSA: {executed_data}")
        
        # Lilin bullish harus disetujui AI dan parameter dinamis di-override
        assert executed_data["sl"] != 65500.0, "Stop Loss asli TV tidak di-override oleh AI!"
        assert executed_data["leverage"] is not None, "Leverage saran AI tidak diteruskan!"
        print(f"✅ OVERWRITE SUKSES! SL: {executed_data['sl']} | TP1: {executed_data['tp1']} | TP2: {executed_data['tp2']} | Leverage: {executed_data['leverage']}")
        
        # 5. Verifikasi isi Database
        print("\nMemverifikasi perekaman database...")
        recent = db_logger.get_recent_logs(limit=1)
        assert len(recent) == 1, "Log database kosong!"
        log_entry = recent[0]
        
        print(f"Log Database: {log_entry}")
        assert log_entry["suggested_sl"] is not None, "Kolom suggested_sl bernilai kosong!"
        assert log_entry["suggested_leverage"] is not None, "Kolom suggested_leverage bernilai kosong!"
        print("✅ PEREKAMAN SARAN PARAMETER AI DI DATABASE SUKSES!")
        
        # 6. Verifikasi Notifikasi Telegram
        assert len(mock_bot.replies) == 1, "Bot Telegram tidak membalas!"
        reply_content = mock_bot.replies[0]
        print(f"\n📢 ISI NOTIFIKASI TELEGRAM:\n{reply_content}")
        
        assert "~~`65500.0`" in reply_content, "Notifikasi Telegram tidak menunjukkan coretan parameter asli!"
        assert "🧠" in reply_content, "Notifikasi Telegram tidak memiliki emoji indikator parameter AI!"
        print("✅ FORMAT NOTIFIKASI TELEGRAM BERHASIL DIFILTER!")
        
        print("\n✅ PENGUJIAN INTEGRASI PARAMETER DINAMIS 100% SUKSES!")
        
    finally:
        # Kembalikan mock dan bersihkan file
        if 'original_execute_signal' in locals():
            order_manager.execute_signal = original_execute_signal
        if 'original_bot' in locals():
            webhook_server.bot = original_bot
        if 'original_validate_signal' in locals():
            ai_trading.gemini_filter.validate_signal = original_validate_signal
        db_logger.DB_PATH = original_db
        test_db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ai_trading", "test_ai_logs.db")
        if os.path.exists(test_db_path):
            os.remove(test_db_path)

if __name__ == "__main__":
    test_dynamic_parameters_integration()
