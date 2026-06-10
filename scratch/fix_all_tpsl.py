import os
import json
import time
import hmac
import hashlib
import urllib.request
import urllib.parse

# Manual ENV reading
def get_env():
    env = {}
    try:
        with open(".env", "r") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    parts = line.strip().split("=", 1)
                    if len(parts) == 2:
                        k, v = parts
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

def fix_all_positions():
    print(f"🔄 Memeriksa SEMUA posisi aktif (BTC, ETH, SOL)...")
    
    # 1. Ambil Semua Posisi
    res = _request("GET", "/openApi/swap/v2/user/positions")
    all_positions = res.get("data", [])
    
    if not all_positions:
        print("❌ Tidak ada posisi open yang ditemukan di BingX.")
        return

    for pos in all_positions:
        symbol = pos["symbol"]
        side = pos["positionSide"]
        amt = abs(float(pos["positionAmt"]))
        entry = float(pos["avgPrice"])
        
        if amt == 0: continue
        
        print(f"\n✅ Menemukan posisi: {symbol} | {side} | Qty: {amt} | Entry: {entry}")

        # 2. Cek apakah sudah ada TP/SL aktif
        orders_res = _request("GET", "/openApi/swap/v2/trade/openOrders", {"symbol": symbol})
        open_orders = orders_res.get("data", [])
        has_tpsl = any("STOP" in o.get("type", "") or "TAKE_PROFIT" in o.get("type", "") for o in open_orders)
        
        if has_tpsl:
            print(f"✔️ {symbol} sudah punya TP/SL. Dilewati.")
            continue

        # 3. Hitung TP/SL Aman (Scalping 1% / 1.5%)
        print(f"⚠️ {symbol} TIDAK punya TP/SL. Memasang otomatis...")
        if side == "LONG":
            sl_price = round(entry * 0.985, 2)
            tp_price = round(entry * 1.01, 2)
        else:
            sl_price = round(entry * 1.015, 2)
            tp_price = round(entry * 0.99, 2)

        sl_side = "SELL" if side == "LONG" else "BUY"
        
        # Pasang SL
        r1 = _request("POST", "/openApi/swap/v2/trade/order", {
            "symbol": symbol, "side": sl_side, "positionSide": side,
            "type": "STOP_MARKET", "stopPrice": sl_price, "quantity": amt
        })
        # Pasang TP
        r2 = _request("POST", "/openApi/swap/v2/trade/order", {
            "symbol": symbol, "side": sl_side, "positionSide": side,
            "type": "TAKE_PROFIT_MARKET", "stopPrice": tp_price, "quantity": amt
        })
        
        print(f"🚀 SL Result: {r1.get('msg', 'Success')} | TP Result: {r2.get('msg', 'Success')}")

if __name__ == "__main__":
    fix_all_positions()
