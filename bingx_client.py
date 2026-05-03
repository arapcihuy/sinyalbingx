import hashlib
import hmac
import time
import requests
import json
import os
import urllib3
from dotenv import load_dotenv

load_dotenv()

# Disable SSL warning untuk lokal Mac (Railway tidak punya masalah ini)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BINGX_API_KEY = os.getenv("BINGX_API_KEY")
BINGX_API_SECRET = os.getenv("BINGX_API_SECRET")
BASE_URL = "https://open-api.bingx.com"


def _sign(params: dict) -> str:
    """Buat HMAC-SHA256 signature untuk BingX API."""
    query_string = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
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
    """Buat request ke BingX API dengan autentikasi."""
    if params is None:
        params = {}

    params["timestamp"] = int(time.time() * 1000)
    params["signature"] = _sign(params)

    url = BASE_URL + path
    headers = _get_headers()

    if method == "GET":
        response = requests.get(url, headers=headers, params=params, timeout=10, verify=False)
    elif method == "POST":
        response = requests.post(url, headers=headers, params=params, timeout=10, verify=False)
    elif method == "DELETE":
        response = requests.delete(url, headers=headers, params=params, timeout=10, verify=False)
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


def set_tp_sl(
    symbol: str,
    position_side: str,  # "LONG" atau "SHORT"
    stop_price: float,
    tp_price: float,
) -> dict:
    """
    Pasang Take Profit dan Stop Loss setelah order masuk.
    Menggunakan stop order terpisah.
    """
    results = {}

    # ── Take Profit ──
    # Jika LONG: TP = SELL saat harga naik ke tp_price
    tp_side = "SELL" if position_side == "LONG" else "BUY"
    tp_params = {
        "symbol": symbol,
        "side": tp_side,
        "positionSide": position_side,
        "type": "TAKE_PROFIT_MARKET",
        "stopPrice": tp_price,
        "quantity": 0,          # 0 = tutup seluruh posisi
        "workingType": "MARK_PRICE",
        "closePosition": "true",
    }
    results["tp"] = _request("POST", "/openApi/swap/v2/trade/order", tp_params)

    # ── Stop Loss ──
    sl_side = "SELL" if position_side == "LONG" else "BUY"
    sl_params = {
        "symbol": symbol,
        "side": sl_side,
        "positionSide": position_side,
        "type": "STOP_MARKET",
        "stopPrice": stop_price,
        "quantity": 0,
        "workingType": "MARK_PRICE",
        "closePosition": "true",
    }
    results["sl"] = _request("POST", "/openApi/swap/v2/trade/order", sl_params)

    return results


def cancel_all_orders(symbol: str) -> dict:
    """Batalkan semua open order untuk symbol."""
    result = _request("DELETE", "/openApi/swap/v2/trade/allOpenOrders", {"symbol": symbol})
    return result


def get_open_positions(symbol: str) -> list:
    """Cek posisi aktif."""
    result = _request("GET", "/openApi/swap/v2/user/positions", {"symbol": symbol})
    if result.get("code") == 0:
        return result.get("data", [])
    return []
