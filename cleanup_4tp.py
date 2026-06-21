import os
from dotenv import load_dotenv
load_dotenv()
import bingx_client as bx

symbol = "BTC-USDT"

# Get all open orders
orders = bx._request('GET', '/openApi/swap/v2/trade/openOrders', {'symbol': symbol, 'pageSize': 20})
data = orders.get('data', {})
all_orders = data.get('orders', [])

print(f"Cancelling {len(all_orders)} orders...")

# Cancel one by one
for o in all_orders:
    oid = o.get('orderId')
    res = bx._request('DELETE', '/openApi/swap/v2/trade/order', {'symbol': symbol, 'orderId': oid})
    print(f"Cancel {oid}: {res.get('msg', 'ok')}")

# Re-place clean 4 TP + 1 SL
entry = 64399.1
qty = 0.002
sl_price = 59000.0

tp_list = [
    (66009.1, 0.0007),
    (67941.1, 0.0006),
    (70839.0, 0.0004),
    (74059.0, 0.0003),
]

print("\nPlacing clean orders...")
# Place SL
bx._request("POST", "/openApi/swap/v2/trade/order", {
    "symbol": symbol, "side": "SELL", "positionSide": "LONG",
    "type": "STOP_MARKET", "quantity": str(qty),
    "stopPrice": str(sl_price), "price": "0", "workingType": "MARK_PRICE"
})

# Place 4 TP
for tp, tq in tp_list:
    bx._request("POST", "/openApi/swap/v2/trade/order", {
        "symbol": symbol, "side": "SELL", "positionSide": "LONG",
        "type": "TAKE_PROFIT_MARKET", "quantity": str(tq),
        "stopPrice": str(tp), "price": "0", "workingType": "MARK_PRICE"
    })

# Verify
final = bx._request('GET', '/openApi/swap/v2/trade/openOrders', {'symbol': symbol, 'pageSize': 20})
final_data = final.get('data', {}).get('orders', [])
print(f"\nFinal open orders: {len(final_data)}")
for o in final_data:
    print(f"{o.get('type')} {o.get('stopPrice')} qty {o.get('origQty')}")
