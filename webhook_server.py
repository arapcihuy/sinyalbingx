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
        import state_manager
        if self.path in ("/health", "/"):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
        elif self.path == "/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            mode = state_manager.get_trading_mode()
            self.wfile.write(json.dumps(mode).encode())
        else:
            self.send_response(404)
            self.end_headers()

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


def run_autonomous_self_test_loop():
    import time
    import requests
    import state_manager
    import bingx_client as bx
    
    # Tunggu 5 detik agar server HTTP siap mengikat port saat boot
    time.sleep(5)
    
    while True:
        try:
            log.info("🧪 Memulai Uji Mandiri Sistem (Self-Test Loop)...")
            
            # Target mode ditentukan oleh Env Var
            env_paper = os.getenv("PAPER_MODE", "false").lower() == "true"
            env_demo = os.getenv("USE_DEMO", "false").lower() == "true"
            
            # Simpan state status sebelumnya
            prev_mode = state_manager.get_trading_mode()
            
            # Set mode sementara ke target untuk menguji endpoint target
            state_manager.set_mode(env_paper, env_demo, "TESTING_CONNECTION")
            
            # 1. Tes Inbound Jaringan Publik ke dirinya sendiri
            domain = "sinyal-bingx-production.up.railway.app"
            test_url = f"https://{domain}/health"
            inbound_ok = False
            try:
                res = requests.get(test_url, timeout=10)
                if res.status_code == 200 and b"OK" in res.content:
                    inbound_ok = True
                    log.info(f"✅ SELF-TEST: Inbound Jaringan Publik ({test_url}) SUKSES.")
                else:
                    log.error(f"❌ SELF-TEST: Inbound Jaringan Publik gagal. Status: {res.status_code}")
            except Exception as e:
                log.error(f"❌ SELF-TEST: Inbound Jaringan Publik mengalami error: {e}")
                
            # 2. Tes API BingX
            bingx_ok = False
            api_err_msg = ""
            try:
                price = bx.get_current_price("BTC-USDT")
                if price > 0:
                    try:
                        # Panggil private endpoint untuk verifikasi validitas API keys
                        balance = bx.get_balance()
                        bingx_ok = True
                        log.info(f"✅ SELF-TEST: Koneksi & API Key BingX SUKSES. Harga BTC: {price} | Saldo: {balance} USDT")
                    except Exception as bal_err:
                        api_err_msg = f"Validasi Saldo Gagal ({str(bal_err)})"
                        log.error(f"❌ SELF-TEST: Koneksi API OK tetapi validasi API Key / Saldo GAGAL: {bal_err}")
                else:
                    api_err_msg = "Harga BTC 0"
                    log.error("❌ SELF-TEST: Koneksi API BingX mengembalikan harga 0.")
            except Exception as e:
                api_err_msg = f"Koneksi Error ({str(e)})"
                log.error(f"❌ SELF-TEST: Koneksi API BingX mengalami error: {e}")
                
            # Logika Promosi / Demotasi Mode Trading (Internal Tanpa Notif Telegram)
            if inbound_ok and bingx_ok:
                if not env_paper and not env_demo:
                    state_manager.promote_to_live()
                    if prev_mode["system_status"] != "LIVE":
                        log.info("🚀 SELF-TEST: Koneksi & API sehat. Bot dipromosikan ke LIVE MODE (Uang Asli).")
                else:
                    state_manager.demote_to_safe_mode("Dibatasi oleh konfigurasi Env Var (PAPER_MODE/USE_DEMO=true)")
                    if not prev_mode["system_status"].startswith("SAFE_MODE"):
                        log.info("🔒 SELF-TEST: Koneksi sehat, tetapi bot tetap di SAFE MODE sesuai konfigurasi env var.")
            else:
                reason = []
                if not inbound_ok: reason.append("Inbound Jaringan Error")
                if not bingx_ok: reason.append(f"API BingX Error: {api_err_msg}")
                err_msg = ", ".join(reason)
                state_manager.demote_to_safe_mode(err_msg)
                log.warning(f"🚨 SELF-TEST: Gagal ({err_msg}). Bot dikunci di SAFE MODE (Simulasi) demi keamanan dana.")
                
        except Exception as e:
            log.error(f"❌ Error dalam loop Self-Test: {e}")
            
        # Jalankan loop setiap 5 menit
        time.sleep(300)


# ─────────────────────────────────────────────
#  TELEGRAM BOT COMMAND RESPONDERS
# ─────────────────────────────────────────────
import telebot

bot = None
if TG_TOKEN:
    try:
        bot = telebot.TeleBot(TG_TOKEN)
        log.info("🤖 pyTelegramBotAPI initialized successfully.")
    except Exception as e:
        log.error(f"❌ Failed to initialize TeleBot: {e}")

if bot:
    # Middleware untuk validasi Chat ID (Cybersecurity Guard)
    def is_authorized(message):
        allowed_ids = [str(TG_CHAT_ID), "7809584261"]
        admin_id = os.getenv("TELEGRAM_ADMIN_ID")
        if admin_id:
            allowed_ids.append(str(admin_id))
            
        authorized = str(message.chat.id) in allowed_ids
        if not authorized:
            log.warning(f"🔒 Unauthorized access attempt from Chat ID: {message.chat.id}")
            try:
                bot.reply_to(message, f"⚠️ *Akses Ditolak:* Anda tidak memiliki izin untuk mengontrol bot ini.\n\n👤 *ID Telegram Anda:* `{message.chat.id}`\n🔑 *Solusi:* Silakan daftarkan ID ini di environment variable `TELEGRAM_ADMIN_ID` pada dashboard Railway.", parse_mode="Markdown")
            except:
                pass
        return authorized

    @bot.message_handler(commands=['status'])
    def handle_status(message):
        if not is_authorized(message):
            return
        try:
            import state_manager
            import order_manager
            import bingx_client as bx
            
            mode = state_manager.get_trading_mode()
            paper_mode = mode["paper_mode"]
            status_str = mode["system_status"]
            
            if paper_mode:
                trades = order_manager.load_paper_trades()
                open_trades = [t for t in trades if t.get("status") == "OPEN_PAPER"]
                pos_count = len(open_trades)
                pos_details = "\n".join([f"• `{t['symbol']}` ({t['side']}) Entry: `{t['entry']}` | SL: `{t['sl']}`" for t in open_trades])
            else:
                positions = bx.get_open_positions()
                pos_count = len(positions)
                pos_details = "\n".join([f"• `{p['symbol']}` ({p['positionSide']}) x{p['leverage']} Qty: `{abs(float(p['positionAmt']))}` @ `{p['avgPrice']}`" for p in positions])
                
            response = (
                f"📊 *STATUS BOT TRADING*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"⚙️ *Mode Trading:* `{'PAPER / SIMULASI' if paper_mode else 'LIVE / UANG ASLI'}`\n"
                f"📡 *Status Koneksi:* `{status_str}`\n"
                f"📈 *Posisi Terbuka:* `{pos_count} / 3`\n"
                f"{pos_details if pos_details else '• (Tidak ada posisi aktif)'}\n"
                f"━━━━━━━━━━━━━━━━━━━━━"
            )
            bot.reply_to(message, response, parse_mode="Markdown")
        except Exception as e:
            log.error(f"Error handling /status command: {e}")
            bot.reply_to(message, f"❌ Gagal memproses /status: {str(e)}")

    @bot.message_handler(commands=['balance'])
    def handle_balance(message):
        if not is_authorized(message):
            return
        try:
            import state_manager
            import order_manager
            import bingx_client as bx
            
            mode = state_manager.get_trading_mode()
            paper_mode = mode["paper_mode"]
            
            if paper_mode:
                trades = order_manager.load_paper_trades()
                closed_pnl = sum([t.get("pnl_usdt", 0) for t in trades if t.get("status", "").startswith("CLOSED")])
                balance = 1000.0 + closed_pnl
                response = (
                    f"💵 *SALDO SIMULASI (PAPER)*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"💰 *Total Equity:* `${balance:.2f} USDT`\n"
                    f"📝 *Catatan:* Berjalan di akun virtual/demo lokal.\n"
                    f"━━━━━━━━━━━━━━━━━━━━━"
                )
            else:
                balance = bx.get_balance()
                response = (
                    f"💵 *SALDO LIVE BINGX*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"💰 *Total Equity (Live):* `${balance:.2f} USDT`\n"
                    f"━━━━━━━━━━━━━━━━━━━━━"
                )
            bot.reply_to(message, response, parse_mode="Markdown")
        except Exception as e:
            log.error(f"Error handling /balance command: {e}")
            bot.reply_to(message, f"❌ Gagal memproses /balance: {str(e)}")

    @bot.message_handler(commands=['pnl'])
    def handle_pnl(message):
        if not is_authorized(message):
            return
        try:
            import state_manager
            import order_manager
            import bingx_client as bx
            
            mode = state_manager.get_trading_mode()
            paper_mode = mode["paper_mode"]
            
            if paper_mode:
                trades = order_manager.load_paper_trades()
                closed_trades = [t for t in trades if t.get("status", "").startswith("CLOSED")]
                open_trades = [t for t in trades if t.get("status") == "OPEN_PAPER"]
                total_pnl = sum([t.get("pnl_usdt", 0) for t in closed_trades])
                
                response = (
                    f"📊 *LAPORAN PnL (PAPER)*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"✅ *Trade Tertutup:* `{len(closed_trades)}`\n"
                    f"🟢 *Trade Terbuka:* `{len(open_trades)}`\n"
                    f"💰 *Total PnL Bersih:* `{'+' if total_pnl >= 0 else ''}${total_pnl:.2f} USDT`\n"
                    f"━━━━━━━━━━━━━━━━━━━━━"
                )
            else:
                positions = bx.get_open_positions()
                unrealized_pnl = sum([float(p.get("unrealizedProfit", 0)) for p in positions])
                
                income = bx.get_income_history(days=7)
                realized_pnl = sum([float(inc.get("income", 0)) for inc in income if inc.get("incomeType") in ["REALIZED_PNL", "COMMISSION"]])
                
                total_pnl = realized_pnl + unrealized_pnl
                
                response = (
                    f"📊 *LAPORAN PnL LIVE (7 HARI TERAKHIR)*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🟢 *PnL Mengambang:* `${unrealized_pnl:.2f} USDT`\n"
                    f"💵 *PnL Terealisasi:* `${realized_pnl:.2f} USDT`\n"
                    f"💰 *Estimasi Total PnL:* `{'+' if total_pnl >= 0 else ''}${total_pnl:.2f} USDT`\n"
                    f"━━━━━━━━━━━━━━━━━━━━━"
                )
            bot.reply_to(message, response, parse_mode="Markdown")
        except Exception as e:
            log.error(f"Error handling /pnl command: {e}")
            bot.reply_to(message, f"❌ Gagal memproses /pnl: {str(e)}")

    @bot.message_handler(commands=['settings'])
    def handle_settings(message):
        if not is_authorized(message):
            return
        try:
            auto_entry = os.getenv("AUTO_ENTRY", "true")
            margin_mode = os.getenv("MARGIN_MODE", "ISOLATED")
            leverage = os.getenv("LEVERAGE", "5")
            risk_pct = os.getenv("RISK_PER_TRADE_PERCENT", "2.0")
            webhook_url = os.getenv("WEBHOOK_URL", "-")
            
            # Mask API Key untuk keamanan
            api_key = os.getenv("BINGX_API_KEY", "")
            masked_key = f"{api_key[:6]}...{api_key[-6:]}" if len(api_key) > 12 else "Tidak Dikonfigurasi"
            
            response = (
                f"⚙️ *PENGATURAN BOT TRADING*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"🪙 *API Key BingX:* `{masked_key}`\n"
                f"🛡️ *Leverage:* `{leverage}x`\n"
                f"🎯 *Margin Mode:* `{margin_mode}`\n"
                f"⚠️ *Risk per Trade:* `{risk_pct}%`\n"
                f"🤖 *Auto Entry:* `{auto_entry}`\n"
                f"🌐 *Webhook URL:* `{webhook_url}`\n"
                f"━━━━━━━━━━━━━━━━━━━━━"
            )
            bot.reply_to(message, response, parse_mode="Markdown")
        except Exception as e:
            log.error(f"Error handling /settings command: {e}")
            bot.reply_to(message, f"❌ Gagal memproses /settings: {str(e)}")

def start_telegram_bot_polling():
    if bot:
        def polling_thread():
            log.info("📡 Memulai polling Telegram bot di background thread...")
            while True:
                try:
                    bot.infinity_polling(timeout=30, long_polling_timeout=10)
                except Exception as ex:
                    log.error(f"⚠️ Error polling Telegram: {ex}")
                    time.sleep(10)
        t = threading.Thread(target=polling_thread, daemon=True)
        t.start()


if __name__ == "__main__":
    # Cetak info env PORT saat startup
    raw_port = os.getenv("PORT")
    log.info(f"Railway Raw PORT env: {raw_port}")
    
    # Aktifkan background monitor (default aktif demi pemantauan posisi otomatis)
    if os.getenv("ENABLE_MONITOR", "true").lower() == "true":
        start_background_monitor()
    else:
        log.info("📡 Background monitor thread dinonaktifkan via env var.")
    
    # Jalankan Autonomous Self-Test loop secara asinkron di latar belakang
    threading.Thread(target=run_autonomous_self_test_loop, daemon=True).start()
    
    # Jalankan Telegram bot polling secara asinkron di latar belakang
    start_telegram_bot_polling()
    
    port = int(raw_port or 8080)
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    log.info(f"Listening on :{port}")
    server.serve_forever()
