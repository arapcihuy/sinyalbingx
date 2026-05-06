import os
from dotenv import load_dotenv
import order_manager
import bingx_client as bx

load_dotenv()

payload = {
    "symbol": "BTC-USDT",
    "action": "LONG",
    "price": 60000.50,
    "sl": 59000.00,
    "tp1": 61000.00,
    "leverage": 10
}

print("Mencoba eksekusi sinyal...")
try:
    res = order_manager.execute_signal(payload)
    print("Berhasil:", res)
except Exception as e:
    print("Error:", e)
    
print("\nLog terakhir:")
try:
    with open("bot.log", "r") as f:
        print("".join(f.readlines()[-10:]))
except:
    pass
