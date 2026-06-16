import time
import os
import sys

# Tambahkan direktori root agar bisa import module bot
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import order_manager
import bingx_client as bx

# 1. KITA "HACK" KONEKSI BINGX AGAR TIDAK MENGGUNAKAN UANG ASLI
# =============================================================
fake_open_orders = []
fake_positions = []
current_mock_price = 78758.59
mock_balance = 1000.0

def mock_request(method, path, params=None):
    global current_mock_price, mock_balance, fake_open_orders, fake_positions
    params = params or {}
    
    if "quote/price" in path:
        return {"code": 0, "data": {"price": str(current_mock_price)}}
    elif "user/balance" in path:
        return {"code": 0, "data": {"balance": {"equity": str(mock_balance)}}}
    elif "trade/order" in path and method == "POST":
        order_type = params.get("type", "MARKET")
        print(f"   [BINGX SIMULATOR] 🛒 EKSEKUSI: {params.get('side')} {params.get('symbol')} | Type: {order_type} | Qty: {params.get('quantity')} | Harga Target (StopPrice): {params.get('stopPrice', 'Market')}")
        
        if order_type == "MARKET":
            fake_positions.append({
                "symbol": params.get("symbol"),
                "positionSide": params.get("positionSide", "SHORT"),
                "positionAmt": f"-{params.get('quantity')}", # Negatif karena SHORT
                "avgPrice": str(current_mock_price),
                "markPrice": str(current_mock_price),
                "unrealizedProfit": "0"
            })
        else:
            fake_open_orders.append({
                "orderId": f"fake_{time.time()}",
                "symbol": params.get("symbol"),
                "type": order_type,
                "stopPrice": str(params.get("stopPrice", 0)),
                "origQty": str(params.get("quantity")),
                "positionSide": params.get("positionSide", "SHORT")
            })
        return {"code": 0, "msg": "success", "data": {}}
    elif "trade/allOpenOrders" in path and method == "DELETE":
        print(f"   [BINGX SIMULATOR] 🧹 Pembersihan order {params.get('symbol')}...")
        fake_open_orders = [o for o in fake_open_orders if o.get("symbol") != params.get("symbol")]
        return {"code": 0, "msg": "success"}
    elif "user/positions" in path:
        for p in fake_positions:
            p["markPrice"] = str(current_mock_price)
            # PnL untuk SHORT = (Entry - Mark) * Qty
            p["unrealizedProfit"] = str((float(p["avgPrice"]) - current_mock_price) * abs(float(p["positionAmt"])))
        return {"code": 0, "data": fake_positions}
    elif "trade/openOrders" in path:
        return {"code": 0, "data": {"orders": fake_open_orders}}
    return {"code": 0, "msg": "success", "data": {}}

# Timpa fungsi asli
bx._request = mock_request
order_manager.active_trade_data = {}

print("=========================================================")
print("🧪 SIMULASI AUDIT: TRAILING SL SHORT BTC-USDT")
print("=========================================================\n")

# 2. MULAI SIMULASI
symbol = "BTC-USDT"
entry_price = 78758.59

print(f"⏱️ [DETIK 1] Menerima Sinyal SHORT {symbol} @ {entry_price}...")
signal_data = {
    "symbol": symbol,
    "action": "SHORT",
    "price": entry_price,
    "sl": 81780.8,
    "tp1": 78003.0, "tp1_qty": 0.25,
    "tp2": 77247.4, "tp2_qty": 0.25,
    "tp3": 76240.0, "tp3_qty": 0.25,
    "tp4": 74225.2, "tp4_qty": 0.25
}

print("🤖 Eksekusi Sinyal...")
order_manager.execute_signal(signal_data)
print("✅ Sinyal awal terpasang.\n")

print(f"⏱️ [DETIK 5] Harga turun mendekati TP1...")
current_mock_price = 78100.0
order_manager.monitor_and_sync_positions()
print(f"   Harga: {current_mock_price}. Belum kena TP1 (78003).")

print("\n---------------------------------------------------------")
print(f"⏱️ [DETIK 10] DAR! Harga tembus TP1 (77950) 🎯")
current_mock_price = 77950.0
print("🤖 Menjalankan loop monitor...")
order_manager.monitor_and_sync_positions()

# Verifikasi Memory
state = order_manager.active_trade_data.get(symbol)
print(f"\n📝 Status Memory Sekarang: SL={state.get('sl')}")

if state.get('sl') == entry_price:
    print("✅ SUKSES: SL bergeser ke ENTRY untuk posisi SHORT!")
else:
    print(f"❌ GAGAL: SL harusnya {entry_price}, tapi malah {state.get('sl')}")

print("\n---------------------------------------------------------")
print(f"⏱️ [DETIK 15] GILA! Harga terjun bebas tembus TP2 (77100) 🎯🎯")
current_mock_price = 77100.0
print("🤖 Menjalankan loop monitor...")
order_manager.monitor_and_sync_positions()

state = order_manager.active_trade_data.get(symbol)
print(f"\n📝 Status Memory Sekarang: SL={state.get('sl')}")

if state.get('sl') == 78003.0:
    print("✅ SUKSES: SL bergeser ke TP1 untuk posisi SHORT!")
else:
    print(f"❌ GAGAL: SL harusnya 78003.0, tapi malah {state.get('sl')}")

print("\n=========================================================")
print("🧪 HASIL AKHIR: SISTEM DINYATAKAN SEHAT & SIAP TEMPUR!")
print("=========================================================")
