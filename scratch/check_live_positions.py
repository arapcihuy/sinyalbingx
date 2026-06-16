import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))
import bingx_client as bx
import state_manager

print("🔍 Memeriksa status trading mode...")
# Paksa check script menggunakan status LIVE (Uang Asli)
state_manager.set_mode(False, False, "TESTING_LIVE_ACCOUNT")
mode = state_manager.get_trading_mode()
print(f"Mode dipaksa ke: {mode}")

print("\n--- POSISI AKTIF DI BINGX (PERPETUAL FUTURES) ---")
try:
    positions = bx.get_open_positions()
    if positions:
        for pos in positions:
            print(f"🪙 Symbol: {pos.get('symbol')}")
            print(f"   Side: {pos.get('positionSide')}")
            print(f"   Amount: {pos.get('positionAmt')}")
            print(f"   Entry Price: {pos.get('avgPrice')}")
            print(f"   Leverage: {pos.get('leverage')}x")
            print(f"   Unrealized PnL: {pos.get('unrealizedProfit')} USDT")
    else:
        print("📭 Tidak ada posisi aktif.")
except Exception as e:
    print(f"❌ Gagal mengambil posisi: {e}")

print("\n--- ORDER AKTIF DI BINGX ---")
try:
    for symbol in ["BTC-USDT", "ETH-USDT"]:
        orders_res = bx._request("GET", "/openApi/swap/v2/trade/openOrders", {"symbol": symbol})
        orders = orders_res.get("data", [])
        if isinstance(orders, dict):
            orders = orders.get("orders", [])
        
        if orders:
            print(f"📌 {symbol} Open Orders:")
            for o in orders:
                print(f"   - ID: {o.get('orderId')} | Type: {o.get('type')} | Side: {o.get('side')} | Price: {o.get('price')} | StopPrice: {o.get('stopPrice')}")
        else:
            print(f"📭 Tidak ada order aktif untuk {symbol}")
except Exception as e:
    print(f"❌ Gagal mengambil open orders: {e}")
