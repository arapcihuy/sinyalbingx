import os
import time
import logging
from dotenv import load_dotenv
import telebot
from webhook_server import bot, logger

# Ensure logger is configured for polling
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler("polling.log"), logging.StreamHandler()]
)

if __name__ == "__main__":
    logger.info("🚀 Starting Bot in LONG POLLING mode...")
    
    # Remove webhook to enable polling
    try:
        bot.remove_webhook()
        logger.info("✅ Webhook removed.")
    except Exception as e:
        logger.error(f"Failed to remove webhook: {e}")

    # Start infinity polling
    while True:
        try:
            logger.info("📡 Bot is now listening for messages...")
            bot.infinity_polling(timeout=60, long_polling_timeout=20)
        except Exception as e:
            logger.error(f"Polling error: {e}")
            time.sleep(15)
