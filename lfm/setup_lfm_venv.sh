#!/bin/bash

# Setup LFM Virtual Environment Script
# This script creates an isolated Python environment for the LFM server

set -e

echo "========================================"
echo "Setting up LFM Virtual Environment"
echo "========================================"

# Navigate to OmniCortex directory
cd ~/OmniCortex

# Create virtual environment
echo ""
echo "Creating virtual environment: .lfm-venv"
python3 -m venv .lfm-venv

# Activate virtual environment
echo "Activating virtual environment..."
source .lfm-venv/bin/activate

# Upgrade pip, setuptools, and wheel
echo ""
echo "Upgrading pip, setuptools, and wheel..."
pip install --upgrade pip setuptools wheel

# Install core dependencies
echo ""
echo "Installing core dependencies..."
pip install fastapi uvicorn python-multipart

# Install torch and torchaudio (CPU first, then CUDA if needed)
echo ""
echo "Installing PyTorch with CUDA 12.1 support..."
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# Install LiquiAI liquid-audio package
echo ""
echo "Installing liquid-audio package..."
pip install liquid-audio

# Install other dependencies
echo ""
echo "Installing additional dependencies..."
pip install numpy scipy librosa audioread soundfile

# Install TorchCodec for audio codec support
echo ""
echo "Installing torchcodec..."
pip install torchcodec

# Install CORS and other FastAPI utilities
echo ""
echo "Installing FastAPI extras..."
pip install python-dotenv pydantic

# Install sentence-transformers for reranking
echo ""
echo "Installing sentence-transformers..."
pip install sentence-transformers

# Test the environment
echo ""
echo "Testing Python environment..."
python3 -c "
import sys
print(f'Python: {sys.version}')
import torch
print(f'PyTorch: {torch.__version__}')
print(f'CUDA available: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'CUDA device: {torch.cuda.get_device_name(0)}')
"

echo ""
echo "========================================"
echo "Setup Complete!"
echo "========================================"
echo ""
echo "To activate the environment, run:"
echo "  source ~/.lfm-venv/bin/activate"
echo ""
echo "To start the LFM server:"
echo "  cd ~/OmniCortex"
echo "  source .lfm-venv/bin/activate"
echo "  python lfm/serve_lfm.py --host 0.0.0.0 --port 8012 --device cuda --preload"
echo ""
