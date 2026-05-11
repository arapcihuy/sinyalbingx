import os
import logging
import uuid
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import order_manager
import settings_manager

# Load initial settings
settings = settings_manager.load_settings()
CURRENT_LEVERAGE = settings.get("leverage", 40)
import threading
import time

# Load environment variables
load_dotenv()

# Konfigurasi Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Konfigurasi Utama
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
PORT = int(os.getenv("PORT", 5000))
HOST = os.getenv("HOST", "0.0.0.0")
DUPLICATE_SIGNAL_TTL = int(os.getenv("WEBHOOK_DEDUP_TTL_SECONDS", 45))

# ── Telegram Config ──
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
bot = telebot.TeleBot(TG_TOKEN, threaded=True)
WEBHOOK_URL = os.getenv("WEBHOOK_URL") 
# Set menu perintah bot
try:
    bot.set_my_commands([
        telebot.types.BotCommand("start", "Mulai / Reset Menu Bot"),
        telebot.types.BotCommand("status", "Cek posisi & balance aktif"),
        telebot.types.BotCommand("market", "Cek harga pasar saat ini"),
        telebot.types.BotCommand("settings", "Cek konfigurasi bot"),
        telebot.types.BotCommand("report", "Laporan profit 24 jam terakhir"),
        telebot.types.BotCommand("tpsl", "Pasang Auto TP/SL (Manual Entry)"),
        telebot.types.BotCommand("susul", "Re-entry sinyal terakhir jika belum kena TP1"),
        telebot.types.BotCommand("leverage", "Ganti leverage (1x - 150x)"),
        telebot.types.BotCommand("panic", "Tutup semua posisi & cancel order"),
        telebot.types.BotCommand("reset", "Muat ulang menu bot"),
        telebot.types.BotCommand("help", "Panduan penggunaan bot"),
    ])
except Exception as e:
    logger.error(f"Gagal set menu perintah: {e}")

# CURRENT_LEVERAGE sudah di-load di atas

# ── Cache untuk deduplikasi sinyal ──
processed_signals = {}
pending_signals = {}

# ── Set Webhook Otomatis jika ada URL ──
if WEBHOOK_URL:
    try:
        tg_webhook_url = WEBHOOK_URL.rstrip('/')
        if not tg_webhook_url.endswith('/telegram'):
            tg_webhook_url += '/telegram'
        bot.remove_webhook()
        bot.set_webhook(url=tg_webhook_url)
        logger.info(f"✅ Telegram Webhook berhasil diset ke: {tg_webhook_url}")
    except Exception as e:
        logger.error(f"❌ Gagal set webhook: {e}")


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy", "bot": "active"}), 200

@app.route("/webhook", methods=["POST"])
def webhook():
    """Endpoint untuk menerima sinyal dari TradingView."""
    # Tangkap semua request (walaupun text biasa dari alert asli) agar tidak error merah di TV
    if not request.is_json:
        return jsonify({"status": "ignored", "reason": "Bukan format JSON. Diabaikan."}), 200
        
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "ignored", "reason": "Format JSON tidak valid."}), 200
        
    # Konversi semua key ke lowercase agar aman (TP1 -> tp1)
    data = {k.lower(): v for k, v in data.items()}
    
    if data.get("secret") != os.getenv("WEBHOOK_SECRET"):
        return jsonify({"error": "Unauthorized"}), 401
        
    action = data.get("action", "").upper()
    symbol = data.get("symbol", "BTC-USDT")
    
    # 2. Deduplikasi Sinyal (Cegah double execution)
    signal_key = f"{symbol}_{action}_{data.get('price')}"
    now = time.time()
    if signal_key in processed_signals:
        if now - processed_signals[signal_key] < DUPLICATE_SIGNAL_TTL:
            logger.info(f"Sinyal duplikat diabaikan: {signal_key}")
            return jsonify({"status": "ignored", "reason": "duplicate"}), 200
    processed_signals[signal_key] = now

    logger.info("==================================================")
    logger.info(f"Payload diterima: {data}")
    
    # ── Simpan Sinyal Terakhir untuk Keperluan Re-Entry ──
    order_manager.latest_signals[symbol] = data
    order_manager.save_latest_signals()

    # ── Notifikasi Awal ke Telegram (Asynchronous) ──
    def send_notif_bg(text):
        try:
            bot.send_message(TG_CHAT_ID, text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Gagal kirim notif telegram: {e}")

    initial_msg = f"🔔 *SINYAL MASUK: {symbol}*\nAction: `{action}`\n"
    if data.get("price"):
        initial_msg += f"Price: `{data.get('price')}`\n"
    threading.Thread(target=send_notif_bg, args=(initial_msg,), daemon=True).start()

    # ── Cek Mode Otomatis ──
    current_settings = settings_manager.load_settings()
    AUTO_ENTRY = current_settings.get("auto_entry", False)
    
    if AUTO_ENTRY:
        try:
            lev_from_signal = data.get("leverage", os.getenv("LEVERAGE", "10"))
            logger.info(f"⚡ Mode OTOMATIS aktif. Leverage dari sinyal: {lev_from_signal}x. Eksekusi...")
            result = order_manager.execute_signal(data)
            
            # Notifikasi Sukses / Warning (Asynchronous)
            status_text = "BERHASIL"
            if "warning" in result.get("status", ""):
                status_text = "BERHASIL (⚠️ TP/SL GAGAL)"
            
            exec_msg = (
                f"⚡ *EKSEKUSI OTOMATIS {status_text}*\n"
                f"Symbol: `{symbol}`\n"
                f"Action: `{action}`\n"
                f"Qty: `{result.get('total_quantity', 'N/A')}`\n"
                f"Status: `{result.get('status')}`"
            )
            threading.Thread(target=send_notif_bg, args=(exec_msg,), daemon=True).start()
            return jsonify({"status": "success", "message": status_text}), 200
        except Exception as e:
            logger.error(f"❌ Gagal eksekusi otomatis: {e}")
            fail_msg = f"❌ *GAGAL EKSEKUSI OTOMATIS!*\n\nError: `{str(e)}`"
            threading.Thread(target=send_notif_bg, args=(fail_msg,), daemon=True).start()
            return jsonify({"error": str(e)}), 500

    # ── Jika Mode Otomatis Mati, Minta Konfirmasi Telegram ──
    try:
        signal_id = str(uuid.uuid4())[:8]
        pending_signals[signal_id] = data
        
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
            f"Symbol: `{symbol}`\n"
            f"Price: `{data.get('price', 'MARKET')}`\n\n"
            f"Pilih Leverage untuk eksekusi:"
        )
        bot.send_message(TG_CHAT_ID, msg, parse_mode="Markdown", reply_markup=markup)
        return jsonify({"status": "pending", "message": "Menunggu konfirmasi Telegram", "id": signal_id}), 200
    except Exception as e:
        logger.error(f"❌ Error saat kirim konfirmasi: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return ''
    return jsonify({"error": "Invalid content type"}), 403

@bot.message_handler(commands=['cekbot'])
def cekbot_cmd(message):
    bot.reply_to(message, "✅ Bot versi TERBARU sudah berjalan!", parse_mode="HTML")

@bot.message_handler(commands=['clearmenu', 'start', 'reset'])
def clear_menu(message):
    markup = telebot.types.ReplyKeyboardRemove()
    current_settings = settings_manager.load_settings()
    auto_mode = "AKTIF 🟢" if current_settings.get("auto_entry") else "MATI 🔴 (Konfirmasi Manual)"
    
    welcome_msg = (
        "🤖 *BingX Auto-Trading Bot Aktif!*\n\n"
        f"Leverage Default: `{CURRENT_LEVERAGE}x`\n"
        f"Mode Auto-Entry: `{auto_mode}`\n\n"
        "📜 *Perintah Utama:*\n"
        "• /status - Cek saldo & posisi\n"
        "• /market - Cek harga koin\n"
        "• /settings - Lihat config bot\n"
        "• /help - Panduan penggunaan\n"
        "• /panic - Tutup SEMUA posisi\n\n"
        "Bot siap menerima sinyal dari TradingView."
    )
    bot.send_message(message.chat.id, welcome_msg, reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(commands=['market', 'price'])
def market_price_cmd(message):
    try:
        import bingx_client as bx
        args = message.text.split()
        
        def format_price(p):
            return f"{float(p):.5f}".rstrip('0').rstrip('.') if '.' in f"{float(p):.5f}" else str(p)

        if len(args) > 1:
            symbol = args[1].upper()
            if "-" not in symbol: symbol += "-USDT"
            price = bx.get_current_price(symbol)
            msg = f"📊 *MARKET PRICE*\n\nCoin: `{symbol}`\nPrice: `{format_price(price)} USDT`"
        else:
            msg = "📊 *MARKET PRICE*\n\n"
            for sym in ["BTC-USDT", "ETH-USDT", "SOL-USDT"]:
                try:
                    price = bx.get_current_price(sym)
                    msg += f"• `{sym}` : `{format_price(price)} USDT`\n"
                except:
                    pass
        bot.send_message(message.chat.id, msg, parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Gagal ambil harga: `{str(e)}`")

@bot.message_handler(commands=['help', 'bantuan'])
def help_cmd(message):
    help_text = (
        "📖 *PANDUAN BINGX BOT*\n\n"
        "• /status - Menampilkan saldo USDT dan detail posisi yang sedang terbuka.\n"
        "• /market [KODE] - Cek harga koin. Contoh: `/market btc` atau `/market eth`.\n"
        "• /settings - Melihat pengaturan leverage dan mode trading saat ini.\n"
        "• /leverage - Mengubah leverage default melalui tombol.\n"
        "• /tpmode - Mengganti mode TP (Scalping atau Trend).\n"
        "• /tpsl [HARGA_SL] - Memasang TP/SL otomatis untuk posisi manual.\n"
        "• /susul [KODE] - Re-entry otomatis menggunakan sinyal terakhir.\n"
        "• /report - Melihat ringkasan Profit/Loss (PnL) 24 jam terakhir.\n"
        "• /panic - Menutup SEMUA posisi dan membatalkan semua order secara instan.\n"
        "• /reset - Memuat ulang menu utama bot.\n\n"
        "💡 *Tips:* Bot ini otomatis trading 24/7 jika sinyal dari TradingView masuk."
    )
    bot.send_message(message.chat.id, help_text, parse_mode="Markdown")

@bot.message_handler(commands=['settings', 'config'])
def settings_cmd(message):
    current_settings = settings_manager.load_settings()
    risk = os.getenv("RISK_PERCENT", "1.5")
    mode = "Otomatis" if current_settings.get("auto_entry") else "Manual (Konfirmasi)"
    
    msg = (
        "⚙️ *KONFIGURASI BOT SAAT INI*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"🤖 *Mode:* `{mode}`\n"
        f"⚖️ *Leverage:* `{current_settings.get('leverage')}x`\n"
        f"💰 *Risk per Trade:* `{risk}% dari saldo`\n"
        f"🎯 *Mode TP:* `{ 'Scalping (TP1 Only)' if current_settings.get('tp_mode') == 'tp1_only' else 'Trend (Multi-TP)' }`\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "Gunakan /leverage atau /tpmode untuk mengubah."
    )
    bot.send_message(message.chat.id, msg, parse_mode="Markdown")

@bot.message_handler(commands=['tpsl'])
def tpsl_cmd(message):
    try:
        args = message.text.split()
        
        # Deteksi posisi aktif jika symbol tidak disebutkan
        import bingx_client as bx
        open_positions = bx.get_open_positions()
        
        symbol = None
        tp_price = None
        sl_price = None
        
        if len(args) == 3:
            # Format: /tpsl [TP] [SL] (Auto-detect symbol)
            if len(open_positions) == 1:
                symbol = open_positions[0]["symbol"]
                tp_price = float(args[1])
                sl_price = float(args[2])
            elif len(open_positions) == 0:
                bot.reply_to(message, "❌ Tidak ada posisi aktif untuk dipasang TP/SL.")
                return
            else:
                bot.reply_to(message, "❌ Ada lebih dari 1 posisi aktif. Tolong sebutkan symbolnya!\nContoh: `/tpsl SOL-USDT 90 87`", parse_mode="Markdown")
                return
                
        elif len(args) == 4:
            # Format: /tpsl [SYMBOL] [TP] [SL]
            symbol = args[1].upper()
            if "-" not in symbol: symbol += "-USDT"
            tp_price = float(args[2])
            sl_price = float(args[3])
        else:
            bot.reply_to(message, "❌ <b>Format Salah!</b>\nContoh: <code>/tpsl 90 87</code>\nAtau: <code>/tpsl SOL-USDT 90 87</code>", parse_mode="HTML")
            return
            
        bot.reply_to(message, f"⏳ Memasang TP/SL...", parse_mode="HTML")
        
        import order_manager
        res = order_manager.apply_manual_tpsl(symbol, tp_price, sl_price)
        
        tps = res["tps"]
        msg = f"✅ <b>{symbol}</b> | TP: <code>{tps[0]:.2f}</code> | SL: <code>{res['sl']:.2f}</code>"
        
        bot.send_message(message.chat.id, msg, parse_mode="HTML")
    except ValueError as ve:
        bot.reply_to(message, f"❌ <b>Gagal:</b> {str(ve)}", parse_mode="HTML")
    except Exception as e:
        logger.error(f"Gagal set tpsl manual: {e}")
        bot.reply_to(message, f"❌ <b>System Error:</b> {str(e)}", parse_mode="HTML")

@bot.message_handler(commands=['susul', 'reentry'])
def reentry_cmd(message):
    try:
        args = message.text.split()
        if len(args) < 2:
            bot.reply_to(message, "❌ *Format Salah!*\nContoh: `/susul ETH` atau `/susul BTC-USDT`", parse_mode="Markdown")
            return
            
        symbol = args[1].upper()
        if "-" not in symbol: 
            symbol += "-USDT"
            
        bot.reply_to(message, f"⏳ Memeriksa keamanan re-entry untuk `{symbol}`...", parse_mode="Markdown")
        
        import order_manager
        result = order_manager.reentry_signal(symbol)
        
        # Notifikasi Sukses
        status_text = "BERHASIL RE-ENTRY"
        if "warning" in result.get("status", ""):
            status_text += " (⚠️ TP/SL GAGAL)"
            
        exec_msg = (
            f"⚡ *EKSEKUSI RE-ENTRY {status_text}*\n"
            f"Symbol: `{result.get('symbol')}`\n"
            f"Action: `{result.get('action')}`\n"
            f"Qty: `{result.get('total_quantity', 'N/A')}`\n"
            f"Status: `{result.get('status')}`"
        )
        bot.send_message(message.chat.id, exec_msg, parse_mode="Markdown")
        
    except ValueError as ve:
        bot.reply_to(message, f"❌ *Ditolak:* {str(ve)}", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Gagal re-entry: {e}")
        bot.reply_to(message, f"❌ *System Error:* `{str(e)}`", parse_mode="Markdown")


@bot.message_handler(commands=['leverage', 'setleverage'])
def set_leverage_cmd(message):
    global CURRENT_LEVERAGE
    try:
        args = message.text.split()
        if len(args) == 2:
            new_lev = int(args[1])
            if 1 <= new_lev <= 150:
                CURRENT_LEVERAGE = new_lev
                # Simpan ke file agar tidak hilang saat restart
                settings_manager.save_settings({"leverage": CURRENT_LEVERAGE})
                bot.reply_to(message, f"✅ *Leverage Berhasil Diubah!*\nSekarang: `{CURRENT_LEVERAGE}x`", parse_mode="Markdown")
                return

        markup = InlineKeyboardMarkup(row_width=4)
        options = [1, 2, 5, 10, 20, 30, 40, 50, 60, 75, 100, 125, 150]
        buttons = [InlineKeyboardButton(f"{opt}x", callback_data=f"setlev:{opt}") for opt in options]
        markup.add(*buttons)
        bot.send_message(message.chat.id, f"⚙️ *PILIH LEVERAGE DEFAULT*\nLeverage saat ini: `{CURRENT_LEVERAGE}x`", reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, "❌ Gagal memuat menu leverage.")

@bot.message_handler(commands=['status', 'cek'])
def status_cmd(message):
    try:
        logger.info(f"⏳ Memulai pengambilan status untuk {message.chat.id}...")
        import bingx_client as bx
        
        # 1. Ambil Balance
        balance = bx.get_balance()
        logger.info("✅ Balance berhasil diambil")
        
        # 2. Ambil Posisi
        positions = bx.get_open_positions()
        logger.info(f"✅ {len(positions)} posisi aktif ditemukan")
        
        # Ambil leverage dan TP mode dari file settings
        current_settings = settings_manager.load_settings()
        leverage_display = current_settings.get("leverage", 40)
        tp_mode = current_settings.get("tp_mode", "tp1_only")
        tp_mode_display = "Scalping (TP1 Only) 🎯" if tp_mode == "tp1_only" else "Trend (Multi-TP) 🚀"
        
        status_msg = f"<b>📊 [ SYSTEM STATUS ]</b>\n"
        status_msg += f"━━━━━━━━━━━━━━━━━━━━━\n"
        status_msg += f"💰 <b>Balance:</b> <code>{balance:.2f} USDT</code>\n"
        status_msg += f"⚙️ <b>Leverage:</b> <code>{leverage_display}x</code>\n"
        status_msg += f"🤖 <b>Mode Entry:</b> <code>AUTO-ENTRY 🟢</code>\n"
        status_msg += f"🎯 <b>Mode TP:</b> <code>{tp_mode_display}</code>\n"
        status_msg += f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        if not positions:
            status_msg += "📭 <b>Posisi Aktif:</b> <code>None</code>"
        else:
            status_msg += "<b>📝 Posisi Terbuka:</b>\n"
            for pos in positions:
                sym = pos.get("symbol")
                side = pos.get("positionSide")
                amt = abs(float(pos.get("positionAmt", 0)))
                pnl = float(pos.get("unrealizedProfit", "0"))
                pos_lev = pos.get("leverage", "-")
                
                avg_p = float(pos.get("avgPrice", 0))
                mark_p = float(pos.get("markPrice", 0))
                liq_p = float(pos.get("liquidationPrice", 0))
                margin_raw = pos.get("initialMargin", pos.get("margin", 0))
                margin = float(margin_raw)

                roe = (pnl / margin * 100) if margin > 0 else 0
                pnl_icon = "📈" if pnl >= 0 else "📉"
                
                def format_price(p):
                    return f"{float(p):.5f}".rstrip('0').rstrip('.') if '.' in f"{float(p):.5f}" else str(p)

                status_msg += f"• <b>{sym}</b> ({side}) - <code>{pos_lev}x</code>\n"
                status_msg += f"  💰 Margin: <code>{margin:.2f}</code> | Size: <code>{amt}</code>\n"
                status_msg += f"  📥 Entry: <code>{format_price(avg_p)}</code> | Mark: <code>{format_price(mark_p)}</code>\n"
                status_msg += f"  💀 Liq: <code>{format_price(liq_p)}</code>\n"
                
                # Cek data TPs dari memori bot
                trade_data = order_manager.active_trade_data.get(sym, {})
                tps = trade_data.get("tps", [])
                if tps: 
                    tps_str = ', '.join([format_price(tp) for tp in tps])
                    status_msg += f"  🎯 TPs: <code>{tps_str}</code>\n"
                
                sl = trade_data.get("sl")
                if sl:
                    status_msg += f"  🛑 SL: <code>{format_price(sl)}</code>\n"
                
                status_msg += f"  💵 PnL: <b>{pnl:+.2f} USDT</b> (<code>{roe:+.2f}%</code>) {pnl_icon}\n"
                status_msg += "━━━━━━━━━━━━━━━━━━━━━\n"
                
        logger.info("📤 Mengirim pesan HTML ke Telegram...")
        bot.send_message(message.chat.id, status_msg, parse_mode="HTML")
        logger.info("✅ Pesan terhasil dikirim!")
    except Exception as e:
        logger.error(f"❌ Gagal status: {e}")
        bot.send_message(message.chat.id, f"❌ <b>Gagal ambil status</b>\nError: <code>{str(e)}</code>", parse_mode="HTML")

@bot.message_handler(commands=['tpmode'])
def tpmode_cmd(message):
    try:
        current_settings = settings_manager.load_settings()
        current_mode = current_settings.get("tp_mode", "tp1_only")
        
        # Jika user kirim "/tpmode 1" atau "/tpmode multi"
        cmd_text = message.text.split()
        if len(cmd_text) > 1:
            val = cmd_text[1].lower()
            if val in ['1', 'tp1', 'scalping']:
                new_mode = "tp1_only"
            elif val in ['4', 'multi', 'trend']:
                new_mode = "multi_tp"
            else:
                bot.reply_to(message, "❌ Gunakan: `/tpmode 1` (TP1 Only) atau `/tpmode multi` (Semua TP)", parse_mode="Markdown")
                return
            
            current_settings["tp_mode"] = new_mode
            settings_manager.save_settings(current_settings)
            msg = "🎯 *Mode TP1 Only Aktif* (Scalping)" if new_mode == "tp1_only" else "🚀 *Mode Multi-TP Aktif* (Trend)"
            bot.send_message(message.chat.id, f"✅ *Setting Berhasil Diubah!*\n{msg}", parse_mode="Markdown")
            return

        # Menu Interaktif
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("🎯 TP1 ONLY (Scalping)", callback_data="settpmode:tp1_only"),
            InlineKeyboardButton("🚀 MULTI-TP (Trend)", callback_data="settpmode:multi_tp")
        )
        
        mode_text = "Scalping (TP1 Only)" if current_mode == "tp1_only" else "Trend (Multi-TP)"
        bot.send_message(message.chat.id, f"⚙️ *PILIH MODE TAKE PROFIT*\nSaat ini: `{mode_text}`", reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error tpmode_cmd: {e}")
        bot.reply_to(message, "❌ Gagal memuat menu TP mode.")

@bot.message_handler(commands=['panic', 'closeall'])
def panic_cmd(message):
    try:
        result = _close_all_positions()
        closed_count = len(result.get("closed_positions", []))
        bot.send_message(message.chat.id, f"🛑 *PANIC MODE AKTIF*\n\nPosisi ditutup: `{closed_count}`", parse_mode="Markdown")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Gagal: `{str(e)}`", parse_mode="Markdown")

@bot.message_handler(commands=['log'])
def log_cmd(message):
    try:
        if not os.path.exists("bot.log"):
            bot.send_message(message.chat.id, "❌ File bot.log tidak ditemukan.")
            return
        with open("bot.log", "r") as f:
            lines = f.readlines()
            last_lines = lines[-15:] if len(lines) > 15 else lines
            log_text = "".join(last_lines)
        bot.send_message(message.chat.id, f"📜 *LOG TERAKHIR:*\n\n```\n{log_text}\n```", parse_mode="Markdown")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Gagal baca log: `{str(e)}`", parse_mode="Markdown")

@bot.message_handler(commands=['report', 'pnl'])
def report_cmd(message):
    """Kirim laporan performa (PnL) merangkum 24 Jam, 7 Hari, dan 30 Hari."""
    try:
        import bingx_client as bx
        import time
        
        bot.send_message(message.chat.id, "⏳ Sedang merekap data laporan 30 hari terakhir...", parse_mode="HTML")
        
        # 1. Ambil Balance & Unrealized PnL
        balance = bx.get_balance()
        positions = bx.get_open_positions()
        unrealized_pnl = sum(float(pos.get("unrealizedProfit", 0)) for pos in positions)
        total_aset = balance + unrealized_pnl
        
        # 2. Ambil Income 30 Hari (Sekali panggil API)
        incomes = bx.get_income_history(days=30)
        
        now_ms = int(time.time() * 1000)
        day_ms = 24 * 60 * 60 * 1000
        
        # Siapkan wadah (Realized + Fees)
        pnl_1d = 0; pnl_7d = 0; pnl_30d = 0
        
        for inc in incomes:
            inc_type = inc.get("incomeType", "")
            val = float(inc.get("income", 0))
            inc_time = int(inc.get("time", 0))
            
            # Hanya peduli Realized PnL & Fee
            if inc_type in ["REALIZED_PNL", "COMMISSION", "FUNDING_FEE"]:
                # Tambahkan ke 30 Hari
                pnl_30d += val
                
                # Cek apakah masuk 7 Hari
                if now_ms - inc_time <= 7 * day_ms:
                    pnl_7d += val
                    
                # Cek apakah masuk 24 Jam
                if now_ms - inc_time <= 1 * day_ms:
                    pnl_1d += val
                    
        # 3. Gabungkan dengan Unrealized (Hanya yang 24 Jam/Saat ini)
        tot_1d = pnl_1d + unrealized_pnl
        tot_7d = pnl_7d + unrealized_pnl
        tot_30d = pnl_30d + unrealized_pnl
        
        msg = f"<b>📊 [ REKAP PnL FUTURES ]</b>\n"
        msg += f"━━━━━━━━━━━━━━━━━━━━━\n"
        msg += f"🏦 <b>Total Nilai Aset:</b> <code>{total_aset:.2f} USDT</code>\n"
        msg += f"<i>*Termasuk Unrealized PnL: {unrealized_pnl:+.2f} USDT</i>\n"
        msg += f"━━━━━━━━━━━━━━━━━━━━━\n"
        msg += f"<b>📈 Profit / Loss Bersih:</b>\n"
        msg += f"   ├ <b>24 Jam:</b> <code>{tot_1d:+.2f} USDT</code>\n"
        msg += f"   ├ <b>7 Hari:</b> <code>{tot_7d:+.2f} USDT</code>\n"
        msg += f"   └ <b>30 Hari:</b> <code>{tot_30d:+.2f} USDT</code>\n"
        
        bot.send_message(message.chat.id, msg, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Gagal buat laporan: {e}")
        bot.send_message(message.chat.id, f"❌ <b>Gagal mengambil data laporan.</b>\nError: <code>{str(e)}</code>", parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    data_parts = call.data.split(":")
    cmd = data_parts[0]
    
    if cmd == "setlev":
        new_lev = int(data_parts[1])
        global CURRENT_LEVERAGE
        CURRENT_LEVERAGE = new_lev
        
        # Simpan ke settings agar tidak hilang saat restart (merge with existing)
        current_settings = settings_manager.load_settings()
        current_settings["leverage"] = CURRENT_LEVERAGE
        settings_manager.save_settings(current_settings)
        
        bot.edit_message_text(
            f"✅ *Leverage Berhasil Diubah!*\nSekarang Bot menggunakan: `{CURRENT_LEVERAGE}x`",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="Markdown"
        )
        status_cmd(call.message)
        return

    if cmd == "settpmode":
        new_mode = data_parts[1]
        current_settings = settings_manager.load_settings()
        current_settings["tp_mode"] = new_mode
        settings_manager.save_settings(current_settings)
        
        mode_text = "🎯 *Mode TP1 Only Aktif* (Scalping)" if new_mode == "tp1_only" else "🚀 *Mode Multi-TP Aktif* (Trend)"
        bot.edit_message_text(
            f"✅ *Setting Berhasil Diubah!*\n{mode_text}",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="Markdown"
        )
        status_cmd(call.message)
        return
        
    if cmd == "exec":
        leverage = int(data_parts[1])
        sid = data_parts[2]
        if sid not in pending_signals:
            bot.answer_callback_query(call.id, "Sinyal kadaluarsa!")
            return
        signal = pending_signals.pop(sid)
        signal["leverage"] = leverage
        bot.edit_message_text(f"⚙️ Memproses `{signal['action']}` `{signal['symbol']}`...", chat_id=call.message.chat.id, message_id=call.message.message_id)
        try:
            result = order_manager.execute_signal(signal)
            bot.edit_message_text(f"✅ *ORDER BERHASIL!*\nSymbol: `{result['symbol']}`", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="Markdown")
        except Exception as e:
            bot.edit_message_text(f"❌ *GAGAL*\nError: `{str(e)}`", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="Markdown")

    if cmd == "cancel":
        sid = data_parts[1]
        pending_signals.pop(sid, None)
        bot.edit_message_text("❌ Sinyal dibatalkan.", chat_id=call.message.chat.id, message_id=call.message.message_id)

def _close_all_positions():
    import bingx_client as bx
    positions = bx.get_open_positions()
    closed = []
    symbols = []
    for pos in positions:
        symbol = pos["symbol"]
        side = pos["positionSide"]
        qty = abs(float(pos["positionAmt"]))
        close_side = "SELL" if side == "LONG" else "BUY"
        res = bx.place_order(symbol, close_side, side, qty, reduce_only=True)
        bx.cancel_all_orders(symbol)
        closed.append(res)
        symbols.append(symbol)
    return {"closed_positions": closed, "symbols": list(set(symbols))}

def start_monitor():
    """Jalankan monitor sinkronisasi posisi di background."""
    logger.info("🕵️ Monitor posisi aktif dimulai (cek setiap 10 detik)...")
    last_report_date = None
    
    while True:
        try:
            # --- 1. Sinkronisasi Posisi & Trailing SL ---
            order_manager.monitor_and_sync_positions()
            
            # --- 2. Kirim Laporan Harian Otomatis (Jam 7 Pagi WIB / 00:00 UTC) ---
            now_utc = time.gmtime()
            today_str = time.strftime("%Y-%m-%d", now_utc)
            
            if now_utc.tm_hour == 0 and last_report_date != today_str:
                logger.info("📢 Mengirim Laporan Performa Harian Otomatis...")
                # Panggil fungsi report secara internal
                class DummyMsg: chat = type('obj', (object,), {'id': TG_CHAT_ID})
                report_cmd(DummyMsg())
                last_report_date = today_str

        except Exception as e:
            logger.error(f"Error di monitor thread: {e}")
        time.sleep(10)

# ── Jalankan Monitor (Radar) di Background ──
# Ini harus di luar __main__ agar jalan saat dideploy lewat Gunicorn
monitor_thread = threading.Thread(target=start_monitor, daemon=True)
monitor_thread.start()
logger.info("🚀 Background Monitor (Radar) Started")

if __name__ == "__main__":
    app.run(host=HOST, port=PORT)
