import hmac
import hashlib
import time
import requests

key = "4SpTFy7bpDRUrR0cKYnHxkAJs1SwFWAsTaJ4pwQarOco4FMbK20JXzRpe6JUU2b8PrKWq2L2i5KT0btQeSqt8Q"
secret = "HK5P3JWf059hq0k5JREnxAUytlwb3AIDPGmQbG7uQyfRJueZNGeAvcVOBhd9eUdEJnfTppXDPHoLrbgTVg"

def query_bingx(path, params):
    params["timestamp"] = int(time.time() * 1000)
    sorted_params = sorted(params.items())
    query_string = "&".join([f"{k}={v}" for k, v in sorted_params])
    signature = hmac.new(
        secret.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    
    url = f"https://open-api.bingx.com{path}?{query_string}&signature={signature}"
    headers = {
        "X-BX-APIKEY": key,
        "User-Agent": "Mozilla/5.0"
    }
    return requests.get(url, headers=headers).json()

oid = "2065130767482724352"
res = query_bingx("/openApi/swap/v2/trade/order", {"symbol": "ETH-USDT", "orderId": oid})
print("RAW RESPONSE:", res)
