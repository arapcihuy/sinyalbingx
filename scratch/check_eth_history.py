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

for base_url, label in [("https://open-api.bingx.com", "LIVE"), ("https://open-api-vst.bingx.com", "VST (DEMO)")]:
    print(f"\n--- {label} ETH-USDT ORDER HISTORY ---")
    res = query_bingx(base_url, "GET", "/openApi/swap/v2/trade/allOrders", {"symbol": "ETH-USDT", "limit": 50})
    if res.get("code") == 0:
        orders = res.get("data", [])
        if isinstance(orders, dict):
            orders = orders.get("orders", [])
        for o in orders:
            print(f"Time: {time.ctime(o['time']/1000)} | OrderID: {o.get('orderId')} | Side: {o.get('side')} | Type: {o.get('type')} | Status: {o.get('status')} | Price: {o.get('price')} | Qty: {o.get('origQty')}")
    else:
        print("Failed to get ETH-USDT history:", res)
