#!/bin/bash
# OmniCortex One-Click Deploy Script (Systemd + Nginx)
set -e

# Auto-detect project directory
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "🚀 Starting OmniCortex Deployment at ${PROJECT_DIR}..."

# ==========================================
# 1. Environment Setup
# ==========================================
if [ ! -d "${PROJECT_DIR}/.venv" ] || [ ! -d "${PROJECT_DIR}/.moshi-venv" ]; then
    echo "📦 Setting up environments..."
    bash "${PROJECT_DIR}/setup_environments.sh"
else
    echo "✅ Environments already exist."
fi

# ==========================================
# 2. Runtime Checks
# ==========================================
echo "🔍 Running runtime checks..."
source "${PROJECT_DIR}/.venv/bin/activate"
echo "  Python: $(python --version)"
echo "  Torch:  $(python -c 'import torch; print(torch.__version__)' 2>/dev/null || echo 'not installed')"
echo "  vLLM:   $(python -c 'import vllm; print(vllm.__version__)' 2>/dev/null || echo 'not installed')"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || echo "  ⚠️ No GPU detected"
deactivate

# Export HF token
if [ -f "${PROJECT_DIR}/.env" ]; then
    export $(grep -v '^#' "${PROJECT_DIR}/.env" | grep HUGGING_FACE_HUB_TOKEN | xargs)
fi
if [ -n "${HUGGING_FACE_HUB_TOKEN}" ] && [ -z "${HF_TOKEN}" ]; then
    export HF_TOKEN="${HUGGING_FACE_HUB_TOKEN}"
fi

# ==========================================
# 4. Install & Configure Nginx
# ==========================================
echo "🌐 Setting up Nginx..."
apt-get install -y nginx 2>/dev/null || true

cat > /etc/nginx/sites-available/omnicortex << 'NGINX_CONF'
upstream api_upstream   { server 127.0.0.1:8000; }
upstream moshi_upstream { server 127.0.0.1:8998; }
upstream vllm_upstream  { server 127.0.0.1:8080; }

server {
    listen 80 default_server;
    server_name _;

    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;

    proxy_connect_timeout 300;
    proxy_send_timeout 300;
    proxy_read_timeout 300;
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
    location ~ ^/(query|agents|documents|voice|health|metrics|stats|webhooks|auth|ws) {
        proxy_pass http://api_upstream;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # Voice WebSocket (proxied through api.py for RAG context)
    location /voice/ws {
        proxy_pass http://api_upstream;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 3600;
        proxy_send_timeout 3600;
    }

    # Moshi direct API
    location /voice/api/ {
        proxy_pass http://moshi_upstream/api/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 3600;
        proxy_send_timeout 3600;
    }

    # vLLM (internal)
    location /vllm/ {
        proxy_pass http://vllm_upstream/;
    }

    # API docs / fallback
    location / {
        proxy_pass http://api_upstream;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
NGINX_CONF

ln -sf /etc/nginx/sites-available/omnicortex /etc/nginx/sites-enabled/omnicortex
rm -f /etc/nginx/sites-enabled/default
nginx -t && echo "✅ Nginx config valid"

# ==========================================
# 5. Create Systemd Service Units
# ==========================================
echo "⚙️ Creating systemd services..."
mkdir -p "${PROJECT_DIR}/storage/logs"

# --- vLLM ---
cat > /etc/systemd/system/omni-vllm.service << EOF
[Unit]
Description=OmniCortex vLLM Server
After=network.target

[Service]
Type=simple
WorkingDirectory=${PROJECT_DIR}
Environment=PATH=${PROJECT_DIR}/.venv/bin:/usr/local/bin:/usr/bin:/bin
Environment=VIRTUAL_ENV=${PROJECT_DIR}/.venv
Environment=HF_TOKEN=${HF_TOKEN}
Environment=VLLM_USE_UVLOOP=0
ExecStart=${PROJECT_DIR}/.venv/bin/python -m vllm.entrypoints.openai.api_server \
    --model meta-llama/Llama-3.1-8B-Instruct \
    --host 0.0.0.0 --port 8080 \
    --dtype auto --max-model-len 8192 \
    --gpu-memory-utilization 0.45 \
    --max-num-seqs 100 --disable-log-requests
Restart=on-failure
RestartSec=10
StandardOutput=append:${PROJECT_DIR}/storage/logs/vllm_server.log
StandardError=append:${PROJECT_DIR}/storage/logs/vllm_server.log

[Install]
WantedBy=multi-user.target
EOF

# --- Moshi ---
cat > /etc/systemd/system/omni-moshi.service << EOF
[Unit]
Description=OmniCortex Moshi Voice Server
After=network.target

[Service]
Type=simple
WorkingDirectory=${PROJECT_DIR}
Environment=PATH=${PROJECT_DIR}/.moshi-venv/bin:/usr/local/bin:/usr/bin:/bin
Environment=VIRTUAL_ENV=${PROJECT_DIR}/.moshi-venv
Environment=HF_TOKEN=${HF_TOKEN}
ExecStart=${PROJECT_DIR}/.moshi-venv/bin/python -m moshi.server --port 8998
Restart=on-failure
RestartSec=10
StandardOutput=append:${PROJECT_DIR}/storage/logs/moshi_server.log
StandardError=append:${PROJECT_DIR}/storage/logs/moshi_server.log

[Install]
WantedBy=multi-user.target
EOF

# --- FastAPI ---
cat > /etc/systemd/system/omni-api.service << EOF
[Unit]
Description=OmniCortex FastAPI Backend
After=network.target

[Service]
Type=simple
WorkingDirectory=${PROJECT_DIR}
Environment=PATH=${PROJECT_DIR}/.venv/bin:/usr/local/bin:/usr/bin:/bin
Environment=VIRTUAL_ENV=${PROJECT_DIR}/.venv
ExecStart=${PROJECT_DIR}/.venv/bin/uvicorn api:app --host 0.0.0.0 --port 8000 --workers 4
Restart=on-failure
RestartSec=5
StandardOutput=append:${PROJECT_DIR}/storage/logs/api_server.log
StandardError=append:${PROJECT_DIR}/storage/logs/api_server.log

[Install]
WantedBy=multi-user.target
EOF

# ==========================================
# 6. Start All Services
# ==========================================
echo "🚀 Starting all services..."
systemctl daemon-reload

systemctl enable --now omni-vllm
echo "⏳ Waiting for vLLM to load model (1-2 min)..."
sleep 30

systemctl enable --now omni-moshi
sleep 10

systemctl enable --now omni-api
sleep 5

systemctl enable --now nginx
systemctl restart nginx

echo ""
echo "=================================================="
echo "🎉 DEPLOYMENT ACTIVE"
echo "=================================================="
echo "Services:"
echo " - Nginx:     http://localhost (reverse proxy)"
echo " - Backend:   http://localhost:8000"
echo " - Voice AI:  http://localhost:8998"
echo " - vLLM:      http://localhost:8080"
echo ""
echo "Status:  systemctl status omni-vllm omni-moshi omni-api nginx"
echo "Logs:    tail -f ${PROJECT_DIR}/storage/logs/*.log"
echo "=================================================="
