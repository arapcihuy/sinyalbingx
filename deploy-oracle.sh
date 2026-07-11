#!/bin/bash
# Deploy sinyalbingx ke Oracle Cloud VM
# Usage: ./deploy-oracle.sh <IP_ADDRESS> <SSH_KEY_PATH>
# Contoh: ./deploy-oracle.sh 129.154.xx.xx ~/.ssh/oracle_key

set -e

IP="$1"
KEY="$2"
REMOTE_USER="ubuntu"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -z "$IP" ] || [ -z "$KEY" ]; then
    echo "Usage: $0 <VM_IP> <SSH_KEY_PATH>"
    echo "Contoh: $0 129.154.xx.xx ~/.ssh/oracle_key"
    exit 1
fi

SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
SSH="ssh $SSH_OPTS -i $KEY $REMOTE_USER@$IP"
SCP="scp $SSH_OPTS -i $KEY"

echo "🔧 [1/4] Setup Docker di VM..."
$SSH "bash -s" <<'REMOTE_SCRIPT'
    if ! command -v docker &>/dev/null; then
        sudo apt-get update -qq
        sudo apt-get install -y -qq docker.io docker-compose-v2
        sudo systemctl enable docker
        sudo systemctl start docker
        sudo usermod -aG docker ubuntu
        echo "✅ Docker installed"
    else
        echo "✅ Docker already installed"
    fi
    # Login to Docker Hub (optional, needed if image is private)
    # echo "$DOCKERHUB_PASSWORD" | docker login -u "$DOCKERHUB_USER" --password-stdin
REMOTE_SCRIPT

echo "📦 [2/4] Upload project..."
$SSH "rm -rf ~/sinyalbingx && mkdir -p ~/sinyalbingx"

# Upload all files
$SCP -r "$PROJECT_DIR"/* "$REMOTE_USER@$IP:~/sinyalbingx/" 2>/dev/null || \
    $SSH "bash -s" <<UPLOAD_SCRIPT
        cd ~/sinyalbingx
        # Fallback: upload file by file
UPLOAD_SCRIPT

# Make sure all .py files are uploaded
$SCP "$PROJECT_DIR"/*.py "$REMOTE_USER@$IP:~/sinyalbingx/" 2>/dev/null || true

echo "⚙️  [3/4] Build & start container..."
$SSH "cd ~/sinyalbingx && \
    if [ ! -f .env ]; then \
        cp .env.example .env && \
        echo '⚠️  .env belum dikonfigurasi! Edit: nano ~/sinyalbingx/.env'; \
    fi && \
    sudo docker compose down 2>/dev/null || true && \
    sudo docker compose up -d --build"

echo "🔍 [4/4] Verifikasi..."
$SSH "sleep 5 && sudo docker compose -f ~/sinyalbingx/docker-compose.yml logs --tail=20"

echo ""
echo "✅ Deploy selesai!"
echo "📋 Cek logs: ssh -i $KEY $REMOTE_USER@$IP 'sudo docker compose -f ~/sinyalbingx/docker-compose.yml logs -f'"
echo "📋 Edit env: ssh -i $KEY $REMOTE_USER@$IP 'nano ~/sinyalbingx/.env'"
echo "📋 Restart:  ssh -i $KEY $REMOTE_USER@$IP 'cd ~/sinyalbingx && sudo docker compose restart'"
