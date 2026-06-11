#!/bin/bash
# Path ke direktori bot
BOT_DIR="/Users/mac/sinyalbingx"

# Path ke Python virtual environment
VENV_PYTHON="$BOT_DIR/venv/bin/python3"

# 0. Muat berkas .env untuk membaca PORT konfigurasi secara dinamis
if [ -f "$BOT_DIR/.env" ]; then
    # Ekspor variabel dari .env dengan mengabaikan komentar
    export $(grep -v '^#' "$BOT_DIR/.env" | xargs)
fi

# Gunakan PORT dari .env atau default ke 5000
TARGET_PORT=${PORT:-5000}

# 1. Pastikan Caffeinate jalan (Cegah Mac Sleep)
# Gunakan 'pgrep' untuk mencari proses caffeinate, lalu 'kill -9' jika ada.
# Jika tidak ada, 'grep' akan error, tapi '|| true' akan mencegah skrip berhenti.
pgrep -x caffeinate > /dev/null || $VENV_PYTHON -c "import os; os.system('caffeinate -dis &')"

# 2. Jalankan Bot Utama (Webhook)
cd $BOT_DIR
$VENV_PYTHON webhook_server.py > bot_run.log 2>&1 &

# 3. Jalankan Hunter Engine (Otonom) - DINONAKTIFKAN
# $VENV_PYTHON hunter_engine.py > hunter_run.log 2>&1 &

# 4. Jalankan Cloudflare Tunnel ke port yang sesuai
# Menggunakan path absolut untuk cloudflared
/opt/homebrew/bin/cloudflared tunnel --url http://127.0.0.1:$TARGET_PORT > bridge_tunnel.log 2>&1 &

# 5. Jalankan Hermes AI Chat Bot (DINONAKTIFKAN)
# $VENV_PYTHON hermes_ai_bot.py > hermes_bot.log 2>&1 &

echo "✅ Auto-Trader System Started (Bot on Port $TARGET_PORT, Tunnel, Anti-Sleep)"

