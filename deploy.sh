#!/bin/bash
# OmniCortex One-Click Deploy Script
set -e

echo "🚀 Starting OmniCortex Deployment..."

# 1. Environment Setup
if [ ! -d ".venv" ] || [ ! -d ".moshi-venv" ]; then
    echo "📦 Setting up environments..."
    ./setup_environments.sh
else
    echo "✅ Environments already exist."
fi

# 2. vLLM install + runtime checks (commands from manual session)
echo "🔍 Running runtime checks and vLLM install verification..."
source .venv/bin/activate

echo "Checking toolchain..."
uv --version || true
python --version
nvidia-smi || true

echo "Checking Python packages in .venv..."
python -c "import torch; print(torch.__version__)" || true
python -c "import vllm,sys; print(vllm.__version__)" || true

if ! python -c "import vllm" >/dev/null 2>&1; then
    echo "📦 vLLM missing in .venv; installing required packages..."
    python -m pip install --upgrade pip
    python -m pip install torch==2.4.0 torchvision==0.19.0 torchaudio==2.4.0 --index-url https://download.pytorch.org/whl/cu121
    python -m pip install vllm==0.6.3
fi

# Export HF token for model pulls if token exists in .env
if [ -n "${HUGGING_FACE_HUB_TOKEN}" ] && [ -z "${HF_TOKEN}" ]; then
    export HF_TOKEN="${HUGGING_FACE_HUB_TOKEN}"
fi

# Ensure vLLM model defaults to meta-llama gated repo
export VLLM_MODEL="${VLLM_MODEL:-meta-llama/Llama-3.1-8B-Instruct}"

# 3. Service Management
echo "🔄 Starting Service Manager..."

# Check if already running
if pgrep -f "service_manager.py monitor" > /dev/null; then
    echo "✅ Service Manager is already running."
    python scripts/service_manager.py status
else
    # Start in background via nohup if on server, or direct execution
    echo "▶️ Starting services (vLLM, Moshi, API, Admin)..."
    python scripts/service_manager.py monitor
fi

echo ""
echo "=================================================="
echo "🎉 DEPLOYMENT ACTIVE"
echo "=================================================="
echo "Services:"
echo " - Frontend:    http://localhost:3000"
echo " - Backend:     http://localhost:8000"
echo " - Voice AI:    http://localhost:8998"
echo " - vLLM:        http://localhost:8080"
echo ""
echo "To view logs:"
echo "   tail -f storage/logs/service_manager.log"
echo "=================================================="
