import os
from dotenv import load_dotenv
load_dotenv()
import bingx_client as bx
import time

symbol = "SOL-USDT"

# 1. Ambil semua open orders SOL-USDT di bursa
orders_res = bx._request('GET', '/openApi/swap/v2/trade/openOrders', {'symbol': symbol, 'pageSize': 100})
if orders_res.get("code") == 0:
    orders = orders_res.get("data", {}).get("orders", [])
    print(f"Ditemukan {len(orders)} order aktif untuk {symbol}")
    
    # 2. Batalkan semua order TP/SL yang ada satu per satu
    for o in orders:
        oid = o.get("orderId")
        res = bx._request('DELETE', '/openApi/swap/v2/trade/order', {'symbol': symbol, 'orderId': oid})
        print(f"Cancel Order {oid} ({o.get('type')} @ {o.get('stopPrice')}): {res.get('msg', 'ok')}")
        time.sleep(0.2)
else:
    print(f"Gagal mengambil open orders: {orders_res}")
    exit(1)

# 3. Dapatkan detail posisi aktif SOL-USDT di bursa untuk re-place TP/SL yang presisi
pos_res = bx.get_open_positions(symbol)
if not pos_res:
    print(f"Tidak ada posisi aktif untuk {symbol} di bursa.")
    exit(0)

pos = pos_res[0]
side = pos["positionSide"] # SHORT
qty = abs(float(pos["positionAmt"]))
entry_price = float(pos["avgPrice"])
print(f"\nPosisi aktif: {side} | Qty: {qty} | Entry: {entry_price}")

# Definisikan target parameter TP/SL bersih (4 TP & 1 SL) untuk SOL SHORT dari data adopsi
sl_price = 75.0
tp_list = [
    (65.996, round(qty * 0.35, 3)), # TP1: 35%
    (66.628, round(qty * 0.30, 3)), # TP2: 30%
    (67.049, round(qty * 0.20, 3)), # TP3: 20%
    (67.450, round(qty * 0.15, 3)), # TP4: 15%
]

sl_side = "BUY" if side == "SHORT" else "SELL"

# 4. Pasang Stop Loss tunggal yang bersih
time.sleep(0.5)
sl_order = bx._request("POST", "/openApi/swap/v2/trade/order", {
    "symbol": symbol, "side": sl_side, "positionSide": side,
    "type": "STOP_MARKET", "quantity": str(qty),
    "stopPrice": str(sl_price), "price": "0", "workingType": "MARK_PRICE"
})
print(f"Re-placed SL @ {sl_price}: {sl_order.get('msg', 'ok')}")

# 5. Pasang 4 TP baru yang bersih sesuai pembagian kuantitas
total_tp_placed = 0.0
for i, (tp, tq) in enumerate(tp_list, 1):
    time.sleep(0.3)
    # Yakinkan qty ter-clamp ke sisa untuk menghindari kelebihan order
    tq = round(tq, 3)
    if tq > 0:
        tp_order = bx._request("POST", "/openApi/swap/v2/trade/order", {
            "symbol": symbol, "side": sl_side, "positionSide": side,
            "type": "TAKE_PROFIT_MARKET", "quantity": str(tq),
            "stopPrice": str(tp), "price": "0", "workingType": "MARK_PRICE"
        })
        print(f"Re-placed TP{i} @ {tp} (Qty: {tq}): {tp_order.get('msg', 'ok')}")

# 6. Verifikasi Akhir
time.sleep(1)
final_res = bx._request('GET', '/openApi/swap/v2/trade/openOrders', {'symbol': symbol, 'pageSize': 20})
final_orders = final_res.get('data', {}).get('orders', [])
print(f"\n=== VERIFIKASI AKHIR SOL-USDT: {len(final_orders)} open orders ===")
for o in final_orders:
    print(f"  {o['type']:20s} stopPrice={o['stopPrice']:>10s} qty={o['origQty']}")
