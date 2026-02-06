#!/bin/bash
set -e

# 1. Install System Dependencies
echo "📦 Installing libopus-dev..."
apt-get update && apt-get install -y libopus-dev

# 2. Install Python Dependencies
echo "🐍 Installing moshi and pytorch..."
pip install moshi
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# 3. Setup Environment
export HF_TOKEN="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"

# 4. Launch Server
echo "🚀 Launching PersonaPlex (Moshi) on port 8998..."
# Create temp SSL dir
SSL_DIR=$(mktemp -d)
echo "Generated SSL dir: $SSL_DIR"

# Launch in background with PM2 for persistence
pm2 start "python -m moshi.server --ssl '$SSL_DIR' --port 8998" --name personaplex
pm2 save
pm2 logs personaplex
