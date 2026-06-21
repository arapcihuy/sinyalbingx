import os
from dotenv import load_dotenv
load_dotenv()
import bingx_client as bx

symbol = "BTC-USDT"
entry = 64399.1
pos_side = "LONG"
qty = 0.002

# 1. Cancel semua open orders
cancel = bx._request("DELETE", "/openApi/swap/v2/trade/allOpenOrders", {"symbol": symbol})
print("Cancel:", cancel)

# 2. Gunakan SL dari sinyal TV
sl_price = 59000.0
print(f"\nWAJIB 4 TP - BTC-USDT LONG @ {entry}")
print(f"SL: {sl_price}")

# TP menggunakan persentase realistis (untuk BTC)
base_price = entry

# Persentase dari entry ke TP (drift)
tp1 = round(base_price * 1.025, 1)  # +2.5%
tp2 = round(base_price * 1.055, 1)  # +5.5%
tp3 = round(base_price * 1.100, 1)  # +10.0%
tp4 = round(base_price * 1.150, 1)  # +15.0%

# Bagi qty ke 4 TP
tp_qty1 = round(qty * 0.35, 4)  # 35%
tp_qty2 = round(qty * 0.30, 4)  # 30%
tp_qty3 = round(qty * 0.20, 4)  # 20%
tp_qty4 = round(qty * 0.15, 4)  # 15%

print(f"TP1: {tp1} qty {tp_qty1}")
print(f"TP2: {tp2} qty {tp_qty2}")
print(f"TP3: {tp3} qty {tp_qty3}")
print(f"TP4: {tp4} qty {tp_qty4}")

# 3. Pasang SL baru
r1 = bx._request("POST", "/openApi/swap/v2/trade/order", {
    "symbol": symbol, "side": "SELL", "positionSide": "LONG",
    "type": "STOP_MARKET", "quantity": str(qty),
    "stopPrice": str(sl_price), "price": "0",
    "workingType": "MARK_PRICE"
})
print(f"\nSL: {r1}")

# 4. Pasang 4 TP (semua > harga saat ini)
current = 63942.6
tp_pairs = [(tp1, tp_qty1), (tp2, tp_qty2), (tp3, tp_qty3), (tp4, tp_qty4)]
for i, (tp, tq) in enumerate(tp_pairs, 1):
    if tp > current:  # Validasi harga > current
        res = bx._request("POST", "/openApi/swap/v2/trade/order", {
            "symbol": symbol, "side": "SELL", "positionSide": "LONG",
            "type": "TAKE_PROFIT_MARKET", "quantity": str(tq),
            "stopPrice": str(tp), "price": "0",
            "workingType": "MARK_PRICE"
        })
        print(f"TP{i}: {res}")
    else:
        print(f"TP{i}: NO (harga {tp} < current {current})")
