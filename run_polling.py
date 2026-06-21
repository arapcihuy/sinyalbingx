import os
import time
import logging
from dotenv import load_dotenv
import telebot
from webhook_server import bot, log

# Ensure logger is configured for polling
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler("polling.log"), logging.StreamHandler()]
)

if __name__ == "__main__":
    log.info("🚀 Starting Bot in LONG POLLING mode...")
    
    # Remove webhook to enable polling
    try:
        bot.remove_webhook()
        log.info("✅ Webhook removed.")
    except Exception as e:
        log.error(f"Failed to remove webhook: {e}")

    # Start infinity polling
    while True:
        try:
            log.info("📡 Bot is now listening for messages...")
            bot.infinity_polling(timeout=60, long_polling_timeout=20)
        except Exception as e:
            err_text = str(e)
            if "409" in err_text or "terminated by other getUpdates request" in err_text:
                log.error("Polling error: 409 Conflict / double polling detected. Pastikan hanya SATU instance bot aktif.")
            else:
                log.error(f"Polling error: {e}")
            time.sleep(15)
