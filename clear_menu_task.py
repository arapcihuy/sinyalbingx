import os
import telebot
from telebot.types import ReplyKeyboardRemove
from dotenv import load_dotenv

load_dotenv()

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not TG_TOKEN or not TG_CHAT_ID:
    print("Error: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not found in .env")
    exit(1)

bot = telebot.TeleBot(TG_TOKEN)

try:
    print(f"Sending request to remove keyboard for Chat ID: {TG_CHAT_ID}...")
    bot.send_message(
        TG_CHAT_ID, 
        "✅ Menu lama telah dihapus dari tampilan bot Anda.", 
        reply_markup=ReplyKeyboardRemove()
    )
    print("Success!")
except Exception as e:
    print(f"Error: {e}")
