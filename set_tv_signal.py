import os
from dotenv import load_dotenv
load_dotenv()
import bingx_client as bx

symbol = "BTC-USDT"
qty = 0.002

# Dari sinyal TV jam 11:00
sl_price = 62953.5
tp1 = 64794.1
tp2 = 65162.3
tp3 = 65653.1
tp4 = 66634.8

tp_list = [
    (tp1, round(qty * 0.35, 4)),  # 35%
    (tp2, round(qty * 0.30, 4)),  # 30%
    (tp3, round(qty * 0.20, 4)),  # 20%
    (tp4, round(qty * 0.15, 4)),  # 15%
]

print(f"=== SET TP/SL DARI SINYAL TV JAM 11:00 ===")
print(f"SL:  {sl_price}")
print(f"TP1: {tp1} (35%)")
print(f"TP2: {tp2} (30%)")
print(f"TP3: {tp3} (20%)")
print(f"TP4: {tp4} (15%)")

# 1. Cancel all open orders
cancel = bx._request("DELETE", "/openApi/swap/v2/trade/allOpenOrders", {"symbol": symbol})
print(f"\nCancel all: {cancel}")

# Verify cancel
import time
time.sleep(1)
check = bx._request('GET', '/openApi/swap/v2/trade/openOrders', {'symbol': symbol, 'pageSize': 20})
remaining = len(check.get('data', {}).get('orders', []))
if remaining > 0:
    print(f"Still {remaining} orders, cancelling by ID...")
    for o in check.get('data', {}).get('orders', []):
        bx._request('DELETE', '/openApi/swap/v2/trade/order', {'symbol': symbol, 'orderId': o['orderId']})
    time.sleep(1)

# 2. Place SL
r_sl = bx._request("POST", "/openApi/swap/v2/trade/order", {
    "symbol": symbol, "side": "SELL", "positionSide": "LONG",
    "type": "STOP_MARKET", "quantity": str(qty),
    "stopPrice": str(sl_price), "price": "0", "workingType": "MARK_PRICE"
})
print(f"\nSL: {r_sl.get('code')} - {r_sl.get('msg', '')}")
if r_sl.get('data', {}).get('order'):
    print(f"  stopPrice={r_sl['data']['order']['stopPrice']} qty={r_sl['data']['order']['quantity']}")

# 3. Place 4 TPs
for i, (tp, tq) in enumerate(tp_list, 1):
    time.sleep(0.3)
    res = bx._request("POST", "/openApi/swap/v2/trade/order", {
        "symbol": symbol, "side": "SELL", "positionSide": "LONG",
        "type": "TAKE_PROFIT_MARKET", "quantity": str(tq),
        "stopPrice": str(tp), "price": "0", "workingType": "MARK_PRICE"
    })
    print(f"TP{i}: {res.get('code')} - {res.get('msg', '')}")
    if res.get('data', {}).get('order'):
        print(f"  stopPrice={res['data']['order']['stopPrice']} qty={res['data']['order']['quantity']}")

# 4. Verify final
time.sleep(1)
final = bx._request('GET', '/openApi/swap/v2/trade/openOrders', {'symbol': symbol, 'pageSize': 20})
final_orders = final.get('data', {}).get('orders', [])
print(f"\n=== FINAL: {len(final_orders)} orders ===")
for o in final_orders:
    print(f"  {o['type']:20s} stopPrice={o['stopPrice']:>10s} qty={o['origQty']}")