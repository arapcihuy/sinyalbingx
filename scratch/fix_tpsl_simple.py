import os
import json
import requests
import time
import hmac
import hashlib
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("BINGX_API_KEY")
API_SECRET = os.getenv("BINGX_API_SECRET")
BASE_URL = "https://open-api.bingx.com"

def _request(method, path, params=None):
    if params is None: params = {}
    params["timestamp"] = int(time.time() * 1000)
    
    query_string = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
    signature = hmac.new(API_SECRET.encode("utf-8"), query_string.encode("utf-8"), hashlib.sha256).hexdigest()
    url = f"{BASE_URL}{path}?{query_string}&signature={signature}"
    
    headers = {"X-BX-APIKEY": API_KEY}
    response = requests.request(method, url, headers=headers)
    return response.json()

def fix():
    symbol = "ETH-USDT"
    # 1. Ambil Posisi
    res = _request("GET", "/openApi/swap/v2/user/positions", {"symbol": symbol})
    positions = res.get("data", [])
    if not positions:
        print("❌ Tidak ada posisi open.")
        return
    
    pos = positions[0]
    side = pos["positionSide"]
    amt = abs(float(pos["positionAmt"]))
    
    print(f"✅ Posisi ditemukan: {side} {amt} ETH")

    # 2. Ambil Sinyal Terakhir (dari file lokal)
    try:
        with open("latest_signals.json", "r") as f:
            latest = json.load(f)
        signal = latest.get(symbol)
        if not signal: raise Exception("No signal")
        sl_price = signal["sl"]
        tp_price = signal["tp1"]
    except:
        # Fallback harga manual dari screenshot (Entry 2311)
        # Jika SHORT, SL harus diatas (misal 2350), TP dibawah (misal 2280)
        print("⚠️ Gagal baca file sinyal, gunakan estimasi aman...")
        if side == "SHORT":
            sl_price = 2350.0
            tp_price = 2270.0
        else:
            sl_price = 2270.0
            tp_price = 2350.0

    print(f"🎯 Memasang SL: {sl_price}, TP: {tp_price}")

    # 3. Batalkan Order Lama & Pasang Baru
    _request("POST", "/openApi/swap/v2/trade/allOpenOrders", {"symbol": symbol, "method": "DELETE"})
    
    sl_side = "SELL" if side == "LONG" else "BUY"
    
    # Pasang SL
    r1 = _request("POST", "/openApi/swap/v2/trade/order", {
        "symbol": symbol, "side": sl_side, "positionSide": side,
        "type": "STOP_MARKET", "stopPrice": sl_price, "quantity": amt
    })
    print(f"SL Result: {r1.get('msg')}")
    
    # Pasang TP
    r2 = _request("POST", "/openApi/swap/v2/trade/order", {
        "symbol": symbol, "side": sl_side, "positionSide": side,
        "type": "TAKE_PROFIT_MARKET", "stopPrice": tp_price, "quantity": amt
    })
    print(f"TP Result: {r2.get('msg')}")

if __name__ == "__main__":
    fix()
