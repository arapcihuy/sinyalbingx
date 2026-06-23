import os
from dotenv import load_dotenv
load_dotenv()
import bingx_client as bx
import time

def cleanup_all():
    print("=== MEMULAI PEMBERSIHAN TOTAL OPEN ORDERS ALL PAIRS ===")
    
    # List pair yang sering ditransaksikan untuk pengecekan granular jika allOpenOrders rate limit
    pairs = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT", "ADA-USDT", "XRP-USDT"]
    
    for symbol in pairs:
        print(f"\nMemeriksa open orders untuk {symbol}...")
        orders_res = bx._request('GET', '/openApi/swap/v2/trade/openOrders', {'symbol': symbol, 'pageSize': 100})
        
        if orders_res.get("code") == 0:
            orders = orders_res.get("data", {}).get("orders", [])
            print(f"Ditemukan {len(orders)} order aktif untuk {symbol}")
            
            for o in orders:
                oid = o.get("orderId")
                res = bx._request('DELETE', '/openApi/swap/v2/trade/order', {'symbol': symbol, 'orderId': oid})
                print(f"  -> Cancel {o.get('type')} @ {o.get('stopPrice')}: {res.get('msg', 'ok')}")
                time.sleep(0.3)
        elif orders_res.get("code") == 100410:
            print("🚨 Terdeteksi Rate Limit BingX API. Menunggu cooldown...")
            time.sleep(10)
        else:
            print(f"Gagal mengambil orders untuk {symbol}: {orders_res.get('msg')}")
            
    print("\n=== PEMBERSIHAN MASSAL SELESAI ===")

if __name__ == "__main__":
    cleanup_all()
