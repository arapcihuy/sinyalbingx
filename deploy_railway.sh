#!/bin/bash

echo "🚀 Memulai setup Railway..."

# 1. Install Railway CLI jika belum ada
if ! command -v railway &> /dev/null
then
    echo "📦 Installing Railway CLI via Homebrew..."
    brew install railway
fi

# 2. Login (Hanya diperlukan sekali saja)
# echo "🔑 Silahkan login ke Railway di browser yang akan terbuka..."
# railway login

# 3. Hubungkan Project (Lakukan secara manual jika belum terhubung)
# Jika sudah pernah di-link, langkah ini akan otomatis menggunakan project yang ada.
echo "🔗 Memastikan project terhubung..."
# railway link  # Aktifkan ini jika ingin otomatis minta link setiap jalan

# 4. Set Variables dari .env
echo "⚙️ Mengatur environment variables..."
railway variables set \
  BINGX_API_KEY=FS800S6GYrielJGqKlRa1XgWOPmZeZRCJjtlDiouVnSf5yQrwhLJ1Bl9P51islnEBbgAxqoqeqzVP5Fw9Fw \
  BINGX_API_SECRET=p8BmfLQev4mzlzXjOORSlzbVKmgcC7fOgY72T7a62KFb5oWZwdg2jPJecori0E00rQCYNSBvWg3YvFxY612IQ \
  WEBHOOK_SECRET=Tr4d3BotBingX@2025!xK9 \
  TELEGRAM_BOT_TOKEN=8610835184:AAFHpzr3OH0UGh8NvlVwl64RBsfgn_8Fu7Y \
  TELEGRAM_CHAT_ID=7809584261 \
  SYMBOL=BTC-USDT \
  LEVERAGE=40 \
  RISK_PERCENT=10 \
  TP_SL_MODE=pinescript \
  AUTO_ENTRY=true \
  ORDER_TYPE=MARKET

# 5. Deploy
echo "🚀 Deploying ke Railway..."
railway up

echo "✅ Selesai! Cek dashboard Railway untuk mendapatkan URL public Anda."
