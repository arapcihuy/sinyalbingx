import os
from dotenv import load_dotenv
load_dotenv()
import bingx_client as bx
import time

symbol = "SOL-USDT"

def cleanup_sol_only():
    print(f"=== MEMULAI PEMBERSIHAN KHUSUS TP/SL SOL-USDT ===")
    
    # 1. Ambil order aktif khusus untuk SOL-USDT saja
    orders_res = bx._request('GET', '/openApi/swap/v2/trade/openOrders', {'symbol': symbol, 'pageSize': 100})
    
    if orders_res.get("code") == 0:
        orders = orders_res.get("data", {}).get("orders", [])
        print(f"Ditemukan {len(orders)} order gantung SOL-USDT di bursa.")
        
        # 2. Hapus satu per satu
        for o in orders:
            oid = o.get("orderId")
            res = bx._request('DELETE', '/openApi/swap/v2/trade/order', {'symbol': symbol, 'orderId': oid})
            print(f"  -> Cancel {o.get('type')} @ {o.get('stopPrice')} (ID: {oid}): {res.get('msg', 'ok')}")
            time.sleep(0.3)
            
        print("\n=== PEMBERSIHAN SELESAI: SOL-USDT BERSIH ===")
    elif orders_res.get("code") == 100410:
        print("🚨 BingX API Rate Limit masih aktif. Harap tunggu unblock jam 14:40:17 WIB.")
    else:
        print(f"❌ Gagal mendapatkan order: {orders_res.get('msg')}")

if __name__ == "__main__":
    cleanup_sol_only()
