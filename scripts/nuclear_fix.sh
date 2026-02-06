#!/bin/bash
set -e

echo "☢️ STARTING NUCLEAR FIX..."

# 1. FIX DATABASE PASSWORD
echo "🔧 Resetting DB Password..."
service postgresql start || true
# Run as postgres user to reset password
su - postgres -c "psql -c \"ALTER USER postgres PASSWORD 'postgredb';\""
echo "✅ DB Password reset to 'postgredb'"

# 2. FIX PYTHON ENVIRONMENT
echo "🐍 Repairing Python Environment..."
source /workspace/OmniCortex/.venv/bin/activate

# Force uninstall everything relevant (twice to clear ghosts)
echo "🗑️ Uninstalling broken packages..."
pip uninstall -y torch torchvision torchaudio vllm transformers accelerate
pip uninstall -y torch torchvision torchaudio vllm transformers accelerate

# Install Torch STABLE (No Cache to avoid bad wheels)
echo "⬇️ Installing Torch 2.4.0 (Stable)..."
pip install --no-cache-dir torch==2.4.0 torchvision==0.19.0 torchaudio==2.4.0 --index-url https://download.pytorch.org/whl/cu121

# Install App Deps
echo "📦 Installing App Deps..."
pip install vllm==0.6.2 transformers==4.46.0 accelerate streamlit audio-recorder-streamlit elevenlabs hf_transfer

echo "✅ DONE! Try running Streamlit now."
