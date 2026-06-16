import time
import os
import sys
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

# Tambahkan direktori root agar bisa import module bot
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import order_manager
import bingx_client as bx

print("=========================================================")
print("🧪 MEMULAI SIMULATOR TRADING BOT (UANG PALSU / AMAN 100%)")
print("=========================================================\n")

# 1. KITA "HACK" KONEKSI BINGX AGAR TIDAK MENGGUNAKAN UANG ASLI
# =============================================================
fake_open_orders = []
fake_positions = []
current_mock_price = 60000.0
mock_balance = 100.0

def mock_request(method, path, params=None):
    global current_mock_price, mock_balance, fake_open_orders, fake_positions
    params = params or {}
    
    # Pura-pura ambil harga
    if "quote/price" in path:
        return {"code": 0, "data": {"price": str(current_mock_price)}}
    
    # Pura-pura ambil balance
    elif "user/balance" in path:
        return {"code": 0, "data": {"balance": {"equity": str(mock_balance)}}}
    
    # Pura-pura pasang order
    elif "trade/order" in path and method == "POST":
        order_type = params.get("type", "MARKET")
        print(f"   [BINGX SIMULATOR] 🛒 Menjalankan eksekusi: {params.get('side')} {params.get('symbol')} | Type: {order_type} | Qty: {params.get('quantity')} | Harga Target (StopPrice): {params.get('stopPrice', 'Market')}")
        
        if order_type == "MARKET":
            # Tambahkan ke posisi fiktif
            fake_positions.append({
                "symbol": params.get("symbol"),
                "positionSide": params.get("positionSide", "LONG"),
                "positionAmt": params.get("quantity"),
                "avgPrice": str(current_mock_price),
                "markPrice": str(current_mock_price)
            })
        else:
            # Tambahkan ke open orders fiktif (TP/SL)
            fake_open_orders.append({
                "orderId": f"fake_{time.time()}",
                "symbol": params.get("symbol"),
                "type": order_type,
                "stopPrice": params.get("stopPrice", 0),
                "origQty": params.get("quantity")
            })
        return {"code": 0, "msg": "success"}
    
    # Pura-pura batalkan semua order
    elif "trade/allOpenOrders" in path and method == "DELETE":
        print(f"   [BINGX SIMULATOR] 🧹 Menghapus semua order aktif untuk {params.get('symbol')}...")
        fake_open_orders = [o for o in fake_open_orders if o.get("symbol") != params.get("symbol")]
        return {"code": 0, "msg": "success"}
    
    # Pura-pura ambil posisi aktif
    elif "user/positions" in path:
        # Update markPrice dynamically
        for p in fake_positions:
            p["markPrice"] = str(current_mock_price)
        return {"code": 0, "data": fake_positions}
    
    # Pura-pura baca order aktif (Untuk Auto-Recovery)
    elif "trade/openOrders" in path:
        return {"code": 0, "data": {"orders": fake_open_orders}}
    
    # Fungsi lain bypass saja
    return {"code": 0, "msg": "success", "data": {}}

# Timpa fungsi asli dengan fungsi simulator kita
bx._request = mock_request

# Kosongkan memori bot agar murni dari awal
order_manager.active_trade_data = {}

# 2. MULAI SIMULASI
# =============================================================
symbol = "BTC-USDT"
entry_price = 60000.0

print(f"⏱️ [DETIK 1] Menerima Sinyal Telegram (LONG {symbol}) di harga {entry_price}...")

# Data Sinyal Fiktif
signal_data = {
    "symbol": symbol,
    "action": "LONG",
    "price": entry_price,
    "sl": 59000.0,
    "tp1": 61000.0,
    "tp2": 62000.0,
    "tp3": 63000.0,
    "tp4": 64000.0
}

# Jalankan eksekusi (seperti saat webhook masuk)
try:
    print("🤖 Mengeksekusi Sinyal...")
    order_manager.execute_signal(signal_data)
    print("✅ Sinyal berhasil dieksekusi tanpa error!\n")
except Exception as e:
    print(f"❌ Terjadi error saat entry: {e}")
    sys.exit(1)

print("📝 Memori Bot Saat Ini (active_trade_data):")
print(order_manager.active_trade_data)
print("\n---------------------------------------------------------")

print(f"⏱️ [DETIK 5] Harga mulai bergerak NAIK...")
current_mock_price = 60500.0
order_manager.monitor_and_sync_positions() # Panggil loop monitor
print(f"   Harga sekarang: {current_mock_price}. Belum kena TP1 (61000.0). SL saat ini: {order_manager.active_trade_data.get(symbol, {}).get('sl')}")

print("\n---------------------------------------------------------")
print(f"⏱️ [DETIK 10] BINGO! Harga tembus TP1 (61200.0) 🎯")
current_mock_price = 61200.0

print("🤖 Menjalankan loop monitor_and_sync_positions...")
order_manager.monitor_and_sync_positions()
print(f"   SL saat ini setelah TP1 terlewati: {order_manager.active_trade_data.get(symbol, {}).get('sl')} (Harus 60000.0 - Entry)")

print("\n---------------------------------------------------------")
print(f"⏱️ [DETIK 15] BINGO! Harga tembus TP2 (62500.0) 🎯")
current_mock_price = 62500.0

print("🤖 Menjalankan loop monitor_and_sync_positions...")
order_manager.monitor_and_sync_positions()
print(f"   SL saat ini setelah TP2 terlewati: {order_manager.active_trade_data.get(symbol, {}).get('sl')} (Harus 61000.0 - TP1)")

print("\n✅ SIMULASI SELESAI. Cek log di atas apakah bot melakukan 'Menggeser SL' (Trailing SL).")
print("=========================================================")
