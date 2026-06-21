import sys
sys.path.insert(0, '.')
import bingx_client as bx
import os
from dotenv import load_dotenv
load_dotenv()

# Cek posisi
positions = bx.get_open_positions()
if positions:
    for p in positions:
        if float(p.get('positionAmt', 0)) != 0:
            print(f"POSISI: {p['symbol']} {p['positionSide']} qty={p['positionAmt']} entry={p['avgPrice']}")
else:
    print("Tidak ada posisi")

# Cek open orders
for symbol in ['BTC-USDT', 'ETH-USDT']:
    orders = bx._request('GET', '/openApi/swap/v2/trade/openOrders', {'symbol': symbol})
    data = orders.get('data', [])
    if isinstance(data, dict):
        data = data.get('orders', [])
    if isinstance(data, list) and len(data) > 0:
        print(f'\nORDERS {symbol}: {len(data)}')
        for o in data:
            print(f"  {o.get('type')} | side={o.get('side')} | stopPrice={o.get('stopPrice')} | qty={o.get('quantity')} | orderId={o.get('orderId')}")
    else:
        print(f'\nNo orders for {symbol}')