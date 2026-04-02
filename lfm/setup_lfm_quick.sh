#!/bin/bash

# Quick LFM Virtual Environment Setup
# Run this on the server: bash ~/OmniCortex/lfm/setup_lfm_quick.sh

set -e

cd ~/OmniCortex

echo "Creating .lfm-venv..."
python3 -m venv .lfm-venv

echo "Activating environment..."
source .lfm-venv/bin/activate

echo "Upgrading pip..."
pip install --upgrade pip setuptools wheel

echo "Installing PyTorch with CUDA 12.1..."
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

echo "Installing LFM requirements..."
pip install -r lfm/requirements_lfm.txt

echo ""
echo "========== SETUP COMPLETE =========="
echo ""
echo "Activate with: source ~/.lfm-venv/bin/activate"
echo ""
echo "Start LFM server:"
echo "source ~/.lfm-venv/bin/activate && python lfm/serve_lfm.py --host 0.0.0.0 --port 8012 --device cuda --preload"
