#!/bin/bash
# VPS Setup & Deployment Script for Oracle Cloud
# Target OS: Ubuntu / Debian

PROJECT_DIR="sinyalbingx"
PORT=5001

echo "🚀 Starting VPS Hardening & Deployment..."

# 1. Update & Install Dependencies
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv ufw iptables-persistent

# 2. Setup Virtual Environment
cd ~/$PROJECT_DIR
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 3. Open Firewall (Oracle Cloud Specific)
echo "🛡️ Opening Firewall Port $PORT..."
# Buka di OS level
sudo ufw allow $PORT/tcp
sudo ufw --force enable

# Force open via iptables (Oracle often overrides ufw)
sudo iptables -I INPUT -p tcp --dport $PORT -j ACCEPT
sudo iptables-save | sudo tee /etc/iptables/rules.v4

# 4. Create Systemd Services
echo "⚙️ Creating Systemd Services..."

# SERVICE 1: WEBHOOK (Passive)
sudo bash -c "cat > /etc/systemd/system/bingx-webhook.service <<EOF
[Unit]
Description=BingX Webhook Bridge
After=network.target

[Service]
User=$USER
WorkingDirectory=$HOME/$PROJECT_DIR
ExecStart=$HOME/$PROJECT_DIR/venv/bin/python3 webhook_server.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF"

# SERVICE 2: HUNTER (Active Otonom)
sudo bash -c "cat > /etc/systemd/system/bingx-hunter.service <<EOF
[Unit]
Description=BingX Hunter Otonom
After=network.target

[Service]
User=$USER
WorkingDirectory=$HOME/$PROJECT_DIR
ExecStart=$HOME/$PROJECT_DIR/venv/bin/python3 hunter_engine.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF"

# 5. Start Services
sudo systemctl daemon-reload
sudo systemctl enable bingx-webhook bingx-hunter
sudo systemctl restart bingx-webhook bingx-hunter

echo "✅ DUAL DEPLOYMENT SUCCESSFUL!"
echo "📊 Status Webhook: sudo systemctl status bingx-webhook"
echo "🎯 Status Hunter : sudo systemctl status bingx-hunter"
