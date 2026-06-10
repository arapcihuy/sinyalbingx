import os
import telebot
import requests
import json
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
HERMES_API = "http://localhost:20128/v1/chat/completions"
MODEL = "hermes"

bot = telebot.TeleBot(TOKEN)

@bot.message_handler(func=lambda message: True)
def chat_with_hermes(message):
    bot.send_chat_action(message.chat.id, 'typing')
    try:
        payload = {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": "Kamu Hermes. Singkat padat."},
                {"role": "user", "content": message.text}
            ],
            "stream": True # Aktifkan stream karena 9router default-nya stream
        }
        
        res = requests.post(HERMES_API, json=payload, stream=True, timeout=60)
        full_response = ""
        
        for line in res.iter_lines():
            if line:
                line_text = line.decode('utf-8').replace('data: ', '')
                if line_text == '[DONE]': break
                try:
                    chunk = json.loads(line_text)
                    content = chunk['choices'][0]['delta'].get('content', '')
                    full_response += content
                except:
                    continue
        
        if full_response:
            bot.reply_to(message, full_response)
        else:
            bot.reply_to(message, "❌ Gagal ambil respon.")
            
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

if __name__ == "__main__":
    bot.infinity_polling()
