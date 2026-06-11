import os
import json
import logging
import sys
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
log = logging.getLogger(__name__)

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "7809584261")

import threading

def run_async_execution(data, pair, signal, price, sl, tp1, tp2, tp3, tp4, TG_TOKEN, TG_CHAT_ID):
    import time
    t0 = time.time()
    try:
        sys.path.insert(0, os.path.dirname(__file__))
        import order_manager

        result = order_manager.execute_signal({
            "symbol": pair, "action": signal, "price": price,
            "sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3, "tp4": tp4
        })

        dt = time.time() - t0
        log.info(f"Executed asynchronously in {dt:.1f}s: {result}")

        try:
            import requests as r
            msg = (
                f"⚡ *SINYAL DIEKSEKUSI ({dt:.1f}s)*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"🪙 *Pair:* `{pair}`\n"
                f"📈 *Action:* `{signal}`\n"
                f"💵 *Entry:* `{price}`\n"
                f"🛑 *Stop Loss:* `{sl}`\n"
                f"🎯 *TP1:* `{tp1}` | *TP2:* `{tp2}`\n"
                f"🎯 *TP3:* `{tp3}` | *TP4:* `{tp4}`\n"
                f"Result: `{result.get('status')}`\n"
                f"━━━━━━━━━━━━━━━━━━━━━"
            )
            r.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                  json={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=5)
        except Exception as tg_err:
            log.error(f"Gagal kirim Telegram: {tg_err}")
    except Exception as e:
        log.error(f"Error in background execution: {e}")

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body) if body else {}
            log.info(f"POST {self.path}: {json.dumps(data)[:200]}")

            if self.path == "/tradingview":
                # 1. Validasi Keamanan WEBHOOK_SECRET
                incoming_secret = data.get("secret")
                expected_secret = os.getenv("WEBHOOK_SECRET", "")
                if expected_secret and incoming_secret != expected_secret:
                    log.warning(f"Unauthorized access attempt: secret mismatch")
                    self._respond(401, {"error": "unauthorized"})
                    return

                # 2. Parsing Data
                is_zignaly = "key" in data and "exchange" in data
                if is_zignaly:
                    pair = data.get("pair", "").upper().replace(".P", "")
                    if "USDT" in pair and not pair.endswith("-USDT"):
                        pair = pair.replace("USDT", "-USDT")
                    entry_side = data.get("entrySide", "").upper()
                    signal = "BUY" if entry_side == "LONG" else "SELL"
                    price = float(data.get("entryLimitPrice") or 0)
                    sl = float(data.get("stopLossPrice") or 0)
                    tp1 = float(data.get("takeProfitPrice1") or 0)
                    tp2 = float(data.get("takeProfitPrice2") or 0)
                    tp3 = float(data.get("takeProfitPrice3") or 0)
                    tp4 = float(data.get("takeProfitPrice4") or 0)
                else:
                    signal = (data.get("signal") or data.get("action") or "").upper()
                    pair = data.get("symbol", "").upper().replace(".P", "")
                    if "-USDT" not in pair: pair += "-USDT"
                    price = float(data.get("price") or 0)
                    sl = float(data.get("sl") or 0)
                    tp1 = float(data.get("tp1") or 0)
                    tp2 = float(data.get("tp2") or 0)
                    tp3 = float(data.get("tp3") or 0)
                    tp4 = float(data.get("tp4") or 0)

                # 3. Validasi Dasar
                if signal not in ("BUY", "SELL", "LONG", "SHORT"):
                    self._respond(400, {"error": "invalid signal"})
                    return
                if pair not in ("BTC-USDT", "ETH-USDT"):
                    self._respond(200, {"status": "ignored", "reason": "symbol not allowed"})
                    return

                # 4. Jalankan Eksekusi secara Asinkron
                threading.Thread(
                    target=run_async_execution,
                    args=(data, pair, signal, price, sl, tp1, tp2, tp3, tp4, TG_TOKEN, TG_CHAT_ID),
                    daemon=True
                ).start()

                # 5. Segera respon ke TradingView
                self._respond(200, {"status": "accepted", "message": "Signal received and executing"})
            else:
                self._respond(404, {"error": "not found"})
        except Exception as e:
            log.error(f"Error: {e}")
            self._respond(500, {"error": str(e)})

    def _respond(self, code, body):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def log_message(self, fmt, *args):
        log.info(f"HTTP: {fmt % args}")


def start_background_monitor():
    import time
    import threading
    import order_manager
    
    def monitor_loop():
        log.info("📡 Background monitor thread untuk trailing SL aktif...")
        while True:
            try:
                order_manager.monitor_and_sync_positions()
            except Exception as e:
                log.error(f"Error di background monitor loop: {e}")
            time.sleep(15) # Jalankan setiap 15 detik
            
    t = threading.Thread(target=monitor_loop, daemon=True)
    t.start()


if __name__ == "__main__":
    # Cetak info env PORT saat startup
    raw_port = os.getenv("PORT")
    log.info(f"Railway Raw PORT env: {raw_port}")
    
    # Aktifkan background monitor (default nonaktif untuk isolasi debug koneksi)
    if os.getenv("ENABLE_MONITOR", "false").lower() == "true":
        start_background_monitor()
    else:
        log.info("📡 Background monitor thread dinonaktifkan (Mode Debug Koneksi).")
    
    port = int(raw_port or 5000)
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    log.info(f"Listening on :{port}")
    server.serve_forever()
