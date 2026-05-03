import os
import json
import logging
from datetime import datetime
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import order_manager
import uuid
import threading
import time

load_dotenv()

# ── Setup logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
PORT = int(os.getenv("PORT", 5000))
HOST = os.getenv("HOST", "0.0.0.0")

# ── Telegram Config ──
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
bot = telebot.TeleBot(TG_TOKEN)

# Penyimpanan sementara untuk sinyal yang menunggu konfirmasi
pending_signals = {}


# ─────────────────────────────────────────────
#  HEALTH CHECK
# ─────────────────────────────────────────────

@app.route("/", methods=["GET"])
def health():
    return jsonify({
        "status": "running",
        "time": datetime.now().isoformat(),
        "message": "BingX Webhook Bot aktif ✅"
    })


# ─────────────────────────────────────────────
#  WEBHOOK ENDPOINT
# ─────────────────────────────────────────────

@app.route("/webhook", methods=["POST"])
def webhook():
    logger.info("=" * 50)
    logger.info("📡 Sinyal masuk dari TradingView")

    # ── Parse payload ──
    try:
        if request.is_json:
            data = request.get_json()
        else:
            # TradingView kadang kirim sebagai text biasa
            raw = request.data.decode("utf-8")
            data = json.loads(raw)
    except Exception as e:
        logger.error(f"Gagal parse payload: {e}")
        return jsonify({"error": "Payload tidak valid"}), 400

    logger.info(f"Payload diterima: {json.dumps(data, indent=2)}")

    # ── Verifikasi secret ──
    if WEBHOOK_SECRET:
        received_secret = data.get("secret", "")
        if received_secret != WEBHOOK_SECRET:
            logger.warning("❌ Secret tidak cocok! Request ditolak.")
            return jsonify({"error": "Unauthorized"}), 401

    # ── Validasi field wajib ──
    action = data.get("action", "").upper()
    if action not in ["BUY", "SELL", "CLOSE"]:
        logger.warning(f"Action tidak dikenal: {action}")
        return jsonify({"error": f"Action tidak valid: {action}"}), 400

    # ── Proses CLOSE ──
    if action == "CLOSE":
        try:
            symbol = data.get("symbol", os.getenv("SYMBOL", "BTC-USDT"))
            result = _close_position(symbol, data)
            return jsonify({"status": "success", "action": "CLOSE", "result": result}), 200
        except Exception as e:
            logger.error(f"Gagal close: {e}")
            return jsonify({"error": str(e)}), 500

    # ── Cek apakah sudah ada posisi aktif (Auto Sync TP/SL) ──
    try:
        import bingx_client as bx
        symbol_to_check = data.get("symbol", os.getenv("SYMBOL", "BTC-USDT"))
        positions = bx.get_open_positions(symbol_to_check)
        
        logger.info(f"Mengecek posisi untuk {symbol_to_check}. Ditemukan: {len(positions)} data.")
        
        active_pos = None
        for p in positions:
            qty = abs(float(p.get("positionAmt", 0)))
            if qty > 0:
                active_pos = p
                break
        
        if active_pos:
            logger.info(f"✅ Posisi aktif ditemukan: {active_pos.get('positionSide')} {active_pos.get('positionAmt')}")
            bot.send_message(TG_CHAT_ID, f"🔄 *Posisi aktif terdeteksi untuk {symbol_to_check}*\nSinkronisasi TP/SL otomatis dijalankan...", parse_mode="Markdown")
            result = order_manager.apply_tpsl_to_existing(data)
            
            bot.send_message(
                TG_CHAT_ID,
                f"✅ *TP/SL DISINKRONKAN!*\n\n"
                f"Symbol: `{result['symbol']}`\n"
                f"Qty: `{result['total_quantity']}`\n"
                f"TP1: `{result['tp_configs'][0][0]}`\n"
                f"SL: `{result['sl_price']}`",
                parse_mode="Markdown"
            )
            return jsonify({"status": "success", "message": "Auto-sync TP/SL berhasil"}), 200
        else:
            logger.info("ℹ️ Tidak ada posisi aktif. Lanjut ke mode konfirmasi entry baru.")
    except Exception as e:
        logger.error(f"❌ Gagal auto-sync: {e}", exc_info=True)

    # ── Jika belum ada posisi, Minta Konfirmasi Telegram untuk Entry Baru ──
    try:
        signal_id = str(uuid.uuid4())[:8]
        pending_signals[signal_id] = data
        
        # Buat Tombol
        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("10x", callback_data=f"exec:10:{signal_id}"),
            InlineKeyboardButton("20x", callback_data=f"exec:20:{signal_id}"),
            InlineKeyboardButton("30x", callback_data=f"exec:30:{signal_id}")
        )
        markup.row(InlineKeyboardButton("🛠️ Hanya Pasang TP/SL (No Entry)", callback_data=f"tpsl_only:{signal_id}"))
        markup.row(InlineKeyboardButton("❌ Batal", callback_data=f"cancel:{signal_id}"))

        msg = (
            f"🔔 *SINYAL MASUK!*\n\n"
            f"Action: `{action}`\n"
            f"Symbol: `{data.get('symbol', 'BTC-USDT')}`\n"
            f"Price: `{data.get('price', 'MARKET')}`\n\n"
            f"Pilih Leverage untuk eksekusi:"
        )
        
        bot.send_message(TG_CHAT_ID, msg, parse_mode="Markdown", reply_markup=markup)
        logger.info(f"Sinyal {signal_id} dikirim ke Telegram untuk konfirmasi.")
        
        return jsonify({"status": "pending", "message": "Menunggu konfirmasi Telegram", "id": signal_id}), 200

    except Exception as e:
        logger.error(f"❌ Error saat kirim konfirmasi: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────
#  TELEGRAM WEBHOOK & CALLBACK
# ─────────────────────────────────────────────

@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    """Endpoint untuk menerima update dari Telegram."""
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return ''
    else:
        return jsonify({"error": "Invalid content type"}), 403


@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    """Handle klik tombol di Telegram."""
    data_parts = call.data.split(":")
    cmd = data_parts[0]
    
    if cmd == "exec":
        leverage = data_parts[1]
        sid = data_parts[2]
        
        if sid not in pending_signals:
            bot.answer_callback_query(call.id, "Sinyal kadaluarsa atau tidak ditemukan!")
            return

        signal = pending_signals.pop(sid)
        signal["leverage"] = int(leverage) # Pakai leverage pilihan user

        bot.edit_message_text(
            f"⚙️ Memproses `{signal['action']}` `{signal['symbol']}` dengan leverage `{leverage}x`...",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id
        )

        try:
            result = order_manager.execute_signal(signal)
            bot.edit_message_text(
                f"✅ *ORDER BERHASIL!*\n\n"
                f"Action: `{result['action']}`\n"
                f"Symbol: `{result['symbol']}`\n"
                f"Leverage: `{leverage}x`\n"
                f"Qty: `{result['quantity']}`\n"
                f"Entry: `{result['entry_price']}`\n"
                f"TP: `{result['tp_price']}`\n"
                f"SL: `{result['sl_price']}`",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode="Markdown"
            )
        except Exception as e:
            bot.edit_message_text(
                f"❌ *GAGAL EKSEKUSI!*\n\nError: `{str(e)}`",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode="Markdown"
            )
            
    elif cmd == "tpsl_only":
        sid = data_parts[1]
        if sid not in pending_signals:
            bot.answer_callback_query(call.id, "Sinyal kadaluarsa!")
            return
        
        signal = pending_signals.pop(sid)
        bot.edit_message_text(
            f"⚙️ Menghitung & Memasang TP/SL untuk posisi `{signal['symbol']}` aktif...",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id
        )

        try:
            # Panggil fungsi baru untuk set TP/SL saja
            result = order_manager.apply_tpsl_to_existing(signal)
            bot.edit_message_text(
                f"✅ *TP/SL TERPASANG!*\n\n"
                f"Symbol: `{result['symbol']}`\n"
                f"Qty Terdeteksi: `{result['total_quantity']}`\n"
                f"TP1: `{result['tp_configs'][0][0]}`\n"
                f"TP4: `{result['tp_configs'][3][0] if len(result['tp_configs']) > 3 else '-'}`\n"
                f"SL: `{result['sl_price']}`",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode="Markdown"
            )
        except Exception as e:
            bot.edit_message_text(f"❌ *GAGAL!*\n\nError: `{str(e)}`", chat_id=call.message.chat.id, message_id=call.message.message_id)

    elif cmd == "cancel":
        sid = data_parts[1]
        pending_signals.pop(sid, None)
        bot.edit_message_text("🚫 Sinyal dibatalkan.", chat_id=call.message.chat.id, message_id=call.message.message_id)


def _close_position(symbol: str, data: dict) -> dict:
    """Tutup semua posisi aktif untuk symbol."""
    import bingx_client as bx

    positions = bx.get_open_positions(symbol)
    if not positions:
        return {"message": "Tidak ada posisi aktif"}

    closed = []
    for pos in positions:
        pos_side = pos.get("positionSide", "LONG")
        qty = abs(float(pos.get("positionAmt", 0)))

        if qty == 0:
            continue

        close_side = "SELL" if pos_side == "LONG" else "BUY"
        result = bx.place_order(
            symbol=symbol,
            side=close_side,
            position_side=pos_side,
            quantity=qty,
            order_type="MARKET",
        )
        bx.cancel_all_orders(symbol)  # batalkan TP/SL sisa
        closed.append(result)
        logger.info(f"Posisi {pos_side} ditutup: {result}")

    return {"closed_positions": closed}


# ── Background Monitor Thread ──
def start_monitor():
    logger.info("🕵️ Monitor posisi aktif dimulai (cek setiap 10 detik)...")
    while True:
        try:
            order_manager.monitor_and_sync_positions()
        except Exception as e:
            logger.error(f"Monitor error: {e}")
        time.sleep(10)

# Jalankan monitor di background thread
monitor_thread = threading.Thread(target=start_monitor, daemon=True)
monitor_thread.start()


# ─────────────────────────────────────────────
#  JALANKAN SERVER
# ─────────────────────────────────────────────

if __name__ == "__main__":
    logger.info(f"🚀 BingX Webhook Bot v1.2.6 berjalan di http://{HOST}:{PORT}")
    logger.info(f"   Endpoint webhook: http://{HOST}:{PORT}/webhook")
    logger.info("   Mode: Position Monitoring + Auto TP/SL (Deep Fix)")
    app.run(host=HOST, port=PORT, debug=False)
