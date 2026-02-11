#!/bin/bash
set -e

echo "🚀 Starting Full Environment Setup (Dual-Env Strategy)..."
cd /workspace/OmniCortex

# ==========================================
# 1. Main Environment (vLLM, API, Next.js)
# ==========================================
echo "--------------------------------------------------"
echo "HARD RESET: Setting up Main Environment (.venv)..."
echo "--------------------------------------------------"
rm -rf .venv

# Create venv
uv venv .venv --python 3.12 --seed
source .venv/bin/activate

# Install STABLE Torch (Required for vLLM & Transformers compatibility)
# Using generic 2.4.0 to match vLLM 0.6.3 requirements
echo "⬇️ Installing PyTorch Stable (cu121)..."
uv pip install torch==2.4.0 torchvision==0.19.0 torchaudio==2.4.0 --index-url https://download.pytorch.org/whl/cu121

# Install vLLM
echo "🧠 Installing vLLM..."
uv pip install vllm==0.6.3

# Install App Dependencies
echo "📦 Installing App Dependencies..."
uv pip install transformers==4.46.0 sentence-transformers==3.2.1
uv pip install accelerate hf_transfer langchain langchain-community langchain-openai psycopg2-binary sqlalchemy pgvector fastapi uvicorn python-multipart clickhouse-connect psutil requests

echo "✅ Main Environment Ready!"
deactivate

# ==========================================
# 2. Moshi Environment (PersonaPlex)
# ==========================================
echo "--------------------------------------------------"
echo "HARD RESET: Setting up Moshi Environment (.moshi-venv)..."
echo "--------------------------------------------------"
rm -rf .moshi-venv

# Create venv
uv venv .moshi-venv --python 3.12 --seed
source .moshi-venv/bin/activate

# Install NIGHTLY Torch (Required for Blackwell GPU sm_120)
echo "🌙 Installing PyTorch (cu130 for Blackwell)..."
uv pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu130

# Install System Dependencies (Linux Only)
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    if ! dpkg -s libopus-dev >/dev/null 2>&1; then
        echo "🔧 Installing libopus-dev (Required for Moshi)..."
        if [ "$EUID" -ne 0 ]; then
             echo "⚠️  Please run 'sudo apt-get install libopus-dev' manually or run this script as root."
        else
             apt-get update && apt-get install -y libopus-dev
        fi
    else
        echo "✅ libopus-dev is already installed."
    fi
fi

# Clone PersonaPlex (Requested by user)
echo "📥 Cloning PersonaPlex..."
git clone https://github.com/NVIDIA/personaplex.git || echo "Repo might already exist"

# Export Hugging Face Token for Model Download
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
    if [ -n "$HUGGING_FACE_HUB_TOKEN" ]; then
        export HF_TOKEN="$HUGGING_FACE_HUB_TOKEN"
        echo "🔑 HF_TOKEN exported for model download."
    else
        echo "⚠️  HUGGING_FACE_HUB_TOKEN not found in .env. Model download might fail."
    fi
fi

# Install Moshi
echo "🗣️ Installing Moshi..."
uv pip install moshi

echo "✅ Moshi Environment Ready!"
deactivate

# ==========================================
# 3. Admin UI (Next.js)
# ==========================================
echo "--------------------------------------------------"
echo "Setting up Admin Dashboard (admin/)..."
echo "--------------------------------------------------"
if [ -d "admin" ]; then
    cd admin
    if command -v npm &> /dev/null; then
        echo "📦 Installing Node.js dependencies..."
        npm install
    else
        echo "⚠️  npm not found. Skipping Admin setup."
        echo "   Please install Node.js and run 'npm install' in admin/ manually."
    fi
    cd ..
else
    echo "⚠️  admin/ directory not found. Skipping."
fi


echo "=================================================="
echo "🎉 SETUP COMPLETE!"
echo "=================================================="
echo "Usage Instructions:"
echo ""
echo "🔹 For PROCESS MANAGER (Recommended):"
echo "   source .venv/bin/activate"
echo "   python scripts/service_manager.py monitor"
echo ""
echo "🔹 For MAIN APP (Manual):"
echo "   source .venv/bin/activate"
echo "   uv run uvicorn api:app --host 0.0.0.0 --port 8000"
echo ""
echo "🔹 For MOSHI (Manual):"
echo "   source .moshi-venv/bin/activate"
echo "   python -m moshi.server ..."
echo "=================================================="
