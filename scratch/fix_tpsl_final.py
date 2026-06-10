import os
import json
import time
import hmac
import hashlib
import urllib.request
import urllib.parse

# Manual ENV reading from .env file
def get_env():
    env = {}
    try:
        with open(".env", "r") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.strip().split("=", 1)
                    env[k] = v
    except: pass
    return env

ENV = get_env()
API_KEY = ENV.get("BINGX_API_KEY")
API_SECRET = ENV.get("BINGX_API_SECRET")
BASE_URL = "https://open-api.bingx.com"

def _request(method, path, params=None):
    if params is None: params = {}
    params["timestamp"] = int(time.time() * 1000)
    
    query_string = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
    signature = hmac.new(API_SECRET.encode("utf-8"), query_string.encode("utf-8"), hashlib.sha256).hexdigest()
    
    url = f"{BASE_URL}{path}?{query_string}&signature={signature}"
    
    req = urllib.request.Request(url, method=method)
    req.add_header("X-BX-APIKEY", API_KEY)
    
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        return {"msg": str(e), "code": -1}

def fix():
    symbol = "ETH-USDT"
    print(f"🔄 Memulai perbaikan TP/SL untuk {symbol}...")
    
    # 1. Ambil Posisi
    res = _request("GET", "/openApi/swap/v2/user/positions", {"symbol": symbol})
    data = res.get("data", [])
    if not data:
        print("❌ Tidak ada posisi open di BingX.")
        return
    
    pos = data[0]
    side = pos["positionSide"]
    amt = abs(float(pos["positionAmt"]))
    entry = float(pos["avgPrice"])
    
    print(f"✅ Posisi ditemukan: {side} {amt} ETH (Entry: {entry})")

    # 2. Ambil Sinyal Terakhir
    try:
        with open("latest_signals.json", "r") as f:
            latest = json.load(f)
        signal = latest.get(symbol)
        sl_price = float(signal["sl"])
        tp_price = float(signal["tp1"])
    except:
        print("⚠️ Gagal baca sinyal terakhir, gunakan estimasi dari harga entry...")
        if side == "SHORT":
            sl_price = round(entry * 1.02, 2) # 2% SL
            tp_price = round(entry * 0.98, 2) # 2% TP
        else:
            sl_price = round(entry * 0.98, 2)
            tp_price = round(entry * 1.02, 2)

    print(f"🎯 Memasang SL: {sl_price}, TP: {tp_price}")

    # 3. Bersihkan order lama
    _request("POST", "/openApi/swap/v2/trade/allOpenOrders", {"symbol": symbol})
    
    sl_side = "SELL" if side == "LONG" else "BUY"
    
    # Pasang SL
    r1 = _request("POST", "/openApi/swap/v2/trade/order", {
        "symbol": symbol, "side": sl_side, "positionSide": side,
        "type": "STOP_MARKET", "stopPrice": sl_price, "quantity": amt
    })
    print(f"SL Result: {r1.get('msg', 'Success')}")
    
    # Pasang TP
    r2 = _request("POST", "/openApi/swap/v2/trade/order", {
        "symbol": symbol, "side": sl_side, "positionSide": side,
        "type": "TAKE_PROFIT_MARKET", "stopPrice": tp_price, "quantity": amt
    })
    print(f"TP Result: {r2.get('msg', 'Success')}")

if __name__ == "__main__":
    fix()
