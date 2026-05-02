#!/bin/bash

echo "🚀 Memulai setup Railway..."

# 1. Install Railway CLI jika belum ada
if ! command -v railway &> /dev/null
then
    echo "📦 Installing Railway CLI via Homebrew..."
    brew install railway
fi

# 2. Login (Ini akan membuka browser)
echo "🔑 Silahkan login ke Railway di browser yang akan terbuka..."
railway login

# 3. Inisialisasi Project
echo "📁 Membuat project baru di Railway..."
railway init

# 4. Set Variables dari .env
echo "⚙️ Mengatur environment variables..."
railway variables set \
  BINGX_API_KEY=FS800S6GYrielJGqKlRa1XgWOPmZeZRCJjtlDiouVnSf5yQrwhLJ1Bl9P51islnEBbgAxqoqeqzVP5Fw9Fw \
  BINGX_API_SECRET=p8BmfLQev4mzlzXjOORSlzbVKmgcC7fOgY72T7a62KFb5oWZwdg2jPJecori0E00rQCYNSBvWg3YvFxY612IQ \
  WEBHOOK_SECRET=Tr4d3BotBingX@2025!xK9 \
  SYMBOL=BTC-USDT \
  LEVERAGE=10 \
  RISK_PERCENT=1.5 \
  TP_SL_MODE=pinescript \
  ORDER_TYPE=MARKET

# 5. Deploy
echo "🚀 Deploying ke Railway..."
railway up

echo "✅ Selesai! Cek dashboard Railway untuk mendapatkan URL public Anda."
