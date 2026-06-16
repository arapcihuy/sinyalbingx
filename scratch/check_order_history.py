import hmac
import hashlib
import time
import requests

key = "4SpTFy7bpDRUrR0cKYnHxkAJs1SwFWAsTaJ4pwQarOco4FMbK20JXzRpe6JUU2b8PrKWq2L2i5KT0btQeSqt8Q"
secret = "HK5P3JWf059hq0k5JREnxAUytlwb3AIDPGmQbG7uQyfRJueZNGeAvcVOBhd9eUdEJnfTppXDPHoLrbgTVg"

def query_bingx(base_url, method, path, params=None):
    if params is None:
        params = {}
    params["timestamp"] = int(time.time() * 1000)
    sorted_params = sorted(params.items())
    query_parts = []
    for k, v in sorted_params:
        if isinstance(v, bool):
            val = str(v).lower()
        else:
            val = str(v)
        query_parts.append(f"{k}={val}")
    query_string = "&".join(query_parts)
    signature = hmac.new(
        secret.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    
    url = f"{base_url}{path}?{query_string}&signature={signature}"
    headers = {
        "X-BX-APIKEY": key,
        "User-Agent": "Mozilla/5.0"
    }
    
    try:
        if method == "GET":
            res = requests.get(url, headers=headers, timeout=10)
        else:
            res = requests.post(url, headers=headers, timeout=10)
        return res.json()
    except Exception as e:
        return {"error": str(e)}

print("=== CHECKING BINGX TRANSACTIONS ===")

for base_url, label in [("https://open-api.bingx.com", "LIVE"), ("https://open-api-vst.bingx.com", "VST (DEMO)")]:
    print(f"\n--- {label} ACCOUNT DETAILS ---")
    
    # 1. Get balance
    bal = query_bingx(base_url, "GET", "/openApi/swap/v2/user/balance")
    if bal.get("code") == 0:
        b = bal["data"]["balance"]
        print(f"Equity: {b.get('equity')} {b.get('asset')}, Available Margin: {b.get('availableMargin')}")
    else:
        print("Failed to get balance:", bal)
        
    # 2. Get Open Positions
    pos = query_bingx(base_url, "GET", "/openApi/swap/v2/user/positions")
    if pos.get("code") == 0:
        positions = pos.get("data", [])
        active_pos = [p for p in positions if abs(float(p.get("positionAmt", 0))) > 0]
        if active_pos:
            print("Active Positions:")
            for p in active_pos:
                print(f"  - {p['symbol']} {p['positionSide']} | Amt: {p['positionAmt']} | Entry: {p['avgPrice']} | PnL: {p['unrealizedProfit']}")
        else:
            print("No active positions.")
    else:
        print("Failed to get positions:", pos)
        
    # 3. Get Open Orders
    orders_res = query_bingx(base_url, "GET", "/openApi/swap/v2/trade/openOrders")
    if orders_res.get("code") == 0:
        orders = orders_res.get("data", [])
        if isinstance(orders, dict):
            orders = orders.get("orders", [])
        if orders:
            print("Open Orders:")
            for o in orders:
                print(f"  - OrderID: {o.get('orderId')} | Symbol: {o.get('symbol')} | Side: {o.get('side')} | Type: {o.get('type')} | Price: {o.get('price')} | StopPrice: {o.get('stopPrice')} | Qty: {o.get('origQty')}")
        else:
            print("No open orders.")
    else:
        print("Failed to get open orders:", orders_res)

    # 4. Get Order History (Recent 10)
    history_res = query_bingx(base_url, "GET", "/openApi/swap/v2/trade/allOrders", {"limit": 10})
    if history_res.get("code") == 0:
        orders = history_res.get("data", [])
        if isinstance(orders, dict):
            orders = orders.get("orders", [])
        if orders:
            print("Recent Order History:")
            for o in orders:
                print(f"  - Time: {o.get('time')} | OrderID: {o.get('orderId')} | Symbol: {o.get('symbol')} | Side: {o.get('side')} | Type: {o.get('type')} | Status: {o.get('status')} | Price: {o.get('price')} | Qty: {o.get('executedQty') or o.get('origQty')}")
        else:
            print("No order history.")
    else:
        print("Failed to get order history:", history_res)
