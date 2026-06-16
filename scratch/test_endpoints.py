import hmac
import hashlib
import time
import requests

key = "4SpTFy7bpDRUrR0cKYnHxkAJs1SwFWAsTaJ4pwQarOco4FMbK20JXzRpe6JUU2b8PrKWq2L2i5KT0btQeSqt8Q"
secret = "HK5P3JWf059hq0k5JREnxAUytlwb3AIDPGmQbG7uQyfRJueZNGeAvcVOBhd9eUdEJnfTppXDPHoLrbgTVg"

def test_endpoint(base_url, label):
    params = {
        "timestamp": int(time.time() * 1000)
    }
    sorted_params = sorted(params.items())
    query_string = "&".join([f"{k}={v}" for k, v in sorted_params])
    signature = hmac.new(
        secret.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    
    url = f"{base_url}/openApi/swap/v2/user/balance?{query_string}&signature={signature}"
    headers = {
        "X-BX-APIKEY": key,
        "User-Agent": "Mozilla/5.0"
    }
    
    try:
        res = requests.get(url, headers=headers, timeout=10)
        print(f"\n=== {label} ({base_url}) ===")
        print("Status Code:", res.status_code)
        print("Response:", res.json())
    except Exception as e:
        print(f"\n=== {label} ({base_url}) ===")
        print("Error:", e)

test_endpoint("https://open-api.bingx.com", "LIVE ENDPOINT")
test_endpoint("https://open-api-vst.bingx.com", "VST (DEMO) ENDPOINT")
