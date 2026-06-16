import hmac
import hashlib
import time
import requests

key = "4SpTFy7bpDRUrR0cKYnHxkAJs1SwFWAsTaJ4pwQarOco4FMbK20JXzRpe6JUU2b8PrKWq2L2i5KT0btQeSqt8Q"
secret = "HK5P3JWf059hq0k5JREnxAUytlwb3AIDPGmQbG7uQyfRJueZNGeAvcVOBhd9eUdEJnfTppXDPHoLrbgTVg"

params = {
    "timestamp": int(time.time() * 1000)
}

sorted_params = sorted(params.items())
query_parts = []
for k, v in sorted_params:
    query_parts.append(f"{k}={v}")
query_string = "&".join(query_parts)

signature = hmac.new(
    secret.encode("utf-8"),
    query_string.encode("utf-8"),
    hashlib.sha256
).hexdigest()

url = f"https://open-api.bingx.com/openApi/swap/v2/user/balance?{query_string}&signature={signature}"
headers = {
    "X-BX-APIKEY": key,
    "User-Agent": "Mozilla/5.0"
}

res = requests.get(url, headers=headers)
print("Status Code:", res.status_code)
print("Response:", res.json())
