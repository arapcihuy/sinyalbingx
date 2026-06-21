import sys
sys.path.insert(0, '.')
import bingx_client as bx
import os
import time

def cancel_all_orders(symbol):
    print(f"Mengambil open orders untuk {symbol}...")
    orders = bx._request('GET', '/openApi/swap/v2/trade/openOrders', {'symbol': symbol})
    data = orders.get('data', [])
    if isinstance(data, dict):
        data = data.get('orders', [])
        
    if not isinstance(data, list) or len(data) == 0:
        print(f"Tidak ada open orders untuk {symbol}.")
        return

    print(f"Ditemukan {len(data)} open orders. Membatalkan...")
    for o in data:
        order_id = o.get("orderId")
        if order_id:
            res = bx._request('DELETE', '/openApi/swap/v2/trade/order', {'symbol': symbol, 'orderId': order_id})
            print(f"Cancel {order_id} ({o.get('type')} @ {o.get('stopPrice')}): {res.get('msg', 'OK')}")
            time.sleep(0.2)

cancel_all_orders('BTC-USDT')