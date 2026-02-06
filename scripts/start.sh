#!/bin/bash
# =============================================================================
# OmniCortex Deployment Script
# Supports: RunPod, AWS EC2, Azure VM (Ubuntu 22.04+ with NVIDIA GPU)
# =============================================================================
set -e  # Exit on error

echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║                    OmniCortex Deployment Script                       ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"

# =============================================================================
# 1. SYSTEM DEPENDENCIES
# =============================================================================
echo ""
echo ">>> 1. Installing System Dependencies..."
apt-get update -y
apt-get install -y curl git sudo tmux nano htop

# PostgreSQL with pgvector
if ! command -v psql &> /dev/null; then
    apt-get install -y postgresql postgresql-contrib
    apt-get install -y postgresql-16-pgvector || apt-get install -y postgresql-14-pgvector || true
fi

# Node.js & PM2 for process management
if ! command -v pm2 &> /dev/null; then
    echo ">>> Installing Node.js & PM2..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y nodejs
    npm install -g pm2
fi

# =============================================================================
# 2. DATABASE SETUP
# =============================================================================
echo ""
echo ">>> 2. Configuring PostgreSQL Database..."
service postgresql start || systemctl start postgresql || true

# Create DB user/db (idempotent)
sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'postgredb';" 2>/dev/null || true
sudo -u postgres psql -c "CREATE DATABASE omnicortex;" 2>/dev/null || true
sudo -u postgres psql -d omnicortex -c "CREATE EXTENSION IF NOT EXISTS vector;" 2>/dev/null || true
echo "✅ Database configured"

# =============================================================================
# 3. PYTHON ENVIRONMENT (UV)
# =============================================================================
echo ""
echo ">>> 3. Setting up Python Environment..."

# Install UV if missing
if ! command -v uv &> /dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="/root/.local/bin:$PATH"
fi

# Navigate to project directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"
echo "📁 Working directory: $PROJECT_DIR"

# Create/Recreate venv
echo ">>> Recreating .venv..."
rm -rf .venv
uv venv --python 3.12 --seed
source .venv/bin/activate

# =============================================================================
# 4. INSTALL DEPENDENCIES
# =============================================================================
echo ""
echo ">>> 4. Installing Python Dependencies..."
uv pip install -e .

# Install vLLM only on GPU systems
if command -v nvidia-smi &> /dev/null; then
    echo ">>> GPU detected! Installing vLLM..."
    uv pip install -U vllm transformers accelerate
    
    # Install PersonaPlex voice server
    echo ">>> Installing PersonaPlex voice server..."
    apt-get install -y libopus-dev
    
    # Clone PersonaPlex if not exists
    if [ ! -d "$PROJECT_DIR/personaplex" ]; then
        git clone https://github.com/NVIDIA/personaplex.git "$PROJECT_DIR/personaplex"
    fi
    
    # Install moshi from PersonaPlex
    uv pip install "$PROJECT_DIR/personaplex/moshi/."
else
    echo "⚠️  No GPU detected. Skipping vLLM and PersonaPlex."
fi

# =============================================================================
# 5. BUILD NEXT.JS ADMIN DASHBOARD
# =============================================================================
echo ""
echo ">>> 5. Building Next.js Admin Dashboard..."

cd "$PROJECT_DIR/admin"
npm install
npm run build
cd "$PROJECT_DIR"

# =============================================================================
# 6. START SERVICES WITH PM2
# =============================================================================
echo ""
echo ">>> 6. Starting Services with PM2..."

# Stop existing services
pm2 delete all 2>/dev/null || true

# --- API Server (FastAPI) ---
pm2 start .venv/bin/python3 --name omni-api -- -m uvicorn api:app --host 0.0.0.0 --port 8000 --workers 4

# --- Admin UI (Next.js) ---
cd "$PROJECT_DIR/admin"
pm2 start npm --name omni-admin -- start -- -p 3000
cd "$PROJECT_DIR"

# --- vLLM Server (Only if GPU available) ---
if command -v nvidia-smi &> /dev/null; then
    echo ">>> Starting vLLM server..."
    
    # NOTE: Meta Llama 3.1 is disabled (gated model, pending approval)
    # Once approved, uncomment below and change Nemotron to port 8081
    # pm2 start .venv/bin/python3 --name vllm-llama -- -m vllm.entrypoints.openai.api_server \
    #     --model meta-llama/Meta-Llama-3.1-8B-Instruct \
    #     --port 8080 \
    #     --host 0.0.0.0 \
    #     --trust-remote-code \
    #     --max-model-len 8192
    
    # Primary LLM: Nemotron (Port 8080)
    pm2 start .venv/bin/python3 --name vllm-nemotron -- -m vllm.entrypoints.openai.api_server \
        --model nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4 \
        --port 8080 \
        --host 0.0.0.0 \
        --trust-remote-code \
        --quantization fp8
    
    # --- PersonaPlex Voice Server (Port 8998) ---
    echo ">>> Starting PersonaPlex voice server..."
    SSL_DIR=$(mktemp -d)
    pm2 start .venv/bin/python3 --name personaplex -- -m moshi.server --ssl "$SSL_DIR" --port 8998
fi

# Save PM2 configuration
pm2 save

# =============================================================================
# 7. SUMMARY
# =============================================================================
echo ""
echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║                         DEPLOYMENT COMPLETE                           ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo ""
echo "🌐 Services Running:"
echo "   • API Server:      http://0.0.0.0:8000"
echo "   • Admin Dashboard: http://0.0.0.0:3000"
if command -v nvidia-smi &> /dev/null; then
echo "   • vLLM Nemotron:   http://0.0.0.0:8080/v1"
echo "   • PersonaPlex:     https://0.0.0.0:8998 (Voice)"
fi
echo ""
echo "📋 Useful Commands:"
echo "   pm2 status       # View running processes"
echo "   pm2 logs         # View all logs"
echo "   pm2 logs omni-api   # View API logs"
echo "   pm2 logs omni-admin # View Admin UI logs"
echo "   pm2 logs personaplex # View Voice logs"
echo "   pm2 restart all  # Restart all services"
echo "   pm2 monit        # Real-time monitoring"
echo ""
echo "✅ Done! Your OmniCortex instance is ready."
