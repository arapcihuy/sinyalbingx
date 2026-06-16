import os
import sys
import time
import logging

# Tambahkan project root ke path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MockedServer")

# Mock bingx_client sebelum diimpor oleh webhook_server
import bingx_client

# Simpan request asli
original_request = bingx_client._request

def mocked_request(method, path, params=None):
    # Simulasikan delay jaringan (misal: API BingX sedang lambat)
    # Kami akan memberikan delay 1.5 detik untuk endpoint tertentu
    if "/quote/contracts" in path:
        logger.info(f"[MOCK] Memanggil Contracts untuk {params.get('symbol')}, menunda 1.5s...")
        time.sleep(1.5)
        # Kembalikan mock data contracts jika symbol diizinkan
        symbol = params.get('symbol') if params else "BTC-USDT"
        return {
            "code": 0,
            "msg": "",
            "data": [{
                "symbol": symbol,
                "status": 1,
                "displayName": symbol
            }]
        }
    elif "/quote/price" in path:
        logger.info(f"[MOCK] Memanggil Price, menunda 0.5s...")
        time.sleep(0.5)
        return {"code": 0, "msg": "", "data": {"price": "60000.00"}}
    else:
        # Fallback ke request asli jika private endpoint atau lainnya
        return original_request(method, path, params)

bingx_client._request = mocked_request

# Sekarang impor dan jalankan webhook_server
import webhook_server

if __name__ == "__main__":
    raw_port = os.getenv("PORT")
    port = int(raw_port or 8080)
    
    # Nonaktifkan telegram polling dan monitor agar bersih
    webhook_server.start_background_monitor = lambda: logger.info("[MOCK] Monitor disabled")
    webhook_server.start_telegram_bot_polling = lambda: logger.info("[MOCK] Telegram polling disabled")
    webhook_server.run_autonomous_self_test_loop = lambda: logger.info("[MOCK] Self-test loop disabled")
    
    from http.server import ThreadingHTTPServer
    server = ThreadingHTTPServer(("0.0.0.0", port), webhook_server.Handler)
    logger.info(f"[MOCK SERVER] Listening on :{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Mocked server stopped.")
