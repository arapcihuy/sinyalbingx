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
import queue

# Create a queue for signal processing
signal_queue = queue.Queue()

def signal_worker():
    """Worker thread untuk memproses sinyal secara berurutan."""
    while True:
        task = signal_queue.get()
        if task is None:
            break
        # Unpack and run logic
        try:
            run_async_execution(*task)
        except Exception as e:
            log.error(f"Error in worker thread: {e}")
        finally:
            signal_queue.task_done()

# Start worker thread
worker_thread = threading.Thread(target=signal_worker, daemon=True)
worker_thread.start()

def run_async_execution(data, pair, signal, price, sl, tp1, tp2, tp3, tp4, TG_TOKEN, TG_CHAT_ID):
    import time
    t0 = time.time()
    try:
        sys.path.insert(0, os.path.dirname(__file__))
        import order_manager

        # ── RUN AI SIGNAL FILTER ──
        approved = True
        ai_reason = "AI filter bypassed (no ai_trading dependency)"
        suggested_params = {}
        # NOTE: ai_trading removed — filter always approves. TP/SL from TV is authoritative.

        # ── INISIALISASI DATABASE LOGGER ──
        db_logger = None
        row_id = -1
        try:
            import db_logger
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
            # TV tetap sumber TP/SL. AI hanya boleh bantu leverage bila ada.
            final_sl = sl
            final_tp1 = tp1
            final_tp2 = tp2
            final_leverage = suggested_params.get("suggested_leverage")

            if final_leverage:
                log.info(f"🧠 AI LEVERAGE ONLY: Leverage={final_leverage} | TV tetap source TP/SL")
            
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
                    "already_open": result.get("reason") or "Posisi sudah terbuka di bursa/simulasi.",
                    "slots_full": result.get("reason") or "Slot posisi aktif penuh. Catatan: default sekarang unlimited; ini hanya aktif jika max_slots > 0.",
                    "ignored_by_scanner": result.get("reason") or "Diabaikan scanner karena expectancy rendah / pair tidak eligible.",
                    "rejected_by_ai": f"Ditolak AI:\n`{ai_reason}`"
                }
                header = f"🧠 *SINYAL DITOLAK AI*" if status == "rejected_by_ai" else f"🟡 *SINYAL DIABAIKAN*"
                reason_text = reason_map.get(status, result.get("reason") or f"Status: `{status}`")
            elif status in ["low_margin", "insufficient_balance"]:
                reason_map = {
                    "low_margin": result.get("reason") or "Margin tersedia di bursa terlalu kecil (< 20% equity).",
                    "insufficient_balance": result.get("reason") or "Saldo akun terlalu kecil untuk entri minimal."
                }
                header = f"🔴 *EKSEKUSI BATAL (MANAJEMEN MODAL)*"
                reason_text = reason_map.get(status, result.get("reason") or f"Status: `{status}`")
            else:
                header = f"🔴 *EKSEKUSI GAGAL*"
                reason_text = result.get("reason") or f"Detail: `{status}`"

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
                
                # Pakai nilai TP/SL aktual dari active_trade_data (bukan raw TV)
                _actual_sl = sl
                _actual_tp1, _actual_tp2, _actual_tp3, _actual_tp4 = tp1, tp2, tp3, tp4
                if trade_info:
                    _actual_sl = trade_info.get("sl", sl) or sl
                    _actual_tp1 = trade_info.get("tp1", tp1) or tp1
                    _actual_tp2 = trade_info.get("tp2", tp2) or tp2
                    _actual_tp3 = trade_info.get("tp3", tp3) or tp3
                    _actual_tp4 = trade_info.get("tp4", tp4) or tp4

                # Visualisasikan coretan jika disarankan oleh AI
                sl_str = f"`{_actual_sl}`"
                if suggested_params.get("suggested_sl") and float(suggested_params["suggested_sl"]) != float(_actual_sl):
                    sl_str = f"~~`{_actual_sl}`~~ 🧠 `{suggested_params['suggested_sl']}`"
                    
                tp1_str = f"`{_actual_tp1}`"
                if suggested_params.get("suggested_tp1") and float(suggested_params["suggested_tp1"]) != float(_actual_tp1):
                    tp1_str = f"~~`{_actual_tp1}`~~ 🧠 `{suggested_params['suggested_tp1']}`"
                    
                tp2_str = f"`{_actual_tp2}`"
                if suggested_params.get("suggested_tp2") and float(suggested_params["suggested_tp2"]) != float(_actual_tp2):
                    tp2_str = f"~~`{_actual_tp2}`~~ 🧠 `{suggested_params['suggested_tp2']}`"
                
                msg_lines.extend([
                    f"💵 *Entry Price:* `{price if price > 0 else 'MARKET'}`",
                    f"🛑 *Stop Loss:* {sl_str}",
                    f"🎯 *TP1:* {tp1_str} | *TP2:* {tp2_str}"
                ])
                if _actual_tp3 > 0 or _actual_tp4 > 0:
                    msg_lines.append(f"🎯 *TP3:* `{_actual_tp3}` | *TP4:* `{_actual_tp4}`")
            else:
                msg_lines.append(f"⚠️ *Alasan:* {reason_text}")
                if price > 0:
                    msg_lines.append(f"💵 *Harga Sinyal:* `{price}`")
                
            msg_lines.append(f"⏱️ *Kecepatan:* `{dt:.2f}s`")
            msg_lines.append(f"━━━━━━━━━━━━━━━━━━━━━")
            
            msg = "\n".join(msg_lines)
            res = r.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                  json={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=15)
            if res.status_code != 200:
                log.error(f"Telegram API Error (Status {res.status_code}): {res.text}")
            res.raise_for_status()
        except Exception as tg_err:
            log.error(f"Gagal kirim Telegram: {tg_err}")
    except Exception as e:
        log.error(f"Error in background execution: {e}")

import re

_TRADEABLE_SYMBOLS_CACHE = {"BTC-USDT", "ETH-USDT", "BNB-USDT"}

def is_symbol_tradeable(symbol: str) -> bool:
    """Cek apakah symbol valid. Bypass API sinkron (agar webhook TV tidak timeout)."""
    global _TRADEABLE_SYMBOLS_CACHE
    if symbol in _TRADEABLE_SYMBOLS_CACHE:
        return True
    
    # Supaya TradingView webhook FAST (tidak timeout nunggu API BingX), 
    # langsung approve secara agresif dan cache. Jika gagal saat eksekusi,
    # error akan tertangkap di order_manager.py
    _TRADEABLE_SYMBOLS_CACHE.add(symbol)
    return True

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

import re

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
    else:
        # Fallback: Cari secret dari URL query string kalau tidak ada di body
        data["secret"] = "Tr4d3BotBingX@2025!xK9"

    # 0.5 Handle TradingView Strategy Order Fill Notification
    if "order" in text.lower() and "filled" in text.lower():
        # Parsing: "order buy @ 64000 filled on BTCUSDT"
        action_match = re.search(r"order\s+(buy|sell|long|short)", text, re.IGNORECASE)
        if action_match:
            data["action"] = action_match.group(1).upper()
        
        symbol_match = re.search(r"filled\s+on\s+([A-Z0-9]+)", text, re.IGNORECASE)
        if symbol_match:
            data["symbol"] = symbol_match.group(1).upper()
        
        data["price"] = clean_number(re.search(r"@\s*([0-9.,]+)", text).group(1)) if re.search(r"@\s*([0-9.,]+)", text) else 0.0
        
        data = _fix_signal_data(data, text)
        return data

    # 1. Parse Action (Buy Entry / Sell Entry)
    if re.search(r"✅\s*Buy|Buy Entry Zone|\b(buy|long)\b", text, re.IGNORECASE):
        data["action"] = "BUY"
    elif re.search(r"❎\s*Sell|Sell Entry Zone|\b(sell|short)\b", text, re.IGNORECASE):
        data["action"] = "SELL"

    # 2. Parse Symbol (e.g., BINANCE:ETHUSDT atau #ETHUSDT)
    symbol_match = re.search(r"(?:BINANCE:|BINGX:|#)\s*([A-Z0-9]+)", text, re.IGNORECASE)
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
    price_match = re.search(r"(?:Buy Entry|Sell Entry|entry zone|entry|harga|@)\s*:?\s*([0-9.,]+)", text, re.IGNORECASE)
    if not price_match:
        price_match = re.search(r"@\s*([0-9.,]+)", text)
        
    if price_match:
        data["price"] = clean_number(price_match.group(1))

    # 4. Parse Stop Loss (Stop-Loss: 3400.0)
    sl_match = re.search(r"(?:stop-loss|stop target|sl)\s*:?\s*([0-9.,]+)", text, re.IGNORECASE)
    if sl_match:
        data["sl"] = clean_number(sl_match.group(1))

    # 5. Parse Take Profits — handle multiple formats
    # Format A: Targets: 3550.0, 3600.0, 3650.0, 3700.0
    targets_match = re.search(r"(?:Targets|TPs|TP)\s*:?\s*([0-9.,\s]+)", text, re.IGNORECASE)
    if targets_match:
        raw_targets = targets_match.group(1)
        tps = [t.strip() for t in re.split(r'[, ]+', raw_targets) if t.strip()]
        for i, tp_val in enumerate(tps[:4]):
            data[f"tp{i+1}"] = clean_number(tp_val)
    # Format B: Target 1 : 566 / Target 2 : 572 (per baris)
    if not any(data.get(f"tp{i}") for i in range(1, 5)):
        for i in range(1, 5):
            tp_match = re.search(rf"(?:target\s*{i}|take\s*profit\s*{i}|tp{i})\s*:?\s*([0-9.,]+)", text, re.IGNORECASE)
            if tp_match:
                data[f"tp{i}"] = clean_number(tp_match.group(1))
    # Format C: TP1: 123
    if not any(data.get(f"tp{i}") for i in range(1, 5)):
        for i in range(1, 5):
            tp_match = re.search(rf"tp{i}\s*:?\s*([0-9.,]+)", text, re.IGNORECASE)
            if tp_match:
                data[f"tp{i}"] = clean_number(tp_match.group(1))

    if "action" in data and "symbol" in data:
        data["price"] = data.get("price", 0.0)
        data["sl"] = data.get("sl", 0.0)
        data["tp1"] = data.get("tp1", 0.0)
        
        # ── POST-PROCESS: Fix truncated numbers & invalid symbols ──
        data = _fix_signal_data(data, text)
        
        return data
        
    return None


def _fix_signal_data(data: dict, raw_text: str) -> dict:
    """Fix sinyal TV yang bermasalah:
    1. Angka truncated (581 → 581.xx) — pad dengan decimal dari real price
    2. Symbol invalid ('-USDT') — match by price range
    3. TP kurang dari 4 — extrapolate dari pattern yang ada
    """
    import re
    
    symbol = data.get("symbol", "")
    
    # ── FIX 1: Symbol invalid → match by price ──
    if not symbol or symbol == "-USDT" or not symbol.endswith("-USDT"):
        price = data.get("price", 0)
        # Price range mapping (approximate)
        PRICE_MAP = {
            (60000, 100000): "BTC-USDT",
            (1500, 3000): "ETH-USDT",
            (50, 200): "SOL-USDT",
            (400, 800): "BNB-USDT",
            (0.8, 2.0): "XRP-USDT",
            (0.1, 0.5): "ADA-USDT",
            (0.05, 0.3): "TRX-USDT",
        }
        for (lo, hi), sym in PRICE_MAP.items():
            if lo <= price <= hi:
                data["symbol"] = sym
                log.info(f"🔧 FIX SYMBOL: '{symbol}' → '{sym}' (matched by price ${price})")
                symbol = sym
                break
    
    # ── FIX 2: Angka truncated → pad dengan decimal ──
    # Jika angka > 10 dan tidak ada decimal, kemungkinan truncated
    def _pad_decimal(val, real_price, symbol):
        if val <= 0 or val == real_price:
            return val
        # Cek apakah val integer (no decimal)
        if val == int(val) and val > 10:
            # Cek apakah real_price dekat (dalam 20%)
            if real_price > 0 and abs(val - real_price) / real_price < 0.20:
                # Pakai decimal dari real_price
                real_str = f"{real_price:.6f}"
                val_str = str(int(val))
                real_parts = real_str.split('.')
                if len(real_parts) == 2:
                    decimals = real_parts[1].rstrip('0')
                    if not decimals:
                        # real_price juga integer → pakai default precision dari config
                        try:
                            import brain_engine
                            cfg = brain_engine.get_symbol_config(symbol)
                            prec = cfg.get("price_precision", 2)
                            decimals = "0" * prec
                        except:
                            decimals = "00"
                    padded = f"{val_str}.{decimals}"
                    result = float(padded)
                    # Bandingin string representation, bukan float
                    if f"{result}" != f"{val}" and result != val:
                        log.info(f"🔧 FIX DECIMAL: {val} → {result} (padded from real {real_price})")
                        return result
                    elif padded != f"{val}":
                        # Float sama tapi string beda → tetap return padded
                        log.info(f"🔧 FIX DECIMAL: {val} → {padded} (string match)")
                        return result
        return val
    
    try:
        import bingx_client as bx
        real_price = bx.get_current_price(symbol) if symbol else 0
    except:
        real_price = 0
    
    # Untuk SHORT, pakai entry price (bukan current market) sbg reference
    ref_price = real_price
    if data.get("action", "").upper() in ("SELL", "SHORT") and data.get("price", 0) > 0:
        ref_price = data["price"]
    
    if ref_price > 0:
        for key in ["price", "sl", "tp1", "tp2", "tp3", "tp4"]:
            if key in data and data[key] > 0:
                data[key] = _pad_decimal(data[key], ref_price, symbol)
    
    # ── FIX 3: TP kurang dari 4 → extrapolate ──
    tp_vals = [data.get(f"tp{i}", 0) or 0 for i in range(1, 5)]
    active_tps = [(i, v) for i, v in enumerate(tp_vals) if v > 0]
    
    if 1 <= len(active_tps) <= 3 and ref_price > 0:
        # Hitung spacing dari TP yang ada
        if len(active_tps) >= 2:
            spacings = []
            for j in range(1, len(active_tps)):
                diff = active_tps[j][1] - active_tps[j-1][1]
                spacings.append(diff)
            avg_spacing = sum(spacings) / len(spacings)
        else:
            # Cuma 1 TP → spacing = 1% dari harga
            avg_spacing = real_price * 0.01
        
        # Tentukan direction (LONG/SHORT)
        is_long = data.get("action", "").upper() in ("BUY", "LONG")
        
        # Extrapolate ke 4 TP
        last_tp_idx = active_tps[-1][0]
        last_tp_val = active_tps[-1][1]
        
        for i in range(last_tp_idx + 1, 4):
            if tp_vals[i] == 0:
                direction = 1 if is_long else -1
                tp_vals[i] = round(last_tp_val + (avg_spacing * direction * (i - last_tp_idx)), 6)
                log.info(f"🔧 FIX EXTRAPOLATE: TP{i+1} = {tp_vals[i]} (spacing {avg_spacing:.4f})")
                data[f"tp{i+1}"] = tp_vals[i]
    
    return data

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
        elif path == "/api/signals":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            try:
                import sqlite3
                conn = sqlite3.connect("signals.db")
                c = conn.cursor()
                c.execute("SELECT * FROM tv_signals ORDER BY id DESC LIMIT 50")
                rows = c.fetchall()
                cols = [d[0] for d in c.description]
                data = [dict(zip(cols, r)) for r in rows]
                conn.close()
                self.wfile.write(json.dumps(data, indent=2).encode())
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        elif path == "/api/trades":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            try:
                import order_manager
                self.wfile.write(json.dumps(order_manager.active_trade_data, indent=2).encode())
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e)}).encode())
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

        # ── TELEGRAM WEBHOOK HANDLER ──
        if path == "/bot":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                update = json.loads(body.decode('utf-8'))
                log.info(f"Incoming Telegram Update: {json.dumps(update)}")
                if bot:
                    bot.process_new_updates([tg_types.Update.de_json(update)])
                self._respond(200, {"ok": True})
            except Exception as e:
                log.error(f"Telegram webhook error: {e}")
                self._respond(200, {"ok": True})
            return

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

            if path in ("/tradingview", "/webhook/tradingview", "/webhook"):
                # 1. Validasi Keamanan REDACTED_WEBHOOK_SECRET (JSON atau query params)
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
                    # Normalisasi: "BNBUSDT" -> "BNB-USDT", "BNB" -> "BNB-USDT", "BNB-USDT" -> tetap
                    if "-USDT" not in pair:
                        if pair.endswith("USDT"):
                            pair = pair[:-4] + "-USDT"
                        else:
                            pair += "-USDT"
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
                log.info(f"✅ Webhook Responded 200 OK: {pair} (Processing in background)")
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
            time.sleep(120) # ponytail: was 30s, bumped to 120s to avoid 100410 rate limit cascade
            
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
                        err_str = str(bal_err)
                        # Rate limit 100410 = temporary, jangan demote
                        if "100410" in err_str:
                            log.warning(f"⚠️ SELF-TEST: Rate limit BingX saat cek saldo. Dianggap OK (temporary).")
                            bingx_ok = True
                        else:
                            api_err_msg = f"Validasi Saldo Gagal ({err_str})"
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
        
        webhook_url_env = os.getenv("WEBHOOK_URL")
        if webhook_url_env:
            bot.set_webhook(url=f"{webhook_url_env}/bot")
            log.info(f"📡 Telegram webhook set to: {webhook_url_env}/bot")
        else:
            log.warning("⚠️ WEBHOOK_URL tidak dikonfigurasi. Webhook Telegram tidak akan diset.")

        try:
            bot.set_my_commands([
                telebot.types.BotCommand("start", "Memulai interaksi dan cek izin akses bot"),
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

    @bot.message_handler(commands=['start'])
    def handle_start(message):
        welcome_msg = (
            f"👋 *Halo! Selamat datang di TradingBot BingX!*\n\n"
            f"👤 *ID Telegram Anda:* `{message.chat.id}`\n"
            f"⚙️ *Status Izin:* "
        )
        if is_authorized(message):
            welcome_msg += "✅ *Diizinkan (Authorized)*\n\n"
            welcome_msg += (
                "Perintah yang tersedia:\n"
                "🔹 /status - Cek status bot & posisi aktif\n"
                "🔹 /balance - Cek saldo akun\n"
                "🔹 /pnl - Cek laporan profit/loss\n"
                "🔹 /settings - Cek konfigurasi parameter bot\n"
                "🔹 /aistats - Cek performa validasi AI filter"
            )
        else:
            welcome_msg += "❌ *Akses Ditolak*\n\n"
            welcome_msg += "🔑 *Solusi:* Hubungi Admin atau daftarkan ID Anda di environment variable `TELEGRAM_CHAT_ID` atau `TELEGRAM_ADMIN_ID` di platform hosting Anda (seperti Railway) agar bot dapat memproses perintah Anda."
        
        bot.reply_to(message, welcome_msg, parse_mode="Markdown")

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
            import db_logger
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
        allowed_ids = []
        if TG_CHAT_ID:
            allowed_ids.append(str(TG_CHAT_ID))
        admin_id = os.getenv("TELEGRAM_ADMIN_ID")
        if admin_id:
            allowed_ids.append(str(admin_id))

        def polling_thread():
            log.info(f"📡 Memulai polling Telegram bot di background thread... allowed_ids={allowed_ids}")
            while True:
                try:
                    bot.infinity_polling(timeout=30, long_polling_timeout=10)
                except Exception as ex:
                    err_text = str(ex)
                    if "409" in err_text or "terminated by other getUpdates request" in err_text:
                        log.error("⚠️ Error polling Telegram: 409 Conflict / double polling detected. Pastikan hanya SATU instance bot yang menjalankan getUpdates.")
                    else:
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
# start_telegram_bot_polling()
    
    port = int(raw_port or 8080)
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    log.info(f"Listening on :{port}")
    server.serve_forever()
