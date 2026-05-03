import hashlib
import hmac
import time
import requests
import json
import os
import urllib3
import urllib.parse
from dotenv import load_dotenv

load_dotenv()

# Disable SSL warning untuk lokal Mac (Railway tidak punya masalah ini)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BINGX_API_KEY = os.getenv("BINGX_API_KEY")
BINGX_API_SECRET = os.getenv("BINGX_API_SECRET")
BASE_URL = "https://open-api.bingx.com"


def _sign(query_string: str) -> str:
    """Buat HMAC-SHA256 signature dari query string."""
    signature = hmac.new(
        BINGX_API_SECRET.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return signature


def _get_headers() -> dict:
    return {
        "X-BX-APIKEY": BINGX_API_KEY,
        "Content-Type": "application/json",
    }


def _request(method: str, path: str, params: dict = None) -> dict:
    """Buat request ke BingX API dengan pemisahan Query vs Body untuk V2."""
    import logging as _log
    _logger = _log.getLogger(__name__)
    
    if params is None:
        params = {}

    # Tambahkan timestamp
    params["timestamp"] = int(time.time() * 1000)
    
    # Buat query string murni untuk tanda tangan
    # Pastikan boolean dikonversi ke 'true'/'false' (bukan 'True'/'False')
    sorted_params = sorted(params.items())
    query_parts = []
    for k, v in sorted_params:
        if isinstance(v, bool):
            val = str(v).lower()
        else:
            val = str(v)
        query_parts.append(f"{k}={val}")
    
    query_string = "&".join(query_parts)
    
    # Tambahkan signature ke query string
    signature = _sign(query_string)
    full_query_string = f"{query_string}&signature={signature}"
    
    # Konstruksi URL dengan query string lengkap
    url = f"{BASE_URL}{path}?{full_query_string}"
    headers = _get_headers()
    
    _logger.info(f"[BingX] {method} {path} params={dict(sorted_params)}")

    if method == "GET":
        response = requests.get(url, headers=headers, timeout=10, verify=False)
    elif method == "POST":
        response = requests.post(url, headers=headers, timeout=10, verify=False)
    elif method == "DELETE":
        response = requests.delete(url, headers=headers, timeout=10, verify=False)
    else:
        raise ValueError(f"Method tidak dikenal: {method}")

    response.raise_for_status()
    return response.json()


# ─────────────────────────────────────────────
#  BALANCE & AKUN
# ─────────────────────────────────────────────

def get_balance(currency: str = "USDT") -> float:
    """Ambil balance USDT dari akun Futures."""
    result = _request("GET", "/openApi/swap/v2/user/balance", {})
    if result.get("code") == 0:
        data = result.get("data", {}).get("balance", {})
        return float(data.get("availableMargin", 0))
    raise Exception(f"Gagal ambil balance: {result}")


# ─────────────────────────────────────────────
#  LEVERAGE
# ─────────────────────────────────────────────

def set_leverage(symbol: str, leverage: int, side: str = "LONG") -> dict:
    """Set leverage untuk symbol."""
    params = {
        "symbol": symbol,
        "side": side,
        "leverage": leverage,
    }
    result = _request("POST", "/openApi/swap/v2/trade/leverage", params)
    return result


def set_margin_type(symbol: str, margin_type: str = "ISOLATED") -> dict:
    """
    Set margin type untuk symbol.
    margin_type: "ISOLATED" atau "CROSSED"
    """
    params = {
        "symbol": symbol,
        "marginType": margin_type,
    }
    result = _request("POST", "/openApi/swap/v2/trade/marginType", params)
    return result


# ─────────────────────────────────────────────
#  HARGA
# ─────────────────────────────────────────────

def get_current_price(symbol: str) -> float:
    """Ambil harga terakhir untuk symbol."""
    result = _request("GET", "/openApi/swap/v2/quote/price", {"symbol": symbol})
    if result.get("code") == 0:
        return float(result["data"]["price"])
    raise Exception(f"Gagal ambil harga: {result}")


# ─────────────────────────────────────────────
#  ORDER
# ─────────────────────────────────────────────

def place_order(
    symbol: str,
    side: str,          # "BUY" atau "SELL"
    position_side: str, # "LONG" atau "SHORT"
    quantity: float,
    order_type: str = "MARKET",
    price: float = None,
) -> dict:
    """
    Buka order Futures di BingX.
    - side=BUY + position_side=LONG  → buka posisi LONG
    - side=SELL + position_side=SHORT → buka posisi SHORT
    """
    params = {
        "symbol": symbol,
        "side": side,
        "positionSide": position_side,
        "type": order_type,
        "quantity": quantity,
    }

    if order_type == "LIMIT" and price:
        params["price"] = price
        params["timeInForce"] = "GTC"

    result = _request("POST", "/openApi/swap/v2/trade/order", params)
    return result


def set_multi_tp_sl(
    symbol: str,
    position_side: str,
    stop_price: float,
    tp_levels: list,    # List of (price, qty)
    total_qty: float
) -> dict:
    """
    Pasang Multi-Take Profit dan satu Stop Loss.
    tp_levels: [(price1, qty1), (price2, qty2), ...]
    """
    results = {"tp": [], "sl": None}
    side = "SELL" if position_side == "LONG" else "BUY"

    # ── Pasang Tiap Level TP ──
    for tp_price, tp_qty in tp_levels:
        if tp_qty <= 0: continue
        tp_params = {
            "symbol": symbol,
            "side": side,
            "type": "TAKE_PROFIT_MARKET",
            "stopPrice": round(float(tp_price), 2),
            "quantity": round(float(tp_qty), 4),
            "reduceOnly": "true",
            "priceProtect": "true"
        }
        try:
            res = _request("POST", "/openApi/swap/v2/trade/order", tp_params)
            results["tp"].append(res)
        except Exception as e:
            results["tp"].append({"error": str(e), "price": tp_price})

    # ── Stop Loss (Tutup Semua Sisa Posisi) ──
    sl_params = {
        "symbol": symbol,
        "side": side,
        "type": "STOP_MARKET",
        "stopPrice": round(float(stop_price), 2),
        "quantity": round(float(total_qty), 4),
        "reduceOnly": "true",
        "priceProtect": "true"
    }
    results["sl"] = _request("POST", "/openApi/swap/v2/trade/order", sl_params)

    return results


def cancel_all_orders(symbol: str) -> dict:
    """Batalkan semua open order untuk symbol."""
    result = _request("DELETE", "/openApi/swap/v2/trade/allOpenOrders", {"symbol": symbol})
    return result


def get_open_positions(symbol: str = None) -> list:
    """Cek posisi aktif. Jika symbol None, ambil semua."""
    params = {}
    if symbol:
        params["symbol"] = symbol
        
    result = _request("GET", "/openApi/swap/v2/user/positions", params)
    if result.get("code") == 0:
        return result.get("data", [])
    return []
