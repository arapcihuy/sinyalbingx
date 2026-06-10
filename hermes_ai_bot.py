import os
import sys
import time
import logging
import requests
import telebot
from dotenv import load_dotenv

# Muat environment variable dari .env
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("hermes_bot")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
OWNER_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

if not TOKEN:
    logger.error("❌ TELEGRAM_BOT_TOKEN tidak ditemukan di environment variable / .env!")
    sys.exit(1)

bot = telebot.TeleBot(TOKEN)

# ── KEAMANAN: Cek Hak Akses Chat ID ──
def is_authorized(message) -> bool:
    if not OWNER_CHAT_ID:
        # Jika tidak dikonfigurasi, default to secure (tolak demi keamanan audit)
        return False
    return str(message.chat.id) == str(OWNER_CHAT_ID)

# ── LOGIKA HELPER: Penampil Menu ──
def get_menu_text() -> str:
    return (
        "🤖 *HERMES AI BINGX CONTROLLER V2*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "Berikut adalah perintah kontrol trading aktif Anda:\n\n"
        "📊 `/status` - Cek posisi trading aktif (Paper/Live)\n"
        "🏦 `/balance` - Cek saldo margin & ekuitas akun BingX\n"
        "📈 `/pnl` - Laporan PnL realisasi 24 jam terakhir\n"
        "🛑 `/closeall` - Tutup paksa semua posisi aktif\n"
        "⚙️ `/settings` - Tampilkan konfigurasi bot saat ini\n"
        "⚡ `/sync` - Sinkronisasi TP/SL posisi yang hilang di bursa\n\n"
        "💬 *Kirim pesan biasa* untuk mengobrol dengan asisten AI Hermes."
    )

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    if not is_authorized(message):
        bot.reply_to(message, "🔒 *Akses Ditolak.* Chat ID Anda tidak terdaftar sebagai pemilik sistem ini.", parse_mode='Markdown')
        logger.warning(f"Unauthorized Access Attempt from Chat ID: {message.chat.id}")
        return
    bot.reply_to(message, get_menu_text(), parse_mode='Markdown')

# ── PERINTAH: Cek Posisi Aktif ──
@bot.message_handler(commands=['status', 'positions'])
def show_status(message):
    if not is_authorized(message):
        bot.reply_to(message, "🔒 Akses Ditolak.")
        return
    bot.send_chat_action(message.chat.id, 'typing')
    try:
        sys.path.insert(0, os.path.dirname(__file__))
        import order_manager
        import bingx_client as bx
        
        paper_mode = order_manager.get_paper_mode()
        
        if paper_mode:
            trades = order_manager.load_paper_trades()
            active_positions = [t for t in trades if t["status"] == "OPEN_PAPER"]
        else:
            active_positions = bx.get_open_positions()
            
        if not active_positions:
            mode_label = "PAPER" if paper_mode else "LIVE/DEMO"
            bot.reply_to(message, f"📭 *Tidak ada posisi aktif saat ini.* (Mode: `{mode_label}`)", parse_mode='Markdown')
            return
            
        msg = f"📊 *POSISI AKTIF ({'PAPER' if paper_mode else 'LIVE'})*\n"
        msg += "━━━━━━━━━━━━━━━━━━━━━\n"
        for pos in active_positions:
            if paper_mode:
                pnl = 0.0
                curr_price = bx.get_current_price(pos["symbol"])
                if curr_price > 0:
                    if pos["side"] == "LONG":
                        pnl = (curr_price - pos["entry"]) * pos["qty"]
                    else:
                        pnl = (pos["entry"] - curr_price) * pos["qty"]
                pnl_color = "+" if pnl >= 0 else ""
                msg += (
                    f"🪙 *{pos['symbol']}* ({pos['side']})\n"
                    f"📈 Entry: `{pos['entry']}` | Cur: `{curr_price}`\n"
                    f"💰 PnL: `{pnl_color}{pnl:.2f} USDT`\n"
                    f"📦 Qty: `{pos['qty']}`\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                )
            else:
                amt = float(pos.get("positionAmt", 0))
                side = pos.get("positionSide", "LONG")
                entry = float(pos.get("avgPrice", 0))
                pnl = float(pos.get("unrealizedProfit", 0))
                sym = pos.get("symbol", "")
                pnl_color = "+" if pnl >= 0 else ""
                msg += (
                    f"🪙 *{sym}* ({side})\n"
                    f"📈 Entry: `{entry}`\n"
                    f"💰 PnL: `{pnl_color}{pnl:.2f} USDT`\n"
                    f"📦 Qty: `{abs(amt)}` | Margin: `{pos.get('isolatedMargin', 0)} USDT`\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                )
        bot.reply_to(message, msg, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error status: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Gagal mengambil status posisi: {e}")

# ── PERINTAH: Cek Saldo ──
@bot.message_handler(commands=['balance'])
def show_balance(message):
    if not is_authorized(message):
        bot.reply_to(message, "🔒 Akses Ditolak.")
        return
    bot.send_chat_action(message.chat.id, 'typing')
    try:
        sys.path.insert(0, os.path.dirname(__file__))
        import bingx_client as bx
        import order_manager
        
        paper_mode = order_manager.get_paper_mode()
        
        if paper_mode:
            trades = order_manager.load_paper_trades()
            closed_pnl = sum(float(t.get("pnl_usdt", 0)) for t in trades if "CLOSED" in t["status"])
            balance = 100.0 + closed_pnl
            msg = (
                f"🏦 *SALDO AKUN (PAPER)*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"💰 *Simulated Balance:* `{balance:.2f} USDT`\n"
                f"📈 *Accumulated PnL:* `{closed_pnl:+.2f} USDT`\n"
                f"━━━━━━━━━━━━━━━━━━━━━"
            )
        else:
            balance_data = bx._request('GET', '/openApi/swap/v2/user/balance')
            if balance_data.get("code") == 0:
                avail = float(balance_data["data"]["balance"]["availableMargin"])
                equity = float(balance_data["data"]["balance"]["equity"])
                is_demo = os.getenv("USE_DEMO", "True") == "True"
                msg = (
                    f"🏦 *SALDO AKUN (LIVE/DEMO)*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"💵 *Available Margin:* `{avail:.2f} USDT`\n"
                    f"📊 *Account Equity:* `{equity:.2f} USDT`\n"
                    f"⚙️ *Platform:* `{'BingX VST/Demo' if is_demo else 'BingX Real Live'}`\n"
                    f"━━━━━━━━━━━━━━━━━━━━━"
                )
            else:
                msg = f"❌ Gagal ambil balance: {balance_data.get('msg')}"
        bot.reply_to(message, msg, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error balance: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Gagal mengambil saldo: {e}")

# ── PERINTAH: Tutup Posisi Masif ──
@bot.message_handler(commands=['closeall'])
def close_all_positions(message):
    if not is_authorized(message):
        bot.reply_to(message, "🔒 Akses Ditolak.")
        return
    bot.send_chat_action(message.chat.id, 'typing')
    try:
        sys.path.insert(0, os.path.dirname(__file__))
        import order_manager
        
        paper_mode = order_manager.get_paper_mode()
        
        res_btc = order_manager._close_position("BTC-USDT")
        res_eth = order_manager._close_position("ETH-USDT")
        
        msg = (
            f"🛑 *CLOSE ALL POSITIONS SENT*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 BTC-USDT: `{res_btc.get('msg')}`\n"
            f"🪙 ETH-USDT: `{res_eth.get('msg')}`\n"
            f"⚙️ Mode: `{'PAPER' if paper_mode else 'LIVE'}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━"
        )
        bot.reply_to(message, msg, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error closeall: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Gagal menutup posisi: {e}")

# ── PERINTAH: Tampilkan Konfigurasi ──
@bot.message_handler(commands=['settings'])
def show_settings(message):
    if not is_authorized(message):
        bot.reply_to(message, "🔒 Akses Ditolak.")
        return
    try:
        sys.path.insert(0, os.path.dirname(__file__))
        import settings_manager
        current_settings = settings_manager.load_settings()
        
        msg = (
            f"⚙️ *KONFIGURASI BOT AKTIF*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🟢 *Auto Entry:* `{current_settings.get('auto_entry')}`\n"
            f"📝 *TP Mode:* `{current_settings.get('tp_mode')}`\n"
            f"🛡️ *Paper Mode:* `{current_settings.get('paper_mode')}`\n"
            f"🛑 *Risk Per Trade:* `{os.getenv('RISK_PER_TRADE_PERCENT', '2.0')}%`\n"
            f"📊 *Min R:R Ratio:* `{current_settings.get('min_rr_ratio', 1.5)}`\n"
            f"👥 *Max Open Slots:* `{current_settings.get('max_slots', 3)}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Untuk keamanan operasional, ubah mode Paper/Live langsung di berkas konfigurasi `.env` atau `bot_settings.json`."
        )
        bot.reply_to(message, msg, parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, f"❌ Gagal menampilkan setting: {e}")

# ── PERINTAH: Laporan Realized PnL 24 Jam ──
@bot.message_handler(commands=['pnl', 'profit'])
def show_pnl(message):
    if not is_authorized(message):
        bot.reply_to(message, "🔒 Akses Ditolak.")
        return
    bot.send_chat_action(message.chat.id, 'typing')
    try:
        sys.path.insert(0, os.path.dirname(__file__))
        import bingx_client as bx
        import order_manager
        
        paper_mode = order_manager.get_paper_mode()
        
        if paper_mode:
            trades = order_manager.load_paper_trades()
            closed_pnl = sum(float(t.get("pnl_usdt", 0)) for t in trades if "CLOSED" in t["status"])
            msg = (
                f"📊 *LAPORAN PROFIT SIMULASI (PAPER)*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"💰 *Total Realized PnL:* `{closed_pnl:+.2f} USDT`\n"
                f"⚙️ Mode: `PAPER`\n"
                f"━━━━━━━━━━━━━━━━━━━━━"
            )
        else:
            incomes = bx.get_income_history(days=1)
            pnl_24h = sum(
                float(inc.get("income", 0)) 
                for inc in incomes 
                if inc.get("incomeType") in ["REALIZED_PNL", "COMMISSION", "FUNDING_FEE"]
            )
            icon = "📈" if pnl_24h >= 0 else "📉"
            msg = (
                f"📊 *LAPORAN PnL REALISASI 24 JAM*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"💰 *Net PnL:* `{pnl_24h:+.2f} USDT` {icon}\n"
                f"⚙️ Mode: `LIVE`\n"
                f"━━━━━━━━━━━━━━━━━━━━━"
            )
        bot.reply_to(message, msg, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error PnL: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Gagal mengambil laporan PnL: {e}")

# ── PERINTAH: Sinkronisasi TP/SL ──
@bot.message_handler(commands=['sync'])
def sync_tpsl(message):
    if not is_authorized(message):
        bot.reply_to(message, "🔒 Akses Ditolak.")
        return
    bot.send_chat_action(message.chat.id, 'typing')
    try:
        sys.path.insert(0, os.path.dirname(__file__))
        import order_manager
        res = order_manager.sync_missing_tpsl()
        msg = (
            f"🔄 *SINKRONISASI TP/SL SELESAI*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Result: `{res}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━"
        )
        bot.reply_to(message, msg, parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, f"❌ Gagal sinkronisasi: {e}")

# ── ASSISTANT CHAT AI (Hermes via OpenAI API) ──
@bot.message_handler(func=lambda message: True)
def chat_with_hermes(message):
    if not is_authorized(message):
        bot.reply_to(message, "🔒 Akses Ditolak.")
        return
        
    bot.send_chat_action(message.chat.id, 'typing')
    
    if message.text.startswith("/"):
        bot.reply_to(message, "⚠️ Perintah tidak dikenal. Silakan ketik `/help` untuk menu perintah.")
        return
        
    if not OPENAI_API_KEY:
        bot.reply_to(message, "❌ Hermes AI Assistant sedang offline karena OPENAI_API_KEY tidak dikonfigurasi di environment.")
        return

    try:
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "Anda adalah Hermes, asisten trading pintar BingX. Jawablah dengan singkat, padat, berwawasan, dan langsung ke poin utama menggunakan Bahasa Indonesia. Gaya bicara Anda adalah pakar Cybersecurity Auditor & CEH."},
                {"role": "user", "content": message.text}
            ],
            "max_tokens": 400,
            "temperature": 0.7
        }
        res = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {OPENAI_API_KEY}"},
            json=payload,
            timeout=15
        )
        
        if res.status_code == 200:
            data = res.json()
            full_response = data["choices"][0]["message"]["content"].strip()
            bot.reply_to(message, full_response)
        else:
            logger.error(f"OpenAI API error: {res.status_code} - {res.text}")
            bot.reply_to(message, f"❌ Gagal menghubungi otak AI Hermes (Status {res.status_code}).")
            
    except Exception as e:
        logger.error(f"Error Hermes Chat: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Error: {str(e)}")

if __name__ == "__main__":
    logger.info("📡 Hermes Bot V2 listening...")
    bot.infinity_polling()
