import requests
import json
import os
from dotenv import load_dotenv
import time

load_dotenv()

# Gunakan URL Railway Anda jika ingin mengetes versi online
# contoh: WEBHOOK_URL = "https://namaproject.up.railway.app/webhook"
WEBHOOK_URL = "https://sinyal-bingx-production.up.railway.app/webhook" 

SECRET = os.getenv("WEBHOOK_SECRET")

# Data simulasi sinyal dari TradingView
payload = {
    "secret": SECRET,
    "symbol": "BTC-USDT",
    "action": "LONG",
    "price": 60000.50, # Harga masuk (opsional)
    "sl": 59000.00,    # Stop Loss
    "tp1": 61000.00,   # Take Profit 1
    "tp1_qty": 0.5,    # 50%
    "tp2": 62000.00,   # Take Profit 2
    "tp2_qty": 0.5,    # 50%
}

print(f"Mengirim sinyal tes ke: {WEBHOOK_URL}")
print(f"Payload: {json.dumps(payload, indent=2)}")

try:
    response = requests.post(
        WEBHOOK_URL, 
        json=payload,
        headers={"Content-Type": "application/json"}
    )
    
    print("\n--- HASIL ---")
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.text}")
except Exception as e:
    print(f"\n❌ Gagal mengirim sinyal: {e}")
    print("Pastikan bot (webhook_server.py) sedang berjalan di terminal lain jika mengetes lokal.")
