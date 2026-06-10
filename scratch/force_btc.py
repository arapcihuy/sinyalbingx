import os
import sys
# Make sure we can import from parent directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import bingx_client as bx
import order_manager

def main():
    symbol = "BTC-USDT"
    curr_price = bx.get_current_price(symbol)
    print(f"Current {symbol} Price: {curr_price}")

    # Set parameter untuk posisi SHORT (SELL)
    # SL berdasarkan sinyal gambar
    sl_price = 81780.8158
    
    # 4 TP (Take Profit) berdasarkan sinyal gambar
    tp1 = 78003.0335
    tp2 = 77247.477
    tp3 = 76240.0684
    tp4 = 74225.2512

    payload = {
        "action": "SELL",
        "symbol": symbol,
        "price": curr_price,
        "leverage": 20, 
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "tp4": tp4,
        "qty_tp1": 25,
        "qty_tp2": 25,
        "qty_tp3": 25,
        "qty_tp4": 25,
        "sl": sl_price
    }

    try:
        print(f"Mengeksekusi sinyal dengan payload: {payload}")
        res = order_manager.execute_signal(payload)
        print("SUCCESS! Response:", res)
    except Exception as e:
        print("FAILED:", e)

if __name__ == "__main__":
    main()
