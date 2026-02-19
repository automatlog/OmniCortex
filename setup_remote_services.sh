#!/bin/bash
# Setup Remote Services for OmniCortex
# Run this on the remote server as root

PROJECT_DIR="/workspace"
VENV_DIR="${PROJECT_DIR}/.venv"
NODE_BIN=$(which node 2>/dev/null || echo "/root/.nvm/versions/node/v22/bin/node")

echo "🔧 Configuring OmniCortex Services in ${PROJECT_DIR}..."

# 1. vLLM Service
echo " -> Creating omni-vllm.service..."
cat > /etc/systemd/system/omni-vllm.service << EOF
[Unit]
Description=OmniCortex vLLM Service
After=network.target

[Service]
Type=simple
WorkingDirectory=${PROJECT_DIR}
Environment=PATH=${VENV_DIR}/bin:/usr/local/bin:/usr/bin:/bin
Environment=VIRTUAL_ENV=${VENV_DIR}
Environment=VLLM_USE_UVLOOP=0
ExecStart=${VENV_DIR}/bin/python3 -m vllm.entrypoints.openai.api_server \\
    --model meta-llama/Llama-3.1-8B-Instruct \\
    --host 0.0.0.0 --port 8080 \\
    --dtype auto --max-model-len 8192 \\
    --gpu-memory-utilization 0.45 \\
    --max-num-seqs 100 \\
    --trust-remote-code \\
    --disable-log-requests
Restart=on-failure
RestartSec=10
StandardOutput=append:${PROJECT_DIR}/storage/logs/vllm_server.log
StandardError=append:${PROJECT_DIR}/storage/logs/vllm_server.log

[Install]
WantedBy=multi-user.target
EOF

# 2. API Service
echo " -> Creating omni-api.service..."
cat > /etc/systemd/system/omni-api.service << EOF
[Unit]
Description=OmniCortex API Service
After=network.target

[Service]
Type=simple
WorkingDirectory=${PROJECT_DIR}
Environment=PATH=${VENV_DIR}/bin:/usr/local/bin:/usr/bin:/bin
Environment=VIRTUAL_ENV=${VENV_DIR}
ExecStart=${VENV_DIR}/bin/uvicorn api:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5
StandardOutput=append:${PROJECT_DIR}/storage/logs/api_server.log
StandardError=append:${PROJECT_DIR}/storage/logs/api_server.log

[Install]
WantedBy=multi-user.target
EOF

# 3. Admin Service
echo " -> Creating omni-admin.service..."
cat > /etc/systemd/system/omni-admin.service << EOF
[Unit]
Description=OmniCortex Admin Service
After=network.target

[Service]
Type=simple
WorkingDirectory=${PROJECT_DIR}/admin
ExecStart=${NODE_BIN} node_modules/.bin/next dev -H 0.0.0.0 -p 3000
Restart=on-failure
RestartSec=10
StandardOutput=append:${PROJECT_DIR}/storage/logs/admin_ui.log
StandardError=append:${PROJECT_DIR}/storage/logs/admin_ui.log

[Install]
WantedBy=multi-user.target
EOF

# 4. Nginx Configuration
echo " -> Configuring Nginx..."
cat > /etc/nginx/sites-available/omnicortex << 'NGINX_CONF'
upstream admin_upstream { server 127.0.0.1:3000; }
upstream api_upstream   { server 127.0.0.1:8000; }
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

    # Backend endpoints (Webhooks, etc)
    location ~ ^/(query|agents|documents|voice|health|metrics|stats|webhooks|auth|ws) {
        proxy_pass http://api_upstream;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # Voice WebSocket
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

    # vLLM
    location /vllm/ {
        proxy_pass http://vllm_upstream/;
    }

    # Admin Dashboard
    location / {
        proxy_pass http://admin_upstream;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
NGINX_CONF

# Activate Services
ln -sf /etc/nginx/sites-available/omnicortex /etc/nginx/sites-enabled/omnicortex
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx

echo "🚀 Reloading Systemd and Starting Services..."
mkdir -p ${PROJECT_DIR}/storage/logs
systemctl daemon-reload
systemctl enable --now omni-vllm
systemctl enable --now omni-api
systemctl enable --now omni-admin

echo "✅ Deployment Complete!"
