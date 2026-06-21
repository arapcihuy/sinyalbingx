import os
from dotenv import load_dotenv
load_dotenv()
import bingx_client as bx

symbol = "BTC-USDT"
entry = 64399.1
qty = 0.002

# 1. Cancel per order ID (lebih reliable)
orders = bx._request("GET", "/openApi/swap/v2/trade/openOrders", {"symbol": symbol, "pageSize": 50})
order_ids = [o["orderId"] for o in orders.get("data", {}).get("orders", [])]
print(f"Found {len(order_ids)} orders: {order_ids}")

for oid in order_ids:
    r = bx._request("DELETE", "/openApi/swap/v2/trade/order", {"symbol": symbol, "orderId": str(oid)})
    print(f"Cancel {oid}: {r.get('code')} {r.get('msg')}")

# 2. Verify cancel
orders2 = bx._request("GET", "/openApi/swap/v2/trade/openOrders", {"symbol": symbol, "pageSize": 50})
remaining = orders2.get("data", {}).get("orders", [])
print(f"\nRemaining: {len(remaining)}")

# 3. Pasang ulang: 1 SL + 4 TP
sl_price = 59000.0
tp1 = round(entry * 1.025, 1)
tp2 = round(entry * 1.055, 1)
tp3 = round(entry * 1.100, 1)
tp4 = round(entry * 1.150, 1)
tp_qty1 = round(qty * 0.35, 4)
tp_qty2 = round(qty * 0.30, 4)
tp_qty3 = round(qty * 0.20, 4)
tp_qty4 = round(qty * 0.15, 4)

print(f"\nPasang ulang:")
print(f"SL: {sl_price}")
print(f"TP1: {tp1} qty {tp_qty1}")
print(f"TP2: {tp2} qty {tp_qty2}")
print(f"TP3: {tp3} qty {tp_qty3}")
print(f"TP4: {tp4} qty {tp_qty4}")

# SL
r = bx._request("POST", "/openApi/swap/v2/trade/order", {
    "symbol": symbol, "side": "SELL", "positionSide": "LONG",
    "type": "STOP_MARKET", "quantity": str(qty),
    "stopPrice": str(sl_price), "price": "0", "workingType": "MARK_PRICE"
})
print(f"SL: {r.get('code')} {r.get('msg')}")

# 4 TP
for i, (tp, tq) in enumerate([(tp1, tp_qty1), (tp2, tp_qty2), (tp3, tp_qty3), (tp4, tp_qty4)], 1):
    r = bx._request("POST", "/openApi/swap/v2/trade/order", {
        "symbol": symbol, "side": "SELL", "positionSide": "LONG",
        "type": "TAKE_PROFIT_MARKET", "quantity": str(tq),
        "stopPrice": str(tp), "price": "0", "workingType": "MARK_PRICE"
    })
    print(f"TP{i}: {r.get('code')} {r.get('msg')}")

# 4. Verify final
orders3 = bx._request("GET", "/openApi/swap/v2/trade/openOrders", {"symbol": symbol, "pageSize": 50})
final = orders3.get("data", {}).get("orders", [])
print(f"\n=== FINAL: {len(final)} orders ===")
for o in final:
    print(f"  {o['type']:20s} stopPrice={o['stopPrice']:>10} qty={o['origQty']}")
