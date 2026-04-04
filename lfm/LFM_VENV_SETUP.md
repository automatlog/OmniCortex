# LFM Virtual Environment Setup

This directory contains scripts to set up an isolated Python environment for the LFM2.5-Audio server.

## Files

- `setup_lfm_quick.sh` - Quick setup script (recommended)
- `setup_lfm_venv.sh` - Detailed setup script with step-by-step installation
- `requirements_lfm.txt` - Python package dependencies
- `serve_lfm.py` - Standalone LFM HTTP server
- `lfm_mic_test.html` - Browser mic test UI
- `server.js` - Express server for the mic test UI

## Quick Setup (Recommended)

On the server, run:

```bash
cd ~/OmniCortex
bash lfm/setup_lfm_quick.sh
```

This will:
1. Create `.lfm-venv` virtual environment
2. Install PyTorch with CUDA 12.1 support
3. Install all LFM dependencies

## Step-by-Step Setup

If you prefer more control, use the detailed script:

```bash
cd ~/OmniCortex
bash lfm/setup_lfm_venv.sh
```

## Manual Setup

If you prefer manual installation:

```bash
# Create virtual environment
cd ~/OmniCortex
python3 -m venv .lfm-venv

# Activate it
source .lfm-venv/bin/activate

# Install PyTorch with CUDA 12.1
pip install --upgrade pip setuptools wheel
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# Install requirements
pip install -r lfm/requirements_lfm.txt
```

## Verify Installation

```bash
source .lfm-venv/bin/activate
python3 -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}')"
```

## Run LFM Server

```bash
# Activate environment
source ~/OmniCortex/.lfm-venv/bin/activate

# Start server with CUDA
python lfm/serve_lfm.py --host 0.0.0.0 --port 8012 --device cuda --preload

# Or without preload (lazy load model on first request)
python lfm/serve_lfm.py --host 0.0.0.0 --port 8012 --device cuda

# Run on CPU if CUDA issues occur
python lfm/serve_lfm.py --host 0.0.0.0 --port 8012 --device cpu
```

## Environment Variables

You can also use environment variables to configure the server:

```bash
export VOICE_MODEL="LiquidAI/LFM2.5-Audio-1.5B"
export LFM_DEVICE="cuda"
export LFM_PORT="8012"
export LFM_PRELOAD="true"
export VOICE_MAX_INSTANCES="4"

python lfm/serve_lfm.py
```

## Troubleshooting

### Missing CUDA Libraries

If you get `libnvrtc.so` errors (version depends on your CUDA runtime):

```bash
# For CUDA 12.1 (default in this setup):
apt-get update
apt-get install -y cuda-runtime-12-1

# Or set LD_LIBRARY_PATH
export LD_LIBRARY_PATH=/usr/local/cuda-12.1/lib64:$LD_LIBRARY_PATH
source .lfm-venv/bin/activate
python lfm/serve_lfm.py --host 0.0.0.0 --port 8012 --device cuda

# Note: If you have CUDA 13 runtime installed, use cuda-runtime-13-* and /usr/local/cuda-13/lib64 instead
```

### Falling Back to CPU

If CUDA is problematic, use CPU mode (slower but works):

```bash
source .lfm-venv/bin/activate
python lfm/serve_lfm.py --host 0.0.0.0 --port 8012 --device cpu
```

### Test the Server

Once running, test with:

```bash
curl http://0.0.0.0:8012/health
```

You should see:
```json
{"status":"ok","model":"LiquidAI/LFM2.5-Audio-1.5B","device":"cuda","loaded":true}
```

## HTML UI

The LFM Mic Test UI is served at:
- Local: http://0.0.0.0:3000
- Public: https://jwpma2d42856fn-3000.proxy.runpod.net

Start the Node.js server (if not already running):

```bash
cd ~/OmniCortex/lfm
npm install  # One time
npm start    # Serves on port 3000
```
