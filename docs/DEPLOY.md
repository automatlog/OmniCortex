# 🚀 OmniCortex Deployment Guide

## Architecture: Hybrid (Local Intelligence + Cloud Connectivity)
- **Local Intelligence**: vLLM (Simulates OpenAI) + Local Embedding Models. No external AI API calls.
- **Connectivity**: Exposes endpoints for WhatsApp/Webhooks. Checks internet only if Agents explicitly use Search Tools (configurable).

## 1. Prerequisites (RunPod GPU Instance)
- **OS**: Ubuntu 22.04 (PyTorch template recommended).
- **Python**: 3.12+ (Managed by `uv`).
- **GPU**: NVIDIA GPU required for vLLM (RTX 4090, RTX 3090, A40, or A100).
- **Storage**: ~100GB+ for Models and Data.

## 2. Quick Start (RunPod)

### Option A: Automated Deployment (Recommended)
```bash
# 1. Create RunPod pod with PyTorch template
# 2. Connect via SSH or Web Terminal
# 3. Clone repository
git clone <repo-url> /workspace/OmniCortex
cd /workspace/OmniCortex

# 4. Run deployment script
chmod +x scripts/deploy_runpod.sh
sudo ./scripts/deploy_runpod.sh
```

### Option B: Manual Setup
```bash
# 1. Clone & Enter
git clone <repo-url> /workspace/OmniCortex
cd /workspace/OmniCortex

# 2. Install Dependencies (Fast with uv)
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.cargo/env
uv sync
```

## 3. Setup Models (Offline Ready)
You must place embedding models locally since agents run offline.
```bash
# Create directory
mkdir -p models/sentence-transformers

# Upload your model folder 'all-MiniLM-L6-v2' to:
# /OmniCortex/models/sentence-transformers/all-MiniLM-L6-v2/
```
*Tip: If you have internet on the VM during setup, you can run a script to download them once.*

## 4. Environment Config
Create `.env`:
```ini
DATABASE_URL=postgresql://user:pass@localhost:5432/omnicortex
VLLM_BASE_URL=http://localhost:8080/v1
LLM_MODEL=meta-llama/Meta-Llama-3.1-8B-Instruct
WHATSAPP_ACCESS_TOKEN=...
WHATSAPP_PHONE_ID=...
```

## 5. Run Services

### A. Start vLLM (The Brain)
```bash
# Docker (Recommended)
docker run -d --gpus all --name vllm-server \
  --restart unless-stopped \
  -p 8080:8000 \
  -v /workspace/.cache/huggingface:/root/.cache/huggingface \
  -e HUGGING_FACE_HUB_TOKEN=your_token \
  vllm/vllm-openai:latest \
  --model meta-llama/Meta-Llama-3.1-8B-Instruct \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.90
```

### B. Start OmniCortex (The App)
```bash
# Start API
python api.py &

# Start UI
streamlit run main.py --server.port 8501 --server.address 0.0.0.0 &
```

## 6. Access Application

Get URLs from RunPod dashboard under **Connect** → **HTTP Ports**:
- **Streamlit UI**: `https://<POD_ID>-8501.proxy.runpod.net`
- **API Docs**: `https://<POD_ID>-8000.proxy.runpod.net/docs`

## 7. Monitoring
- **Metrics**: `http://localhost:8000/metrics` (Prometheus)
- **Logs**: `storage/logs/`
- **GPU**: `nvidia-smi` or RunPod dashboard
