import hashlib
import hmac
import time
import requests
import certifi
import os
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
os.environ['SSL_CERT_FILE'] = certifi.where()
import certifi
import os

# ── RATE LIMIT GUARD ──
_rate_limit_until = 0  # unix timestamp when rate limit clears

def _check_rate_limit():
    """Wait if BingX rate limit is active (100410)."""
    global _rate_limit_until
    now = time.time()
    if now < _rate_limit_until:
        wait = _rate_limit_until - now
        import logging as _log
        _log.getLogger(__name__).warning(f"⏳ Rate limit aktif, tunggu {wait:.0f}s...")
        time.sleep(wait + 1)  # +1s buffer

def _set_rate_limit(until_ts_ms: int):
    """Set rate limit cooldown from BingX 100410 response."""
    global _rate_limit_until
    _rate_limit_until = until_ts_ms / 1000 + 5  # +5s buffer
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
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

if not BINGX_API_KEY or not BINGX_API_SECRET:
    # Coba load dari file .env di direktori yang sama jika belum ada
    current_dir = os.path.dirname(os.path.abspath(__file__))
    load_dotenv(os.path.join(current_dir, ".env"))
    BINGX_API_KEY = os.getenv("BINGX_API_KEY")
    BINGX_API_SECRET = os.getenv("BINGX_API_SECRET")

if not BINGX_API_KEY or not BINGX_API_SECRET:
    print("[ERROR] BINGX_API_KEY or BINGX_API_SECRET not found in environment!")
    # Optional: raise error or handle gracefully

def get_base_url() -> str:
    """Mengambil URL endpoint BingX secara dinamis berdasarkan state_manager."""
    try:
        import state_manager
        use_demo = state_manager.get_trading_mode()["use_demo"]
    except Exception:
        # Fallback jika diimpor sebelum state_manager selesai diinisialisasi
        import os
        use_demo = os.getenv("USE_DEMO", "true").lower() == "true"
    return "https://open-api-vst.bingx.com" if use_demo else "https://open-api.bingx.com"

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
    if not BINGX_API_SECRET:
        raise ValueError("BINGX_API_SECRET is not set. Cannot sign request.")
    signature = hmac.new(
        BINGX_API_SECRET.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return signature


def _get_headers() -> dict:
    return {
        "X-BX-APIKEY": BINGX_API_KEY,
    }


def _request(method: str, path: str, params: dict = None) -> dict:
    """Buat request ke BingX API dengan pemisahan Query vs Body untuk V2."""
    import logging as _log
    _check_rate_limit()  # Wait if rate limited
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
    url = f"{get_base_url()}{path}?{full_query_string}"
    
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
    raise Exception(f"Gagal mengambil posisi aktif dari BingX API (code={result.get('code')}, msg={result.get('msg')})")


def get_candles(symbol: str, interval: str = "1h", limit: int = 100) -> list:
    """Ambil data candlestick/klines dari BingX."""
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }
    result = _request("GET", "/openApi/swap/v2/quote/klines", params)
    if result.get("code") == 0:
        return result.get("data", [])
    return []

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
        "type": order_type,
        "quantity": quantity,
    }
    
    if position_side:
        params["positionSide"] = position_side
        
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
            "positionSide": position_side,
            "type": "TAKE_PROFIT_MARKET",
            "stopPrice": round(float(tp_price), 3),
            "quantity": round(float(tp_qty), 4),
            "priceProtect": "true"
        }
        try:
            res = _request("POST", "/openApi/swap/v2/trade/order", tp_params)
            results["tp"].append(res)
        except Exception as e:
            results["tp"].append({"error": str(e), "price": tp_price})
        time.sleep(2)  # Rate limit: 2s gap antar order (CLAUDE.md)

    # ── Stop Loss (Tutup Semua Sisa Posisi) ──
    sl_params = {
        "symbol": symbol,
        "side": side,
        "positionSide": position_side,
        "type": "STOP_MARKET",
        "stopPrice": round(float(stop_price), 3),
        "quantity": round(float(total_qty), 4),
        "priceProtect": "true"
    }
    results["sl"] = _request("POST", "/openApi/swap/v2/trade/order", sl_params)

    return results


def cancel_all_orders(symbol: str) -> dict:
    """Batalkan semua open order (termasuk limit & trigger TP/SL) secara paksa."""
    # 1. Batalkan semua limit orders bawaan
    _request("DELETE", "/openApi/swap/v2/trade/allOpenOrders", {"symbol": symbol})
    
    # 2. Batalkan semua trigger orders (STOP_MARKET & TAKE_PROFIT_MARKET) secara manual
    try:
        orders_res = _request("GET", "/openApi/swap/v2/trade/openOrders", {"symbol": symbol})
        orders_raw = orders_res.get("data", [])
        if isinstance(orders_raw, dict):
            open_orders = orders_raw.get("orders", [])
        else:
            open_orders = orders_raw if isinstance(orders_raw, list) else []
            
        for order in open_orders:
            order_id = order.get("orderId")
            cancel_order(symbol, order_id)
    except Exception as e:
        import logging as _log
        _logger = _log.getLogger(__name__)
        _logger.error(f"⚠️ Gagal membersihkan trigger orders: {e}")
        
    return {"status": "success"}


def cancel_order(symbol: str, order_id: str) -> dict:
    """Batalkan satu order spesifik berdasarkan Order ID."""
    params = {
        "symbol": symbol,
        "orderId": order_id
    }
    result = _request("DELETE", "/openApi/swap/v2/trade/order", params)
    return result


# ─────────────────────────────────────────────
#  CONTRACT INFO (cached 1 jam)
# ─────────────────────────────────────────────

_CONTRACT_INFO_CACHE: dict = {}  # {symbol: {"data": {...}, "ts": float}}
_CONTRACT_CACHE_TTL = 3600  # 1 hour

# BingX max leverage per coin (updated 2026-07-06). Used as fallback if API rate-limited.
_MAX_LEVERAGE_DEFAULTS = {
    "BTC-USDT": 150, "ETH-USDT": 100, "SOL-USDT": 100,
    "XRP-USDT": 125, "BNB-USDT": 75, "ADA-USDT": 100,
    "DOGE-USDT": 75, "AVAX-USDT": 75, "LINK-USDT": 75,
    "DOT-USDT": 75, "MATIC-USDT": 75, "UNI-USDT": 75,
}


def get_contract_info(symbol: str) -> dict:
    """
    Ambil detail contract (min_qty, min_notional, max_leverage, dll).
    Hasil di-cache selama 1 jam.
    """
    import logging as _log
    _logger = _log.getLogger(__name__)

    now = time.time()
    cached = _CONTRACT_INFO_CACHE.get(symbol)
    if cached and (now - cached["ts"]) < _CONTRACT_CACHE_TTL:
        return cached["data"]

    try:
        # /quote/contracts returns a LIST, filter by symbol
        result = _request("GET", "/openApi/swap/v2/quote/contracts", {"symbol": symbol})
        if result.get("code") != 0:
            _logger.error(f"⚠️ Gagal ambil contract info {symbol}: {result}")
            return {}

        data_raw = result.get("data", [])
        # API returns list — find our symbol
        raw = {}
        if isinstance(data_raw, list):
            for item in data_raw:
                if item.get("symbol") == symbol:
                    raw = item
                    break
            if not raw and data_raw:
                raw = data_raw[0]  # fallback
        elif isinstance(data_raw, dict):
            raw = data_raw

        info = {
            "min_qty": float(raw.get("tradeMinQuantity", 0)),
            "min_notional": float(raw.get("tradeMinUSDT", 0)),
            "max_leverage": 0,  # will fill from /trade/leverage below
            "price_precision": int(raw.get("pricePrecision", 1)),
            "quantity_precision": int(raw.get("quantityPrecision", 3)),
            "maint_margin_rate": float(raw.get("maintainMarginRate", 0)),
        }

        # Fetch max leverage from /trade/leverage (not in /quote/contracts)
        # This endpoint is heavily rate-limited. Use hardcoded fallback if API fails.
        info["max_leverage"] = _MAX_LEVERAGE_DEFAULTS.get(symbol, 25)
        for _lev_attempt in range(2):
            try:
                time.sleep(1)
                lev_res = _request("GET", "/openApi/swap/v2/trade/leverage", {"symbol": symbol, "side": "LONG"})
                if lev_res.get("code") == 0:
                    lev_data = lev_res.get("data", {})
                    api_max = int(lev_data.get("maxLongLeverage", 0))
                    if api_max > 0:
                        info["max_leverage"] = api_max
                        _logger.info(f"📊 MAX_LEV {symbol}: {api_max}x (from API)")
                    break
                elif lev_res.get("code") == 100410:  # rate limit
                    _logger.debug(f"⏳ Rate limited on leverage {symbol}, using default={info['max_leverage']}x")
                    break
            except Exception:
                pass

        _CONTRACT_INFO_CACHE[symbol] = {"data": info, "ts": now}
        return info

    except Exception as e:
        _logger.error(f"❌ Error get_contract_info({symbol}): {e}")
        return {}


def get_max_leverage(symbol: str) -> int:
    """Return max_leverage dari contract info."""
    info = get_contract_info(symbol)
    return info.get("max_leverage", 0)


def get_min_notional(symbol: str) -> float:
    """Return min_notional dari contract info (untuk entry/market orders)."""
    info = get_contract_info(symbol)
    return info.get("min_notional", 0)


# Trigger/conditional order min notional — BingX enforce HIGHER min notional for TP/SL
# Source: BingX API error "The minimum size per order is X USDT" on TAKE_PROFIT_MARKET
_TRIGGER_MIN_NOTIONAL = {
    "ETH-USDT": 18.63,
    "BTC-USDT": 100.0,
}
_TRIGGER_MIN_NOTIONAL_MULT = 8  # fallback: multiplier dari tradeMinUSDT


def get_trigger_min_notional(symbol: str) -> float:
    """Return min_notional untuk trigger orders (TP/SL). Lebih tinggi dari trade min."""
    if symbol in _TRIGGER_MIN_NOTIONAL:
        return _TRIGGER_MIN_NOTIONAL[symbol]
    trade_min = get_min_notional(symbol)
    return trade_min * _TRIGGER_MIN_NOTIONAL_MULT if trade_min > 0 else 20.0


# ─────────────────────────────────────────────
#  FUNDING RATE
# ─────────────────────────────────────────────

def get_funding_rate(symbol: str) -> float:
    """Ambil funding rate saat ini untuk symbol."""
    import logging as _log
    _logger = _log.getLogger(__name__)

    try:
        result = _request("GET", "/openApi/swap/v2/quote/premiumIndex", {"symbol": symbol})
        if result.get("code") == 0:
            data = result.get("data", {})
            return float(data.get("lastFundingRate", 0))
        _logger.warning(f"⚠️ Gagal ambil funding rate {symbol}: {result}")
        return 0.0
    except Exception as e:
        _logger.error(f"❌ Error get_funding_rate({symbol}): {e}")
        return 0.0


# ─────────────────────────────────────────────
#  ORDER BOOK
# ─────────────────────────────────────────────

def get_order_book(symbol: str, limit: int = 5) -> dict:
    """Ambil order book. Return {bids: [[price, qty], ...], asks: [...]}."""
    import logging as _log
    _logger = _log.getLogger(__name__)

    try:
        result = _request("GET", "/openApi/swap/v2/quote/depth", {
            "symbol": symbol,
            "limit": limit,
        })
        if result.get("code") == 0:
            data = result.get("data", {})
            return {
                "bids": data.get("bids", []),
                "asks": data.get("asks", []),
            }
        _logger.warning(f"⚠️ Gagal ambil order book {symbol}: {result}")
        return {"bids": [], "asks": []}
    except Exception as e:
        _logger.error(f"❌ Error get_order_book({symbol}): {e}")
        return {"bids": [], "asks": []}


def check_order_book_depth(symbol: str, side: str, qty: float) -> dict:
    """
    Analisis order book untuk estimasi slippage.
    side: 'BUY' (ambil dari asks) atau 'SELL' (ambil dari bids).
    Return: {estimated_slippage_pct, fillable_at_price, enough_liquidity}
    """
    book = get_order_book(symbol, limit=20)
    levels = book["asks"] if side.upper() == "BUY" else book["bids"]

    if not levels:
        return {"estimated_slippage_pct": 0.0, "fillable_at_price": 0.0, "enough_liquidity": False}

    # levels: [[price, qty], ...]
    best_price = float(levels[0][0])
    remaining = qty
    worst_price = best_price

    for price_str, qty_str in levels:
        price = float(price_str)
        level_qty = float(qty_str)
        if remaining <= 0:
            break
        worst_price = price
        remaining -= level_qty

    # slippage dari best price
    if best_price > 0:
        slippage_pct = abs(worst_price - best_price) / best_price * 100
    else:
        slippage_pct = 0.0

    enough = remaining <= 0

    return {
        "estimated_slippage_pct": round(slippage_pct, 4),
        "fillable_at_price": worst_price,
        "enough_liquidity": enough,
    }


