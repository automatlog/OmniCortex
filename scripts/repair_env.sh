#!/bin/bash
set -e

echo "🔧 Starting Environment Repair..."

# Deactivate if active (ignore error if not)
deactivate 2>/dev/null || true

cd /workspace/OmniCortex

# 1. Wipe Config
echo "🧹 Wiping existing venv..."
rm -rf .venv

# 2. Recreate
echo "🐍 Creating fresh venv..."
uv venv --python 3.12 --seed
source .venv/bin/activate

# 3. Install PyTorch STABLE (Pinned)
# Using 2.4.0 to match vLLM requirements commonly
echo "⬇️ Installing PyTorch Stable..."
uv pip install torch==2.4.0 torchvision==0.19.0 torchaudio==2.4.0 --index-url https://download.pytorch.org/whl/cu121

# 4. Install vLLM (Pinned)
echo "🧠 Installing vLLM..."
uv pip install vllm==0.6.3

# 5. Install Other Deps
echo "📦 Installing Dependencies..."
uv pip install transformers==4.46.0 sentence-transformers==3.2.1
uv pip install accelerate streamlit audio-recorder-streamlit hf_transfer

echo "✅ Repair Complete! Try running Streamlit now."
