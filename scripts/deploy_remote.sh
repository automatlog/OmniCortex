#!/bin/bash
set -e  # Exit on error

echo "🚀 Starting Deployment Script..."

# Set non-interactive for apt
export DEBIAN_FRONTEND=noninteractive

# 1. Update system & Unzip
echo "📦 Updating system and unzipping project..."
apt-get update && apt-get install -y unzip
cd /workspace
# Check if zip exists, if so unzip
if [ -f "OmniCortex.zip" ]; then
    unzip -o OmniCortex.zip -d OmniCortex
fi
cd OmniCortex

# Check GPU
nvidia-smi --query-gpu=name --format=csv,noheader || echo "⚠️ No GPU found or nvidia-smi failed"

# 2. Install basic tools
echo "🛠️ Installing basic tools..."
apt-get install -y curl git sudo tmux nano htop wget gnupg2 lsb-release

# 3. Add PostgreSQL 18 repository
echo "🐘 Setting up PostgreSQL 18..."
sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'
curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /etc/apt/trusted.gpg.d/postgresql.gpg
apt-get update -y && apt-get install -y postgresql-18 postgresql-contrib-18 postgresql-18-pgvector

service postgresql start

# 3.2 Database Setup
echo "🗄️ Configuring Database..."
sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'postgredb';"
sudo -u postgres psql -c "CREATE DATABASE omnicortex;" || echo "Database omnicortex might already exist"
sudo -u postgres psql -d omnicortex -c "CREATE EXTENSION IF NOT EXISTS vector;"
sudo -u postgres psql -d omnicortex -c "\dx"

# 4. Node.js
echo "🟢 Installing Node.js..."
cd /workspace/OmniCortex/admin
# Clean install nvm
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

nvm install 22
nvm use 22

# 5. Install global tools
echo "🔧 Installing PM2 and tools..."
npm install -g pm2
pip install uv
uv sync || echo "uv sync warning (continuing)"

# 7. Python Environment
echo "🐍 Setting up Python environment..."
cd /workspace/OmniCortex
export PATH="/root/.local/bin:$PATH"
uv venv --python 3.12 --seed
source .venv/bin/activate

chmod -R 755 /workspace/OmniCortex
uv pip install -e .

# 8. Install vLLM & Deps
echo "🧠 Installing vLLM and dependencies..."
uv pip install vllm transformers accelerate
apt-get install -y libopus-dev
uv pip install streamlit hf_transfer
uv pip install --upgrade transformers sentence-transformers

# Build Admin
echo "🏗️ Building Admin Dashboard..."
cd /workspace/OmniCortex/admin && npm install
npm run build

# 9. Start Services
echo "🚀 Starting Services found in PM2..."
cd /workspace/OmniCortex

# API
pm2 start .venv/bin/python3 --name omni-api -- -m uvicorn api:app --host 0.0.0.0 --port 8000 --workers 4

# Admin
cd /workspace/OmniCortex/admin
pm2 start npm --name omni-admin -- start -- -p 3000

# Save PM2
pm2 save
pm2 list

echo "✅ Deployment Script Completed!"
