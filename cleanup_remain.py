import os
from dotenv import load_dotenv
load_dotenv()
import bingx_client as bx

symbol = "BTC-USDT"

# Target orders yang BENAR (dari sinyal TV)
target = {62953.5, 64794.1, 65162.3, 65653.1, 66634.8}

orders = bx._request('GET', '/openApi/swap/v2/trade/openOrders', {'symbol': symbol, 'pageSize': 20})
for o in orders.get('data', {}).get('orders', []):
    sp = float(o['stopPrice'])
    if sp not in target:
        oid = o['orderId']
        res = bx._request('DELETE', '/openApi/swap/v2/trade/order', {'symbol': symbol, 'orderId': oid})
        print(f"Cancel sisa {o['type']} {sp}: {res.get('code')}")

import time
time.sleep(1)

# Verify final
final = bx._request('GET', '/openApi/swap/v2/trade/openOrders', {'symbol': symbol, 'pageSize': 20})
final_orders = final.get('data', {}).get('orders', [])
print(f"\nFinal: {len(final_orders)} orders")
for o in final_orders:
    print(f"  {o['type']:20s} stopPrice={o['stopPrice']:>10s} qty={o['origQty']}")