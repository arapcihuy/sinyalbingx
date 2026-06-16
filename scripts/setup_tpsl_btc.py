import os
import sys
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bingx_client as bx

symbol = "BTC-USDT"
side = "SHORT"
sl_side = "BUY"  # Untuk menutup SHORT, kita BUY
sl_price = 81780.8

tps = [
    78003.0,
    77247.4,
    76240.0,
    74225.2
]

print(f"Mencari posisi {symbol} aktif...")
positions = bx.get_open_positions(symbol)
actual_pos = next((p for p in positions if p.get("positionSide") == side), None)

if not actual_pos:
    print("❌ Posisi BTC-USDT SHORT tidak ditemukan!")
    sys.exit(1)

amt = abs(float(actual_pos.get("positionAmt", 0)))
print(f"✅ Posisi ditemukan. Total Quantity: {amt}")

print("🧹 Menghapus SEMUA order lama yang menumpuk...")
bx.cancel_all_orders(symbol)
time.sleep(1)

print(f"🛑 Memasang Stop Loss di {sl_price}...")
sl_res = bx._request("POST", "/openApi/swap/v2/trade/order", {
    "symbol": symbol, "side": sl_side, "positionSide": side,
    "type": "STOP_MARKET", "stopPrice": sl_price, "quantity": amt
})
print("Respon SL:", sl_res)

import order_manager

# Pasang TP dibagi rata
tp_qty_base = order_manager._round_qty(amt / len(tps), symbol)
remaining_qty = amt

for i, tp_price in enumerate(tps):
    is_last = (i == len(tps) - 1)
    qty = remaining_qty if is_last else tp_qty_base
    remaining_qty -= qty
    
    print(f"🎯 Memasang TP{i+1} di {tp_price} (Qty: {qty})...")
    tp_res = bx._request("POST", "/openApi/swap/v2/trade/order", {
        "symbol": symbol, "side": sl_side, "positionSide": side,
        "type": "TAKE_PROFIT_MARKET", "stopPrice": tp_price, "quantity": qty
    })
    print(f"Respon TP{i+1}:", tp_res)

print("🎉 Selesai! Silakan cek /status di Telegram.")
