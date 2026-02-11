#!/bin/bash
set -e  # Exit on error

echo "🚀 Starting OmniCortex Deployment Script (RunPod)..."

# Set non-interactive for apt
export DEBIAN_FRONTEND=noninteractive

# 1. Update system & Unzip
echo "📦 Updating system and unzipping project..."
apt-get update && apt-get install -y unzip curl git sudo tmux nano htop wget gnupg2 lsb-release
cd /workspace
# Check if zip exists, if so unzip
if [ -f "OmniCortex.zip" ]; then
    unzip -o OmniCortex.zip -d OmniCortex
fi
cd OmniCortex

# Check GPU
echo "🖥️ GPU Info:"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || echo "⚠️ No GPU found or nvidia-smi failed"

# 2. Add PostgreSQL 18 repository & install
echo "🐘 Setting up PostgreSQL 18..."
sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'
curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /etc/apt/trusted.gpg.d/postgresql.gpg
apt-get update -y && apt-get install -y postgresql-18 postgresql-contrib-18 postgresql-18-pgvector

service postgresql start

# Database Setup
echo "🗄️ Configuring Database..."
sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'postgresdb';"
sudo -u postgres psql -c "CREATE DATABASE omnicortex;" || echo "Database omnicortex might already exist"
sudo -u postgres psql -d omnicortex -c "CREATE EXTENSION IF NOT EXISTS vector;"
sudo -u postgres psql -d omnicortex -c "\dx"

# 3. Node.js via nvm
echo "🟢 Installing Node.js..."
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
nvm install 22
nvm use 22

# 4. Install nginx
echo "🔧 Installing Nginx..."
apt-get install -y nginx

# 5. Install uv & Python Environment
echo "🐍 Setting up Python environment..."
pip install uv
export PATH="/root/.local/bin:$PATH"

cd /workspace/OmniCortex
chmod -R 755 /workspace/OmniCortex

# Run the unified environment setup script
echo "📦 Running environment setup..."
bash setup_environments.sh

# 6. Copy production .env
if [ -f ".env.production" ]; then
    echo "📋 Using .env.production..."
    cp .env.production .env
fi

# ==========================================
# 7. Create systemd service units
# ==========================================
echo "⚙️ Creating systemd service units..."

# --- vLLM Service ---
cat > /etc/systemd/system/omni-vllm.service << 'EOF'
[Unit]
Description=OmniCortex vLLM Server
After=network.target

[Service]
Type=simple
WorkingDirectory=/workspace/OmniCortex
Environment=PATH=/workspace/OmniCortex/.venv/bin:/usr/local/bin:/usr/bin:/bin
Environment=VIRTUAL_ENV=/workspace/OmniCortex/.venv
Environment=VLLM_USE_UVLOOP=0
ExecStart=/workspace/OmniCortex/.venv/bin/python -m vllm.entrypoints.openai.api_server \
    --model nvidia/Llama-3.1-8B-Instruct-NVFP4 \
    --host 0.0.0.0 \
    --port 8080 \
    --dtype auto \
    --max-model-len 8192 \
    --gpu-memory-utilization 0.45 \
    --max-num-seqs 100 \
    --disable-log-requests
Restart=on-failure
RestartSec=10
StandardOutput=append:/workspace/OmniCortex/storage/logs/vllm_server.log
StandardError=append:/workspace/OmniCortex/storage/logs/vllm_server.log

[Install]
WantedBy=multi-user.target
EOF

# --- Moshi Service ---
cat > /etc/systemd/system/omni-moshi.service << 'EOF'
[Unit]
Description=OmniCortex Moshi Voice Server
After=network.target

[Service]
Type=simple
WorkingDirectory=/workspace/OmniCortex
Environment=PATH=/workspace/OmniCortex/.moshi-venv/bin:/usr/local/bin:/usr/bin:/bin
Environment=VIRTUAL_ENV=/workspace/OmniCortex/.moshi-venv
ExecStart=/workspace/OmniCortex/.moshi-venv/bin/python -m moshi.server --port 8998
Restart=on-failure
RestartSec=10
StandardOutput=append:/workspace/OmniCortex/storage/logs/moshi_server.log
StandardError=append:/workspace/OmniCortex/storage/logs/moshi_server.log

[Install]
WantedBy=multi-user.target
EOF

# --- FastAPI Service ---
cat > /etc/systemd/system/omni-api.service << 'EOF'
[Unit]
Description=OmniCortex FastAPI Backend
After=network.target postgresql.service

[Service]
Type=simple
WorkingDirectory=/workspace/OmniCortex
Environment=PATH=/workspace/OmniCortex/.venv/bin:/usr/local/bin:/usr/bin:/bin
Environment=VIRTUAL_ENV=/workspace/OmniCortex/.venv
ExecStart=/workspace/OmniCortex/.venv/bin/uvicorn api:app --host 0.0.0.0 --port 8000 --workers 4
Restart=on-failure
RestartSec=5
StandardOutput=append:/workspace/OmniCortex/storage/logs/api_server.log
StandardError=append:/workspace/OmniCortex/storage/logs/api_server.log

[Install]
WantedBy=multi-user.target
EOF

# --- Admin (Next.js) Service ---
cat > /etc/systemd/system/omni-admin.service << 'EOF'
[Unit]
Description=OmniCortex Admin Dashboard
After=network.target

[Service]
Type=simple
WorkingDirectory=/workspace/OmniCortex/admin
ExecStart=/root/.nvm/versions/node/v22/bin/node node_modules/.bin/next start -H 0.0.0.0 -p 3000
Restart=on-failure
RestartSec=10
StandardOutput=append:/workspace/OmniCortex/storage/logs/admin_ui.log
StandardError=append:/workspace/OmniCortex/storage/logs/admin_ui.log

[Install]
WantedBy=multi-user.target
EOF

# ==========================================
# 8. Configure Nginx
# ==========================================
echo "🌐 Configuring Nginx reverse proxy..."

cat > /etc/nginx/sites-available/omnicortex << 'NGINX_CONF'
upstream admin_upstream {
    server 127.0.0.1:3000;
}

upstream api_upstream {
    server 127.0.0.1:8000;
}

upstream moshi_upstream {
    server 127.0.0.1:8998;
}

upstream vllm_upstream {
    server 127.0.0.1:8080;
}

server {
    listen 80 default_server;
    server_name _;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # Increase timeouts for LLM responses
    proxy_connect_timeout 300;
    proxy_send_timeout 300;
    proxy_read_timeout 300;
    send_timeout 300;

    # Max upload size (for document uploads)
    client_max_body_size 100M;

    # API Backend
    location /api/ {
        proxy_pass http://api_upstream;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Backend endpoints without /api/ prefix
    location ~ ^/(query|agents|documents|voice|health|metrics|stats|webhooks) {
        proxy_pass http://api_upstream;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WhatsApp webhook
    location /api/v1/whatsapp/ {
        proxy_pass http://api_upstream;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Moshi WebSocket (voice AI)
    location /voice/ws {
        proxy_pass http://moshi_upstream;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 3600;
        proxy_send_timeout 3600;
    }

    # Moshi API
    location /voice/api/ {
        proxy_pass http://moshi_upstream/api/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 3600;
        proxy_send_timeout 3600;
    }

    # Prometheus metrics (internal only in production)
    location /metrics {
        proxy_pass http://api_upstream;
        # Uncomment below to restrict access:
        # allow 127.0.0.1;
        # deny all;
    }

    # vLLM health (internal only)
    location /vllm/ {
        proxy_pass http://vllm_upstream/;
        # allow 127.0.0.1;
        # deny all;
    }

    # Admin Dashboard (default — catch-all)
    location / {
        proxy_pass http://admin_upstream;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket support for Next.js HMR (dev) / live updates
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
NGINX_CONF

# Enable the site
ln -sf /etc/nginx/sites-available/omnicortex /etc/nginx/sites-enabled/omnicortex
rm -f /etc/nginx/sites-enabled/default

# Test nginx config
nginx -t

# ==========================================
# 9. Create logs directory & start services
# ==========================================
echo "📁 Ensuring storage directories exist..."
mkdir -p /workspace/OmniCortex/storage/logs
mkdir -p /workspace/OmniCortex/storage/pids

echo "🚀 Starting all services..."
systemctl daemon-reload

# Start services in order
systemctl enable --now omni-vllm
echo "⏳ Waiting for vLLM to load model (this may take 1-2 minutes)..."
sleep 30

systemctl enable --now omni-moshi
sleep 10

systemctl enable --now omni-api
sleep 5

systemctl enable --now omni-admin
sleep 3

# Restart nginx
systemctl enable --now nginx
systemctl restart nginx

echo ""
echo "=================================================="
echo "🎉 DEPLOYMENT COMPLETE!"
echo "=================================================="
echo ""
echo "Services:"
echo " - Nginx:     http://localhost (reverse proxy)"
echo " - FastAPI:   http://localhost:8000 (proxied via /api/)"
echo " - Admin:     http://localhost:3000 (proxied via /)"
echo " - vLLM:      http://localhost:8080 (internal)"
echo " - Moshi:     http://localhost:8998 (proxied via /voice/)"
echo ""
echo "Check status:"
echo "  systemctl status omni-vllm omni-moshi omni-api omni-admin nginx"
echo ""
echo "View logs:"
echo "  tail -f /workspace/OmniCortex/storage/logs/*.log"
echo "=================================================="
