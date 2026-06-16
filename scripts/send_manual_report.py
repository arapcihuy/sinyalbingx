import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add current directory to path
sys.path.append(os.getcwd())

import webhook_server

class DummyMsg:
    chat = type('obj', (object,), {'id': os.getenv("TELEGRAM_CHAT_ID")})

if __name__ == "__main__":
    print(f"Mengirim laporan manual ke Chat ID: {os.getenv('TELEGRAM_CHAT_ID')}...")
    try:
        webhook_server.report_cmd(DummyMsg())
        print("\n✅ Laporan berhasil dikirim ke Telegram!")
    except Exception as e:
        print(f"\n❌ Gagal mengirim laporan: {e}")
        print("Pastikan koneksi internet Anda aktif dan token bot benar.")
