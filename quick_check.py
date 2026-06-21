import sys
sys.path.insert(0, '.')
import bingx_client as bx
import os
from dotenv import load_dotenv
load_dotenv()

positions = bx.get_open_positions()
if positions:
    for p in positions:
        amt = float(p.get('positionAmt', 0))
        if amt != 0:
            print(f'POS: {p["symbol"]} {p["positionSide"]} qty={amt} entry={p["avgPrice"]}')

for sym in ['BTC-USDT', 'ETH-USDT']:
    orders = bx._request('GET', '/openApi/swap/v2/trade/openOrders', {'symbol': sym})
    data = orders.get('data', [])
    if isinstance(data, dict):
        data = data.get('orders', [])
    if isinstance(data, list) and data:
        tp_count = sum(1 for o in data if 'TAKE_PROFIT' in o.get('type',''))
        sl_count = sum(1 for o in data if 'STOP' in o.get('type',''))
        print(f'{sym}: {len(data)} orders (TP={tp_count}, SL={sl_count})')
    else:
        print(f'{sym}: no orders')