import hashlib
import hmac
import time
import requests
import json
import os
import urllib3
import urllib.parse
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

load_dotenv()

# Disable SSL warning untuk lokal Mac (Railway tidak punya masalah ini)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BINGX_API_KEY = os.getenv("BINGX_API_KEY")
BINGX_API_SECRET = os.getenv("BINGX_API_SECRET")
BASE_URL = "https://open-api.bingx.com"
_SESSION = requests.Session()
_RETRY = Retry(
    total=3,
    connect=3,
    read=3,
    status=3,
    backoff_factor=0.6,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET", "POST", "DELETE"]),
)
_SESSION.mount("https://", HTTPAdapter(max_retries=_RETRY))
_SESSION.mount("http://", HTTPAdapter(max_retries=_RETRY))


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
    # Gunakan header yang lebih lengkap agar tidak diblokir
    headers = _get_headers()
    headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    
    _logger.info(f"[BingX] {method} {path} params={dict(sorted_params)}")

    max_retries = 3
    for attempt in range(max_retries):
        try:
            if method == "GET":
                response = _SESSION.get(url, headers=headers, timeout=10, verify=False)
            elif method == "POST":
                response = _SESSION.post(url, headers=headers, timeout=10, verify=False)
            elif method == "DELETE":
                response = _SESSION.delete(url, headers=headers, timeout=10, verify=False)
            else:
                raise ValueError(f"Method tidak dikenal: {method}")

            # Jika rate limit (429), tunggu sebentar lalu retry
            if response.status_code == 429:
                _logger.warning(f"⚠️ Rate Limit (429). Retry {attempt+1}/{max_retries}...")
                time.sleep(2)
                continue

            response.raise_for_status()
            break # Sukses
            
        except requests.exceptions.RequestException as e:
            if attempt == max_retries - 1:
                _logger.error(f"❌ HTTP Request Error ({method} {path}) setelah {max_retries} percobaan: {e}")
                if hasattr(e, 'response') and e.response is not None:
                    _logger.error(f"   Status: {e.response.status_code} | Body: {e.response.text[:200]}")
                raise
            _logger.warning(f"⚠️ Request gagal ({e}). Retry {attempt+1}/{max_retries}...")
            time.sleep(1)

    response_text = response.text.strip()
    if not response_text:
        _logger.error(f"⚠️ BingX mengembalikan body KOSONG untuk {method} {path}")
        return {"code": -1, "msg": "Empty response from server"}

    try:
        return response.json()
    except Exception:
        # Jika bukan JSON, coba cek apakah terlihat seperti JSON
        if response_text.startswith("{") or response_text.startswith("["):
            try:
                import json
                return json.loads(response_text)
            except:
                pass
        _logger.error(f"❌ Gagal parse JSON. Status: {response.status_code} | Body: {response_text[:200]}")
        raise RuntimeError(f"BingX mengembalikan non-JSON response (status {response.status_code})")


# ─────────────────────────────────────────────
#  BALANCE & AKUN
# ─────────────────────────────────────────────

def get_balance(currency: str = "USDT") -> float:
    """Ambil total Equity (Saldo + PnL Mengambang) dari akun Futures."""
    result = _request("GET", "/openApi/swap/v2/user/balance", {})
    if result.get("code") == 0:
        # 'equity' adalah Saldo + PnL yang sedang jalan (lebih realtime)
        data = result.get("data", {}).get("balance", {})
        return float(data.get("equity", 0))
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


def get_income_history(symbol: str = None, days: int = 1) -> list:
    """Ambil riwayat pendapatan (Profit/Loss) dalam kurun waktu tertentu."""
    start_time = int((time.time() - (days * 24 * 3600)) * 1000)
    params = {"startTime": start_time, "timestamp": int(time.time() * 1000)}
    if symbol:
        params["symbol"] = symbol
        
    result = _request("GET", "/openApi/swap/v2/user/income", params)
    if result.get("code") == 0:
        return result.get("data", [])
    return []


# ─────────────────────────────────────────────
#  HARGA
# ─────────────────────────────────────────────

def get_current_price(symbol: str) -> float:
    """Ambil harga terakhir untuk symbol."""
    result = _request("GET", "/openApi/swap/v2/quote/price", {"symbol": symbol})
    if result.get("code") == 0:
        return float(result["data"]["price"])
    raise Exception(f"Gagal ambil harga: {result}")


def get_open_positions(symbol: str = None) -> list:
    """Ambil daftar posisi aktif. Jika symbol diisi, hanya ambil posisi symbol tersebut."""
    result = _request("GET", "/openApi/swap/v2/user/positions", {"timestamp": int(time.time() * 1000)})
    if result.get("code") == 0:
        positions = result.get("data", [])
        if symbol:
            # Filter posisi berdasarkan symbol (misal: 'BTC-USDT')
            return [p for p in positions if p.get("symbol") == symbol and abs(float(p.get("positionAmt", 0))) > 0]
        return [p for p in positions if abs(float(p.get("positionAmt", 0))) > 0]
    return []


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
    reduce_only: bool = False,
) -> dict:
    """
    Buka/Tutup order Futures di BingX.
    """
    params = {
        "symbol": symbol,
        "side": side,
        "positionSide": position_side,
        "type": order_type,
        "quantity": quantity,
    }
    
    if reduce_only:
        params["reduceOnly"] = "true"

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


def cancel_order(symbol: str, order_id: str) -> dict:
    """Batalkan satu order spesifik berdasarkan Order ID."""
    params = {
        "symbol": symbol,
        "orderId": order_id
    }
    result = _request("DELETE", "/openApi/swap/v2/trade/order", params)
    return result


