import os
import json
import logging
import sys
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=5)

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
log = logging.getLogger(__name__)

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

import threading

def run_async_execution(data, pair, signal, price, sl, tp1, tp2, tp3, tp4, TG_TOKEN, TG_CHAT_ID):
    import time
    t0 = time.time()
    try:
        sys.path.insert(0, os.path.dirname(__file__))
        import order_manager

        # ── RUN AI SIGNAL FILTER ──
        approved = True
        ai_reason = ""
        suggested_params = {}
        try:
            from ai_trading.gemini_filter import validate_signal
            log.info(f"🧠 Memulai filter AI untuk {pair} {signal}...")
            res = validate_signal(
                pair=pair,
                action=signal,
                price=float(price or 0),
                sl=float(sl or 0),
                tp1=float(tp1 or 0),
                tp2=float(tp2 or 0)
            )
            if isinstance(res, tuple) and len(res) == 3:
                approved, ai_reason, suggested_params = res
            else:
                approved, ai_reason = res
                suggested_params = {}
        except Exception as filter_err:
            log.warning(f"⚠️ Gagal memanggil AI filter: {filter_err}. Melanjutkan eksekusi tanpa filter.")

        # ── INISIALISASI DATABASE LOGGER ──
        db_logger = None
        row_id = -1
        try:
            from ai_trading import db_logger
            row_id = db_logger.log_validation(
                pair=pair,
                action=signal,
                price=float(price or 0),
                sl=float(sl or 0),
                tp1=float(tp1 or 0),
                tp2=float(tp2 or 0),
                approved=approved,
                reason=ai_reason,
                status="rejected_by_ai" if not approved else "pending",
                suggested_sl=suggested_params.get("suggested_sl"),
                suggested_tp1=suggested_params.get("suggested_tp1"),
                suggested_tp2=suggested_params.get("suggested_tp2"),
                suggested_leverage=suggested_params.get("suggested_leverage")
            )
        except Exception as db_err:
            log.warning(f"⚠️ Gagal mencatat log validasi AI ke database: {db_err}")

        if approved:
            # Overwrite parameter asli dengan saran dinamis dari AI jika tersedia
            final_sl = suggested_params.get("suggested_sl") or sl
            final_tp1 = suggested_params.get("suggested_tp1") or tp1
            final_tp2 = suggested_params.get("suggested_tp2") or tp2
            final_leverage = suggested_params.get("suggested_leverage")
            
            if any([
                suggested_params.get("suggested_sl"),
                suggested_params.get("suggested_tp1"),
                suggested_params.get("suggested_tp2"),
                suggested_params.get("suggested_leverage")
            ]):
                log.info(f"🧠 AI PARAMETER OVERWRITE: SL={final_sl} (TV: {sl}) | TP1={final_tp1} (TV: {tp1}) | TP2={final_tp2} (TV: {tp2}) | Leverage={final_leverage}")

            result = order_manager.execute_signal({
                "symbol": pair, "action": signal, "price": price,
                "sl": final_sl, "tp1": final_tp1, "tp2": final_tp2, "tp3": tp3, "tp4": tp4,
                "leverage": final_leverage
            })
            # Perbarui status eksekusi ril ke database
            if db_logger and row_id != -1:
                try:
                    db_logger.update_log_status(row_id, result.get("status", "failed"))
                except Exception as db_up_err:
                    log.warning(f"⚠️ Gagal memperbarui status eksekusi di database: {db_up_err}")
        else:
            result = {
                "status": "rejected_by_ai",
                "symbol": pair,
                "reason": ai_reason
            }

        dt = time.time() - t0
        log.info(f"Executed asynchronously in {dt:.1f}s: {result}")

        try:
            import requests as r
            status = result.get("status", "failed")
            
            # 1. Tentukan Header & Emoji Indikator
            if status in ["success", "success_paper"]:
                mode_label = "PAPER" if status == "success_paper" else "LIVE"
                header = f"🟢 *ENTRY BERHASIL ({mode_label})*"
            elif status in ["already_open", "slots_full", "ignored_by_scanner", "rejected_by_ai"]:
                reason_map = {
                    "already_open": "Posisi sudah terbuka di bursa/simulasi.",
                    "slots_full": "Slot posisi aktif sudah penuh (maksimal 3).",
                    "ignored_by_scanner": "Diabaikan oleh scanner karena expectancy rendah.",
                    "rejected_by_ai": f"Ditolak AI:\n`{ai_reason}`"
                }
                header = f"🧠 *SINYAL DITOLAK AI*" if status == "rejected_by_ai" else f"🟡 *SINYAL DIABAIKAN*"
                reason_text = reason_map.get(status, f"Status: `{status}`")
            elif status in ["low_margin", "insufficient_balance"]:
                reason_map = {
                    "low_margin": "Margin tersedia di bursa terlalu kecil (< 20% equity).",
                    "insufficient_balance": "Saldo akun terlalu kecil untuk entri minimal."
                }
                header = f"🔴 *EKSEKUSI BATAL (MANAJEMEN MODAL)*"
                reason_text = reason_map.get(status, f"Status: `{status}`")
            else:
                header = f"🔴 *EKSEKUSI GAGAL*"
                reason_text = f"Detail: `{status}`"

            # 2. Ambil parameter tambahan dari state jika berhasil
            extra_details = ""
            if status in ["success", "success_paper"]:
                try:
                    trade_info = order_manager.active_trade_data.get(pair)
                    if trade_info:
                        lev = trade_info.get("leverage", 0)
                        risk = trade_info.get("risk_pct", 0.0)
                        ent = trade_info.get("entry_price", price) or price
                        t_qty = trade_info.get("qty", 0.0)
                        margin_val = (t_qty * ent) / lev if (lev and ent) else 0.0
                        
                        extra_details = (
                            f"🛡️ *Leverage:* `{lev}x` | *Risk:* `{risk}%`\n"
                            f"💰 *Margin:* `${margin_val:.2f} USDT` (Isolated)\n"
                        )
                except Exception as ex_err:
                    log.error(f"Gagal memuat detail trade tambahan: {ex_err}")

            # 3. Bangun isi pesan
            msg_lines = [
                f"{header}",
                f"━━━━━━━━━━━━━━━━━━━━━",
                f"🪙 *Pair:* `{pair}` ({'LONG' if signal in ['BUY', 'LONG'] else 'SHORT'})"
            ]
            
            if status in ["success", "success_paper"]:
                if extra_details:
                    msg_lines.append(extra_details.strip())
                
                # Visualisasikan coretan jika disarankan oleh AI
                sl_str = f"`{sl}`"
                if suggested_params.get("suggested_sl") and float(suggested_params["suggested_sl"]) != float(sl):
                    sl_str = f"~~`{sl}`~~ 🧠 `{suggested_params['suggested_sl']}`"
                    
                tp1_str = f"`{tp1}`"
                if suggested_params.get("suggested_tp1") and float(suggested_params["suggested_tp1"]) != float(tp1):
                    tp1_str = f"~~`{tp1}`~~ 🧠 `{suggested_params['suggested_tp1']}`"
                    
                tp2_str = f"`{tp2}`"
                if suggested_params.get("suggested_tp2") and float(suggested_params["suggested_tp2"]) != float(tp2):
                    tp2_str = f"~~`{tp2}`~~ 🧠 `{suggested_params['suggested_tp2']}`"
                
                msg_lines.extend([
                    f"💵 *Entry Price:* `{price if price > 0 else 'MARKET'}`",
                    f"🛑 *Stop Loss:* {sl_str}",
                    f"🎯 *TP1:* {tp1_str} | *TP2:* {tp2_str}"
                ])
                if tp3 > 0 or tp4 > 0:
                    msg_lines.append(f"🎯 *TP3:* `{tp3}` | *TP4:* `{tp4}`")
            else:
                msg_lines.append(f"⚠️ *Alasan:* {reason_text}")
                if price > 0:
                    msg_lines.append(f"💵 *Harga Sinyal:* `{price}`")
                
            msg_lines.append(f"⏱️ *Kecepatan:* `{dt:.2f}s`")
            msg_lines.append(f"━━━━━━━━━━━━━━━━━━━━━")
            
            msg = "\n".join(msg_lines)
            r.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                  json={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=5)
        except Exception as tg_err:
            log.error(f"Gagal kirim Telegram: {tg_err}")
    except Exception as e:
        log.error(f"Error in background execution: {e}")

import re

_TRADEABLE_SYMBOLS_CACHE = {"BTC-USDT", "ETH-USDT"}

def is_symbol_tradeable(symbol: str) -> bool:
    """Cek apakah symbol valid dan aktif di BingX (dengan caching)."""
    global _TRADEABLE_SYMBOLS_CACHE
    if symbol in _TRADEABLE_SYMBOLS_CACHE:
        return True
        
    try:
        import bingx_client as bx
        res = bx._request('GET', '/openApi/swap/v2/quote/contracts', {"symbol": symbol})
        if res.get("code") == 0 and res.get("data"):
            data = res["data"][0] if isinstance(res["data"], list) else res["data"]
            if int(data.get("status", 0)) == 1:
                _TRADEABLE_SYMBOLS_CACHE.add(symbol)
                log.info(f"✅ Symbol {symbol} validated dynamically and added to cache.")
                return True
            else:
                log.warning(f"⚠️ Symbol {symbol} exists but status is inactive ({data.get('status')}).")
        else:
            log.warning(f"❓ Symbol {symbol} not found or API error: {res}")
    except Exception as e:
        log.error(f"❌ Gagal verifikasi simbol {symbol} di BingX: {e}")
        
    return False

def clean_number(num_str):
    if not num_str:
        return 0.0
    num_str = str(num_str).strip()
    
    # Deteksi dan tangani format angka US dan Eropa/Indonesia secara dinamis
    if "," in num_str and "." in num_str:
        if num_str.rfind(",") < num_str.rfind("."):
            # Koma sebelum titik -> Format US (misal: 65,230.50) -> Hapus koma
            num_str = num_str.replace(",", "")
        else:
            # Titik sebelum koma -> Format Eropa/ID (misal: 65.230,50) -> Hapus titik, ganti koma dengan titik
            num_str = num_str.replace(".", "").replace(",", ".")
    elif "," in num_str:
        # Hanya ada koma (bisa ribuan US 65,230 atau desimal Eropa 65,23)
        parts = num_str.split(",")
        if len(parts[-1]) == 3 and len(parts) == 2:
            # Kemungkinan besar ribuan (misal: 65,000) -> Hapus koma
            num_str = num_str.replace(",", "")
        else:
            # Kemungkinan besar desimal (misal: 1,5) -> Ganti koma dengan titik
            num_str = num_str.replace(",", ".")
    elif "." in num_str:
        # Hanya ada titik (bisa ribuan Eropa/ID 65.000 atau desimal US 65230.50)
        parts = num_str.split(".")
        if len(parts[-1]) == 3 and len(parts) == 2:
            # Kemungkinan besar ribuan format Eropa/ID (misal: 65.000) -> Hapus titik
            num_str = num_str.replace(".", "")
            
    try:
        return float(num_str)
    except ValueError:
        return 0.0

def parse_plain_text_alert(text):
    # Proteksi: Abaikan pesan default order fill dari TradingView Strategy, kecuali jika merupakan sinyal Tradentix
    if (re.search(r"order\s+(buy|sell|long|short)\s+@", text, re.IGNORECASE) or "terisi pada" in text.lower()) and "tradentix" not in text.lower():
        log.warning(f"🛡️ Ignored default TradingView strategy order fill notification: {text[:120]}")
        return None

    data = {}
    
    # 0. Parse Secret/Password/Key dari body teks
    secret_match = re.search(r"(?:secret|password|key)\s*[:=]\s*(\S+)", text, re.IGNORECASE)
    if secret_match:
        data["secret"] = secret_match.group(1).strip()
    
    # 1. Parse Action
    action_match = re.search(r"(?:order|zone|side)?\s*(buy|sell|long|short)\s*(?:entry|zone|order|side)?", text, re.IGNORECASE)
    if re.search(r"✅\s*Buy|Buy Entry Zone|\b(buy|long)\b", text, re.IGNORECASE):
        data["action"] = "BUY"
    elif re.search(r"❎\s*Sell|Sell Entry Zone|\b(sell|short)\b", text, re.IGNORECASE):
        data["action"] = "SELL"
    elif action_match:
        act = action_match.group(1).upper()
        if act in ["LONG", "BUY"]:
            data["action"] = "BUY"
        elif act in ["SHORT", "SELL"]:
            data["action"] = "SELL"

    # 2. Parse Symbol
    symbol_match = re.search(r"#\s*([A-Z0-9]+)", text)
    if not symbol_match:
        symbol_match = re.search(r"Coin\s*:\s*([A-Z0-9]+)", text, re.IGNORECASE)
    if not symbol_match:
        symbol_match = re.search(r"(?:terisi pada|pada)\s+([A-Z0-9.-]+)", text, re.IGNORECASE)
        
    if symbol_match:
        symbol = symbol_match.group(1).upper()
        symbol = re.sub(r'[^A-Z0-9-]', '', symbol)
        symbol = symbol.replace("USDT.P", "USDT")
        if symbol.endswith("USDT") and "-" not in symbol:
            symbol = symbol[:-4] + "-USDT"
        data["symbol"] = symbol

    # 3. Parse Entry Price
    price_match = re.search(r"(?:entry zone|entry|harga|@)\s*:?\s*([0-9.,]+)", text, re.IGNORECASE)
    if not price_match:
        price_match = re.search(r"@\s*([0-9.,]+)", text)
        
    if price_match:
        data["price"] = clean_number(price_match.group(1))

    # 4. Parse Stop Loss
    sl_match = re.search(r"(?:stop-loss|stop target|sl)\s*:?\s*([0-9.,]+)", text, re.IGNORECASE)
    if sl_match:
        data["sl"] = clean_number(sl_match.group(1))

    # 5. Parse Take Profits
    for i in range(1, 5):
        tp_match = re.search(rf"(?:target {i}|take profit {i}|tp{i})\s*:?\s*([0-9.,]+)", text, re.IGNORECASE)
        if tp_match:
            data[f"tp{i}"] = clean_number(tp_match.group(1))

    if "action" in data and "symbol" in data:
        data["price"] = data.get("price", 0.0)
        data["sl"] = data.get("sl", 0.0)
        data["tp1"] = data.get("tp1", 0.0)
        return data
        
    return None

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        import state_manager
        path = self.path.split('?')[0].rstrip('/')
        if not path:
            path = "/"

        if path in ("/health", "/"):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
        elif path == "/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            mode = state_manager.get_trading_mode()
            self.wfile.write(json.dumps(mode).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        from urllib.parse import urlparse, parse_qs
        parsed_url = urlparse(self.path)
        path = parsed_url.path.rstrip('/')
        if not path:
            path = "/"
            
        query_params = {k: v[0] for k, v in parse_qs(parsed_url.query).items()}

        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            
            # Coba decode body
            text_body = body.decode('utf-8', errors='replace').strip() if body else ""
            
            data = {}
            is_json = True
            if text_body:
                try:
                    data = json.loads(text_body)
                except json.JSONDecodeError:
                    is_json = False

            # Jika bukan JSON, coba parsing sebagai teks biasa dari alert TradingView
            if not is_json and text_body:
                log.info(f"Mencoba memparsing body teks biasa: {text_body[:300]}")
                data = parse_plain_text_alert(text_body)
                if not data:
                    log.warning("Gagal memparsing sinyal dari teks biasa.")
                    self._respond(400, {"error": "Invalid payload format. Failed to parse plain text alert."})
                    return

            log.info(f"POST {path}: {json.dumps(data)[:200]}")

            if path == "/tradingview":
                # 1. Validasi Keamanan WEBHOOK_SECRET (JSON atau query params)
                import secrets
                incoming_secret = data.get("secret") or query_params.get("secret") or ""
                expected_secret = os.getenv("WEBHOOK_SECRET", "")
                if not expected_secret:
                    log.error("WEBHOOK_SECRET is not configured in environment. Rejecting request for security.")
                    self._respond(500, {"error": "Internal Server Error: Webhook configuration missing"})
                    return
                if not secrets.compare_digest(incoming_secret, expected_secret):
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
                if not is_symbol_tradeable(pair):
                    self._respond(200, {"status": "ignored", "reason": f"symbol {pair} not allowed or inactive"})
                    return

                # 4. Jalankan Eksekusi secara Asinkron (mask sensitive in logs)
                clean_payload = {k: ("***" if k in ["secret", "key", "password"] else v) for k, v in data.items()}
                log.info(f"📥 Webhook payload: {clean_payload}")
                executor.submit(
                    run_async_execution,
                    data, pair, signal, price, sl, tp1, tp2, tp3, tp4, TG_TOKEN, TG_CHAT_ID
                )

                # 5. Segera respon ke TradingView
                self._respond(200, {"status": "accepted", "message": "Signal received and executing", "pair": pair})
                log.info(f"✅ Webhook Responded: {pair} accepted.")
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
            webhook_url = os.getenv("WEBHOOK_URL", "")
            
            # Deteksi otomatis trycloudflare tunnel dari log jika diatur atau kosong
            if not webhook_url or "trycloudflare.com" in webhook_url:
                try:
                    if os.path.exists("bridge_tunnel.log"):
                        with open("bridge_tunnel.log", "r") as f:
                            lines = f.readlines()
                        for line in reversed(lines):
                            if "trycloudflare.com" in line:
                                import re
                                match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
                                if match:
                                    webhook_url = match.group(0)
                                    log.info(f"🔄 Terdeteksi Cloudflare Tunnel aktif: {webhook_url}")
                                    break
                except Exception as ex_log:
                    log.error(f"Gagal membaca URL dari bridge_tunnel.log: {ex_log}")

            inbound_ok = False
            if webhook_url:
                from urllib.parse import urlparse
                parsed = urlparse(webhook_url)
                domain = parsed.netloc or parsed.path
                test_url = f"https://{domain}/health"
                try:
                    res = requests.get(test_url, timeout=10)
                    if res.status_code == 200 and b"OK" in res.content:
                        inbound_ok = True
                        log.info(f"✅ SELF-TEST: Inbound Jaringan Publik ({test_url}) SUKSES.")
                    else:
                        log.error(f"❌ SELF-TEST: Inbound Jaringan Publik gagal. Status: {res.status_code}")
                except Exception as e:
                    log.error(f"❌ SELF-TEST: Inbound Jaringan Publik mengalami error: {e}")
            else:
                inbound_ok = True
                log.warning("⚠️ SELF-TEST: WEBHOOK_URL tidak dikonfigurasi. Melewati tes inbound eksternal.")
                
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
            if bingx_ok:
                if not env_paper and not env_demo:
                    state_manager.promote_to_live()
                    if prev_mode["system_status"] != "LIVE":
                        log.info("🚀 SELF-TEST: Koneksi & API sehat. Bot dipromosikan ke LIVE MODE (Uang Asli).")
                else:
                    state_manager.demote_to_safe_mode("Dibatasi oleh konfigurasi Env Var (PAPER_MODE/USE_DEMO=true)")
                    if not prev_mode["system_status"].startswith("SAFE_MODE"):
                        log.info("🔒 SELF-TEST: Koneksi sehat, tetapi bot tetap di SAFE MODE sesuai konfigurasi env var.")
            else:
                err_msg = f"API BingX Error: {api_err_msg}"
                state_manager.demote_to_safe_mode(err_msg)
                log.warning(f"🚨 SELF-TEST: Gagal ({err_msg}). Bot dikunci di SAFE MODE (Simulasi) demi keamanan dana.")
            
            if not inbound_ok:
                log.warning("⚠️ SELF-TEST: Inbound Jaringan Publik tidak dapat diverifikasi (kemungkinan DNS propagation delay). Sinyal TV tetap akan diterima jika tunnel sudah aktif.")
                
        except Exception as e:
            log.error(f"❌ Error dalam loop Self-Test: {e}")
            
        # Jalankan loop setiap 5 menit
        time.sleep(300)


# ─────────────────────────────────────────────
#  TELEGRAM BOT COMMAND RESPONDERS
# ─────────────────────────────────────────────
import telebot
from telebot import types as tg_types

def get_freshness_timestamp():
    import datetime
    return f"🕒 Diperbarui: {datetime.datetime.now().strftime('%d-%m-%Y %H:%M:%S')}"

bot = None
if TG_TOKEN:
    try:
        bot = telebot.TeleBot(TG_TOKEN)
        log.info("🤖 pyTelegramBotAPI initialized successfully.")
        try:
            bot.set_my_commands([
                telebot.types.BotCommand("status", "Cek status bot & detail posisi aktif (LIVE/PAPER)"),
                telebot.types.BotCommand("balance", "Cek saldo equity & margin bebas"),
                telebot.types.BotCommand("pnl", "Laporan floating & realized PnL berkala"),
                telebot.types.BotCommand("settings", "Lihat konfigurasi bot trading saat ini")
            ])
            log.info("📡 Clickable menu commands registered successfully in Telegram.")
        except Exception as cmd_err:
            log.error(f"❌ Gagal set menu commands Telegram: {cmd_err}")
    except Exception as e:
        log.error(f"❌ Failed to initialize TeleBot: {e}")

if bot:
    # Middleware untuk validasi Chat ID (Cybersecurity Guard)
    def is_authorized(message):
        allowed_ids = []
        if TG_CHAT_ID:
            allowed_ids.append(str(TG_CHAT_ID))
        admin_id = os.getenv("TELEGRAM_ADMIN_ID")
        if admin_id:
            allowed_ids.append(str(admin_id))
            
        authorized = str(message.chat.id) in allowed_ids
        if not authorized:
            log.warning(f"🔒 Unauthorized access attempt from Chat ID: {message.chat.id}")
            # Selalu balas untuk debugging user
            bot.reply_to(message, f"⚠️ *Akses Ditolak:* Anda tidak memiliki izin.\n\n👤 *ID Telegram Anda:* `{message.chat.id}`\n🔑 *Solusi:* Daftarkan ID ini di dashboard Railway sebagai `TELEGRAM_ADMIN_ID`.", parse_mode="Markdown")
        return authorized

    @bot.message_handler(commands=['status'])
    def handle_status(message):
        if not is_authorized(message):
            return
        try:
            import state_manager
            import order_manager
            import bingx_client as bx
            import time
            
            mode = state_manager.get_trading_mode()
            paper_mode = mode["paper_mode"]
            status_str = mode["system_status"]
            
            if paper_mode:
                trades = order_manager.load_paper_trades()
                open_trades = [t for t in trades if t.get("status") == "OPEN_PAPER"]
                pos_count = len(open_trades)
                
                pos_details_list = []
                for t in open_trades:
                    symbol = t["symbol"]
                    side = t["side"]
                    entry = float(t["entry"])
                    qty = float(t["qty"])
                    sl = float(t["sl"])
                    tp = float(t["tp"])
                    
                    try:
                        curr_price = bx.get_current_price(symbol)
                    except:
                        curr_price = entry
                        
                    if side == "LONG":
                        pnl = (curr_price - entry) * qty
                    else:
                        pnl = (entry - curr_price) * qty
                        
                    lev = 15
                    margin = (qty * entry) / lev
                    pnl_pct = (pnl / margin * 100) if margin > 0 else 0.0
                    
                    pnl_emoji = "🟢" if pnl >= 0 else "🔴"
                    pnl_sign = "+" if pnl >= 0 else ""
                    
                    detail = (
                        f"🪙 `{symbol}` ({'🟢 LONG' if side == 'LONG' else '🔴 SHORT'})\n"
                        f"  ├─ Leverage: `{lev}x` | Margin: `Isolated`\n"
                        f"  ├─ Entry: `${entry:.4f}` ➔ Current: `${curr_price:.4f}`\n"
                        f"  ├─ Size: `{qty} Qty` | Margin: `${margin:.2f} USDT`\n"
                        f"  ├─ Unrealized PnL: `{pnl_sign}{pnl:.2f} USDT ({pnl_sign}{pnl_pct:.2f}%)` {pnl_emoji}\n"
                        f"  └─ Targets: SL `${sl:.4f}` | TP `${tp:.4f}`"
                    )
                    pos_details_list.append(detail)
                pos_details = "\n\n".join(pos_details_list)
            else:
                positions = bx.get_open_positions()
                pos_count = len(positions)
                
                pos_details_list = []
                for p in positions:
                    symbol = p["symbol"]
                    side = p["positionSide"]
                    lev = int(p["leverage"])
                    amt = abs(float(p["positionAmt"]))
                    entry = float(p["avgPrice"])
                    
                    try:
                        curr_price = bx.get_current_price(symbol)
                    except:
                        curr_price = entry
                        
                    unrealized_pnl = float(p.get("unrealizedProfit", 0.0))
                    margin = float(p.get("margin", 0.0))
                    pnl_pct = (unrealized_pnl / margin * 100) if margin > 0 else 0.0
                    
                    pnl_emoji = "🟢" if unrealized_pnl >= 0 else "🔴"
                    pnl_sign = "+" if unrealized_pnl >= 0 else ""
                    
                    sl_price = 0.0
                    tp_list = []
                    try:
                        orders_res = bx._request("GET", "/openApi/swap/v2/trade/openOrders", {"symbol": symbol})
                        open_orders = orders_res.get("data", [])
                        if isinstance(open_orders, dict):
                            open_orders = open_orders.get("orders", [])
                        
                        for o in open_orders:
                            o_type = o.get("type", "")
                            if "STOP" in o_type:
                                sl_price = float(o.get("stopPrice", 0.0))
                            elif "TAKE_PROFIT" in o_type:
                                tp_list.append(float(o.get("stopPrice", 0.0)))
                    except:
                        pass
                    
                    tp_str = " | ".join([f"TP{i+1} `${val:.4f}`" for i, val in enumerate(tp_list)]) if tp_list else "Belum dipasang"
                    sl_str = f"`${sl_price:.4f}`" if sl_price > 0 else "Belum dipasang"
                    
                    detail = (
                        f"🪙 `{symbol}` ({'🟢 LONG' if side == 'LONG' else '🔴 SHORT'})\n"
                        f"  ├─ Leverage: `{lev}x` | Margin: `Isolated`\n"
                        f"  ├─ Entry: `${entry:.4f}` ➔ Current: `${curr_price:.4f}`\n"
                        f"  ├─ Size: `{amt} Qty` | Margin: `${margin:.2f} USDT`\n"
                        f"  ├─ Unrealized PnL: `{pnl_sign}{unrealized_pnl:.2f} USDT ({pnl_sign}{pnl_pct:.2f}%)` {pnl_emoji}\n"
                        f"  └─ Targets: SL {sl_str} | {tp_str}"
                    )
                    pos_details_list.append(detail)
                pos_details = "\n\n".join(pos_details_list)
                
            response = (
                f"📊 *STATUS BOT TRADING*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"⚙️ *Mode Trading:* `{'PAPER / SIMULASI' if paper_mode else 'LIVE / UANG ASLI'}`\n"
                f"📡 *Status Koneksi:* `{status_str}`\n"
                f"📈 *Posisi Terbuka:* `{pos_count} Posisi` (Tanpa Batas)\n\n"
                f"{pos_details if pos_details else '• (Tidak ada posisi aktif)'}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"{get_freshness_timestamp()}"
            )
            markup = tg_types.InlineKeyboardMarkup(row_width=2)
            btn_sync = tg_types.InlineKeyboardButton("🚀 AUTO-SYNC TP", callback_data="sync_tpsl")
            btn_refresh = tg_types.InlineKeyboardButton("🔄 REFRESH", callback_data="refresh_status")
            markup.add(btn_sync, btn_refresh)
            bot.reply_to(message, response, parse_mode="Markdown", reply_markup=markup)
        except Exception as e:
            log.error(f"Error handling /status command: {e}")
            bot.reply_to(message, "❌ Gagal memproses /status. Terjadi gangguan pada koneksi API atau rate limit tercapai. Silakan coba beberapa saat lagi.", parse_mode="Markdown")

    @bot.callback_query_handler(func=lambda call: call.data == "sync_tpsl")
    def callback_sync_tpsl(call):
        try:
            bot.answer_callback_query(call.id, "Sedang sinkronisasi TP/SL...")
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="⏳ *Memproses Auto-Sync TP/SL ke BingX...*", parse_mode="Markdown")
            import order_manager
            hasil = order_manager.sync_missing_tpsl()
            bot.send_message(call.message.chat.id, f"✅ *HASIL SYNC TP/SL:*\n\n{hasil}", parse_mode="Markdown")
        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ Gagal Sync TP/SL: {e}")

    @bot.callback_query_handler(func=lambda call: call.data == "refresh_status")
    def callback_refresh_status(call):
        try:
            bot.answer_callback_query(call.id, "Refreshing...")
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass

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
                total_equity = 1000.0 + closed_pnl
                
                open_trades = [t for t in trades if t.get("status") == "OPEN_PAPER"]
                locked_margin = sum([(float(t["qty"]) * float(t["entry"])) / 15 for t in open_trades])
                available_margin = total_equity - locked_margin
                
                response = (
                    f"🏦 *SALDO SIMULASI (PAPER)*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"💰 *Total Equity:* `${total_equity:.2f} USDT`\n"
                    f"💵 *Available Margin:* `${available_margin:.2f} USDT` (Bisa untuk entry baru)\n"
                    f"🔒 *Locked Margin:* `${locked_margin:.2f} USDT` (Sedang di posisi aktif)\n"
                    f"📝 *Catatan:* Berjalan di akun virtual/demo lokal.\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"{get_freshness_timestamp()}"
                )
            else:
                balance_res = bx._request("GET", "/openApi/swap/v2/user/balance")
                if balance_res.get("code") == 0:
                    bal_data = balance_res.get("data", {}).get("balance", {})
                    equity = float(bal_data.get("equity", 0.0))
                    available = float(bal_data.get("availableMargin", 0.0))
                    locked = equity - available
                else:
                    equity = bx.get_balance()
                    available = equity
                    locked = 0.0
                    
                response = (
                    f"🏦 *SALDO LIVE BINGX*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"💰 *Total Equity:* `${equity:.2f} USDT`\n"
                    f"💵 *Available Margin:* `${available:.2f} USDT` (Bisa untuk entry baru)\n"
                    f"🔒 *Locked Margin:* `${locked:.2f} USDT` (Sedang di posisi aktif)\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"{get_freshness_timestamp()}"
                )
            bot.reply_to(message, response, parse_mode="Markdown")
        except Exception as e:
            log.error(f"Error handling /balance command: {e}")
            bot.reply_to(message, "❌ Gagal memproses /balance. Terjadi gangguan pada koneksi API atau rate limit tercapai. Silakan coba beberapa saat lagi.", parse_mode="Markdown")

    @bot.message_handler(commands=['pnl'])
    def handle_pnl(message):
        if not is_authorized(message):
            return
        try:
            import state_manager
            import order_manager
            import bingx_client as bx
            import time
            import datetime
            
            mode = state_manager.get_trading_mode()
            paper_mode = mode["paper_mode"]
            
            if paper_mode:
                trades = order_manager.load_paper_trades()
                closed_trades = [t for t in trades if t.get("status", "").startswith("CLOSED")]
                open_trades = [t for t in trades if t.get("status") == "OPEN_PAPER"]
                
                unrealized_pnl = 0.0
                for t in open_trades:
                    symbol = t["symbol"]
                    side = t["side"]
                    entry = float(t["entry"])
                    qty = float(t["qty"])
                    try:
                        curr_price = bx.get_current_price(symbol)
                    except:
                        curr_price = entry
                    if side == "LONG":
                        unrealized_pnl += (curr_price - entry) * qty
                    else:
                        unrealized_pnl += (entry - curr_price) * qty
                
                now = datetime.datetime.now()
                pnl_24h = 0.0
                pnl_3d = 0.0
                pnl_7d = 0.0
                for t in closed_trades:
                    try:
                        c_time = datetime.datetime.strptime(t.get("close_time", ""), "%Y-%m-%d %H:%M:%S")
                        diff = now - c_time
                        val = float(t.get("pnl_usdt", 0.0))
                        if diff.total_seconds() < 24 * 3600:
                            pnl_24h += val
                        if diff.total_seconds() < 3 * 24 * 3600:
                            pnl_3d += val
                        if diff.total_seconds() < 7 * 24 * 3600:
                            pnl_7d += val
                    except:
                        continue
                
                total_pnl = pnl_7d + unrealized_pnl
                
                pnl_float_sign = "+" if unrealized_pnl >= 0 else ""
                pnl_24h_sign = "+" if pnl_24h >= 0 else ""
                pnl_3d_sign = "+" if pnl_3d >= 0 else ""
                pnl_7d_sign = "+" if pnl_7d >= 0 else ""
                total_pnl_sign = "+" if total_pnl >= 0 else ""
                
                response = (
                    f"📊 *LAPORAN PnL SIMULASI (PAPER)*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🟢 *PnL Mengambang (Floating):* `{pnl_float_sign}{unrealized_pnl:.2f} USDT`\n"
                    f"💵 *PnL Terealisasi (Realized):*\n"
                    f"  ├─ Hari Ini (24j): `{pnl_24h_sign}{pnl_24h:.2f} USDT`\n"
                    f"  ├─ 3 Hari Terakhir: `{pnl_3d_sign}{pnl_3d:.2f} USDT`\n"
                    f"  └─ 7 Hari Terakhir: `{pnl_7d_sign}{pnl_7d:.2f} USDT`\n"
                    f"💰 *Estimasi Total PnL:* `{total_pnl_sign}{total_pnl:.2f} USDT`\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"{get_freshness_timestamp()}"
                )
            else:
                positions = bx.get_open_positions()
                unrealized_pnl = sum([float(p.get("unrealizedProfit", 0)) for p in positions])
                
                income = bx.get_income_history(days=7)
                
                now_ms = time.time() * 1000
                ms_in_day = 24 * 3600 * 1000
                
                pnl_24h = sum([float(inc.get("income", 0)) for inc in income if inc.get("incomeType") in ["REALIZED_PNL", "COMMISSION"] and (now_ms - int(inc.get("time", 0)) < ms_in_day)])
                pnl_3d = sum([float(inc.get("income", 0)) for inc in income if inc.get("incomeType") in ["REALIZED_PNL", "COMMISSION"] and (now_ms - int(inc.get("time", 0)) < 3 * ms_in_day)])
                pnl_7d = sum([float(inc.get("income", 0)) for inc in income if inc.get("incomeType") in ["REALIZED_PNL", "COMMISSION"]])
                
                total_pnl = pnl_7d + unrealized_pnl
                
                pnl_float_sign = "+" if unrealized_pnl >= 0 else ""
                pnl_24h_sign = "+" if pnl_24h >= 0 else ""
                pnl_3d_sign = "+" if pnl_3d >= 0 else ""
                pnl_7d_sign = "+" if pnl_7d >= 0 else ""
                total_pnl_sign = "+" if total_pnl >= 0 else ""
                
                response = (
                    f"📊 *LAPORAN PnL LIVE BINGX*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🟢 *PnL Mengambang (Floating):* `{pnl_float_sign}{unrealized_pnl:.2f} USDT`\n"
                    f"💵 *PnL Terealisasi (Realized):*\n"
                    f"  ├─ Hari Ini (24j): `{pnl_24h_sign}{pnl_24h:.2f} USDT`\n"
                    f"  ├─ 3 Hari Terakhir: `{pnl_3d_sign}{pnl_3d:.2f} USDT`\n"
                    f"  └─ 7 Hari Terakhir: `{pnl_7d_sign}{pnl_7d:.2f} USDT`\n"
                    f"💰 *Estimasi Total PnL:* `{total_pnl_sign}{total_pnl:.2f} USDT`\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"{get_freshness_timestamp()}"
                )
            bot.reply_to(message, response, parse_mode="Markdown")
        except Exception as e:
            log.error(f"Error handling /pnl command: {e}")
            bot.reply_to(message, "❌ Gagal memproses /pnl. Terjadi gangguan pada koneksi API atau rate limit tercapai. Silakan coba beberapa saat lagi.", parse_mode="Markdown")

    @bot.message_handler(commands=['settings'])
    def handle_settings(message):
        if not is_authorized(message):
            return
        try:
            import state_manager
            mode = state_manager.get_trading_mode()
            paper_mode = mode["paper_mode"]
            
            auto_entry = os.getenv("AUTO_ENTRY", "true")
            margin_mode = os.getenv("MARGIN_MODE", "ISOLATED")
            leverage = os.getenv("LEVERAGE", "5")
            risk_pct = os.getenv("RISK_PER_TRADE_PERCENT", "2.0")
            webhook_url = os.getenv("WEBHOOK_URL", "-")
            
            api_key = os.getenv("BINGX_API_KEY", "")
            masked_key = f"{api_key[:6]}...{api_key[-6:]}" if len(api_key) > 12 else "Tidak Dikonfigurasi"
            
            response = (
                f"⚙️ *PENGATURAN BOT TRADING*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"⚙️ *Mode Default:* `{'PAPER / SIMULASI' if paper_mode else 'LIVE / UANG ASLI'}`\n"
                f"🪙 *API Key BingX:* `{masked_key}`\n"
                f"🛡️ *Leverage:* `{leverage}x`\n"
                f"🎯 *Margin Mode:* `{margin_mode}`\n"
                f"⚠️ *Risk per Trade:* `{risk_pct}%`\n"
                f"🤖 *Auto Entry:* `{auto_entry}`\n"
                f"🌐 *Webhook URL:* `{webhook_url}`\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"{get_freshness_timestamp()}"
            )
            bot.reply_to(message, response, parse_mode="Markdown")
        except Exception as e:
            log.error(f"Error handling /settings command: {e}")
            bot.reply_to(message, "❌ Gagal memproses /settings. Terjadi gangguan pada koneksi API atau rate limit tercapai. Silakan coba beberapa saat lagi.", parse_mode="Markdown")

    @bot.message_handler(commands=['aistats'])
    def handle_aistats(message):
        if not is_authorized(message):
            return
        try:
            from ai_trading import db_logger
            stats = db_logger.get_summary_stats()
            recent_logs = db_logger.get_recent_logs(limit=5)
            
            response_lines = [
                "🧠 *STATISTIK VALIDASI AI FILTER*",
                "━━━━━━━━━━━━━━━━━━━━━",
                f"📊 *Total Sinyal Masuk:* `{stats['total']}`",
                f"🟢 *Disetujui (Approved):* `{stats['approved']}`",
                f"🔴 *Ditolak (Rejected):* `{stats['rejected']}`",
                f"📈 *Rasio Persetujuan:* `{stats['approval_rate']}%`",
                "━━━━━━━━━━━━━━━━━━━━━",
                "🕒 *5 RIWAYAT KEPUTUSAN TERBARU:*"
            ]
            
            if not recent_logs:
                response_lines.append(" (Belum ada catatan aktivitas validasi AI)")
            else:
                for idx, log_entry in enumerate(recent_logs):
                    timestamp_str = log_entry["timestamp"]
                    try:
                        time_part = timestamp_str.split(" ")[1]
                    except:
                        time_part = timestamp_str
                        
                    emoji = "🟢" if log_entry["approved"] == 1 else "🔴"
                    status_emoji = "✅" if log_entry["status"] in ["success", "success_paper"] else ("⚠️" if log_entry["status"] == "rejected_by_ai" else "⚪")
                    
                    response_lines.append(
                        f"{idx+1}. {emoji} *{log_entry['pair']}* | {log_entry['action']}\n"
                        f"  ├─ *Waktu:* `{time_part}` | *Status:* `{log_entry['status']} {status_emoji}`\n"
                        f"  └─ *Alasan:* `{log_entry['reason']}`"
                    )
            
            response_lines.append("━━━━━━━━━━━━━━━━━━━━━")
            response_lines.append(get_freshness_timestamp())
            
            response = "\n".join(response_lines)
            bot.reply_to(message, response, parse_mode="Markdown")
        except Exception as e:
            log.error(f"Error handling /aistats command: {e}")
            bot.reply_to(message, "❌ Gagal memproses /aistats. Silakan coba beberapa saat lagi.", parse_mode="Markdown")

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
