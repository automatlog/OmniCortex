#!/bin/bash
set -e

echo "🚀 Starting Full Environment Setup (Dual-Env Strategy)..."
cd "$(dirname "$0")"

# ==========================================
# Detect CUDA version from container
# ==========================================
CUDA_VERSION=$(nvcc --version 2>/dev/null | grep -oP 'V\K[0-9]+\.[0-9]+' || echo "unknown")
echo "🔍 Detected CUDA version: ${CUDA_VERSION}"

# Determine PyTorch index URL based on CUDA version
case "${CUDA_VERSION}" in
    13.0*) TORCH_INDEX="https://download.pytorch.org/whl/cu130" ;;
    12.8*) TORCH_INDEX="https://download.pytorch.org/whl/cu128" ;;
    12.6*) TORCH_INDEX="https://download.pytorch.org/whl/cu126" ;;
    12.4*) TORCH_INDEX="https://download.pytorch.org/whl/cu124" ;;
    12.1*) TORCH_INDEX="https://download.pytorch.org/whl/cu121" ;;
    *) TORCH_INDEX="https://download.pytorch.org/whl/cu130"
       echo "⚠️  Could not detect CUDA version, defaulting to cu130 (Blackwell)" ;;
esac
echo "📦 Using PyTorch index: ${TORCH_INDEX}"

# Check if PyTorch is already available in the system
SYSTEM_TORCH=$(python3 -c "import torch; print(torch.__version__)" 2>/dev/null || echo "")
if [ -n "$SYSTEM_TORCH" ]; then
    echo "✅ System PyTorch detected: ${SYSTEM_TORCH} — will use --system-site-packages"
    USE_SYSTEM_PACKAGES="--system-site-packages"
    VENV_SITE_PACKAGES_ARG=(--system-site-packages)
else
    echo "ℹ️  No system PyTorch found — will install from ${TORCH_INDEX}"
    USE_SYSTEM_PACKAGES=""
    VENV_SITE_PACKAGES_ARG=()
fi

# ==========================================
# 2. Moshi Voice Server (.moshi-venv — separate to avoid conflicts)
# ==========================================
echo "--------------------------------------------------"
echo "Setting up Moshi Environment (.moshi-venv)..."
echo "--------------------------------------------------"

if [ -d ".moshi-venv" ]; then
    echo "✅ .moshi-venv already exists, skipping creation"
else
    uv venv .moshi-venv --python 3.12 --seed "${VENV_SITE_PACKAGES_ARG[@]}"
    source .moshi-venv/bin/activate

    # Only install PyTorch if not inheriting from system
    if [ -z "$SYSTEM_TORCH" ]; then
        echo "⬇️ Installing PyTorch for Moshi (${TORCH_INDEX})..."
        uv pip install torch torchvision torchaudio --index-url "${TORCH_INDEX}"
    else
        echo "✅ Using system PyTorch ${SYSTEM_TORCH}"
    fi

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

    # Install Moshi from local package
    if [ -d "moshi" ]; then
        echo "🗣️ Installing Moshi from local moshi/ directory..."
        uv pip install moshi/.
        echo "✅ Moshi installed into .moshi-venv"
    else
        echo "⚠️  moshi/ directory not found. Skipping Moshi install."
    fi

    deactivate
fi

echo "=================================================="
echo "🎉 SETUP COMPLETE!"
echo "=================================================="
echo "Usage Instructions:"
echo ""
echo "🔹 For SERVICE MANAGER (Recommended):"
echo "   source .venv/bin/activate"
echo "   python scripts/service_manager.py monitor"
echo ""
echo "🔹 For MAIN APP (Manual):"
echo "   source .venv/bin/activate"
echo "   uv run uvicorn api:app --host 0.0.0.0 --port 8000"
echo ""
echo "🔹 For MOSHI (Manual):"
echo "   source .moshi-venv/bin/activate"
echo "   python -m moshi.server --port 8998"
echo "=================================================="
