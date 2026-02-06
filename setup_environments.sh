#!/bin/bash
set -e

echo "🚀 Starting Full Environment Setup (Dual-Env Strategy)..."
cd /workspace/OmniCortex

# ==========================================
# 1. Main Environment (vLLM, API, Streamlit)
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
uv pip install accelerate streamlit audio-recorder-streamlit elevenlabs hf_transfer langchain langchain-community langchain-openai psycopg2-binary sqlalchemy pgvector

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
echo "🌙 Installing PyTorch Nightly (cu126)..."
uv pip install --pre torch torchvision torchaudio --index-url https://download.pytorch.org/whl/nightly/cu126

# Install Moshi
echo "🗣️ Installing Moshi..."
uv pip install moshi

echo "✅ Moshi Environment Ready!"
deactivate

echo "=================================================="
echo "🎉 SETUP COMPLETE!"
echo "=================================================="
echo "Usage Instructions:"
echo ""
echo "🔹 For MAIN APP (Streamlit/vLLM):"
echo "   source .venv/bin/activate"
echo "   uv run streamlit run main.py ..."
echo ""
echo "🔹 For MOSHI (PersonaPlex):"
echo "   source .moshi-venv/bin/activate"
echo "   python -m moshi.server ..."
echo "=================================================="
