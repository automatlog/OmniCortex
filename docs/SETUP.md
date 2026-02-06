# Setup Guide - Linux

**Time**: ~20 minutes | **Platform**: Linux (Ubuntu 22.04+)

---

## Prerequisites

| Requirement | Version | Check | Notes |
|-------------|---------|-------|-------|
| Python | 3.12+ | `python3 --version` | Required |
| PostgreSQL | 16+ | `psql --version` | Required |
| Git | Latest | `git --version` | Required |
| NVIDIA GPU | 16GB+ VRAM | `nvidia-smi` | For vLLM |

---

## Quick Start (Linux)

```bash
# 1. Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.cargo/env

# 2. Clone and setup
git clone <YOUR_REPO_URL> ~/OmniCortex
cd ~/OmniCortex
uv venv --python 3.12 --seed
source .venv/bin/activate
uv pip install -e .

# 3. Install vLLM (Linux with GPU)
uv pip install vllm --torch-backend=auto

# 4. Configure
cp .env.example .env
nano .env  # Add your tokens

# 5. Setup database
sudo systemctl start postgresql
psql -U postgres -c "CREATE DATABASE omnicortex;"
psql -U postgres -d omnicortex -c "CREATE EXTENSION IF NOT EXISTS vector;"

# 6. Start services (3 terminals)
# Terminal 1: vLLM
python -m vllm.entrypoints.openai.api_server \
  --model meta-llama/Meta-Llama-3.1-8B-Instruct \
  --host 0.0.0.0 --port 8080 --dtype auto

# Terminal 2: API
uv run python api.py

# Terminal 3: UI
uv run streamlit run main.py --server.port 8501 --server.address 0.0.0.0
```

---

## Step 1: Install uv (Package Manager)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.cargo/env
```

**Verify:**
```bash
uv --version  # Should show 0.5+
```

**What is uv?**
- Fast Python package manager (10-100x faster than pip)
- Manages virtual environments
- Handles dependencies efficiently

---

## Step 2: Clone Repository

```bash
git clone https://github.com/YOUR_REPO/OmniCortex.git
cd OmniCortex
```

---

## Step 3: Create Virtual Environment

```bash
uv venv --python 3.12 --seed
```

**What this does:**
- Creates `.venv` folder with Python 3.12
- `--seed` installs pip, setuptools, wheel
- Isolates project dependencies from system Python

**Activate:**
```bash
source .venv/bin/activate
```

**You'll see** `(.venv)` in your terminal prompt when activated.

---

## Step 4: Install Dependencies

### Core Dependencies
```bash
# Install all required packages
uv pip install -e .
```

### Install vLLM (Linux with GPU)
```bash
# Install vLLM for local LLM inference
uv pip install vllm --torch-backend=auto
```

**What gets installed:**
- LangChain (LLM orchestration)
- FastAPI (REST API)
- Streamlit (Web UI)
- PostgreSQL drivers
- Vector store libraries
- vLLM (high-performance inference)
- And more (see `pyproject.toml`)

---

## Step 5: Configure Environment

```bash
# Copy template
cp .env.example .env

# Edit with your settings
nano .env
```

**Required settings:**
```env
# Database (Required)
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/omnicortex

# vLLM Settings (Required for local LLM)
USE_VLLM=true
VLLM_BASE_URL=http://localhost:8080/v1
VLLM_MODEL=meta-llama/Meta-Llama-3.1-8B-Instruct

# HuggingFace Token (Required for downloading Llama models)
HUGGING_FACE_HUB_TOKEN=your_token_here
```

**Optional settings:**
```env
# WhatsApp Integration
WHATSAPP_ACCESS_TOKEN=your_token
WHATSAPP_PHONE_ID=your_phone_id

# ClickHouse Analytics
CLICKHOUSE_HOST=localhost
CLICKHOUSE_PORT=8123
```

---

## Step 6: Setup Database

See [POSTGRESQL.md](POSTGRESQL.md) for detailed instructions.

Quick setup:
```bash
psql -U postgres -c "CREATE DATABASE omnicortex;"
psql -U postgres -d omnicortex -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

---

## Step 7: Start Services

### Terminal 1: Start vLLM Server
```bash
python -m vllm.entrypoints.openai.api_server \
  --model meta-llama/Meta-Llama-3.1-8B-Instruct \
  --host 0.0.0.0 \
  --port 8080 \
  --dtype auto \
  --max-model-len 8192

# Wait for: "Uvicorn running on http://0.0.0.0:8080"
```

### Terminal 2: Start API Server
```bash
uv run python api.py
# Runs on http://localhost:8000
```

### Terminal 3: Start Streamlit UI
```bash
uv run streamlit run main.py --server.port 8501 --server.address 0.0.0.0
# Runs on http://localhost:8501
```

---

## Step 8: Verify Installation

### Test Python Imports
```bash
uv run python -c "from core import process_question; print('✅ Core imports OK')"
```

### Test API Health
```bash
curl http://localhost:8000/
# Expected: {"status":"ok","service":"OmniCortex API"}
```

### Test vLLM Health
```bash
curl http://localhost:8080/health
# Expected: {"status":"ok"}
```

### Test LLM Inference
```bash
curl http://localhost:8080/v1/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"meta-llama/Meta-Llama-3.1-8B-Instruct","prompt":"Hello","max_tokens":10}'
```

### Access Web UI
Open browser: `http://localhost:8501`

---

## Common Issues & Solutions

### "No module named 'core'"
```bash
# Reinstall in editable mode
uv pip install -e .
```

### "Connection refused" (Database)
```bash
# Start PostgreSQL
sudo systemctl start postgresql

# Enable auto-start
sudo systemctl enable postgresql
```

### "CUDA not available"
```bash
# Check GPU
nvidia-smi

# Install NVIDIA drivers if needed
sudo apt install nvidia-driver-535 -y
sudo reboot
```

### "CUDA out of memory"
```bash
# Reduce vLLM memory usage
python -m vllm.entrypoints.openai.api_server \
  --model meta-llama/Meta-Llama-3.1-8B-Instruct \
  --host 0.0.0.0 --port 8080 \
  --max-model-len 4096 \
  --max-num-seqs 64 \
  --gpu-memory-utilization 0.85 \
  --dtype auto
```

### "Connection refused" (vLLM)
```bash
# Check if vLLM is running
ps aux | grep vllm

# Check logs
journalctl -u vllm -f  # if using systemd
```

### "Database 'omnicortex' does not exist"
```bash
# Create database
psql -U postgres -c "CREATE DATABASE omnicortex;"
psql -U postgres -d omnicortex -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### "Port already in use"
```bash
# Find process using port
sudo lsof -i :8080

# Kill process
sudo kill -9 <PID>
```

### Model Download Fails
```bash
# Set HuggingFace token
export HUGGING_FACE_HUB_TOKEN=your_token_here

# Or login
huggingface-cli login
```

---

## Dependencies Overview

| Package | Purpose |
|---------|---------|
| langchain | LLM orchestration |
| langchain-huggingface | Embeddings |
| langchain-postgres | Vector store |
| langchain-openai | OpenAI-compatible APIs |
| fastapi | REST API |
| streamlit | Web UI |
| sqlalchemy | Database ORM |
| psycopg2-binary | PostgreSQL driver |
| vllm | Local LLM inference (Linux) |
| sentence-transformers | Embedding models |

---

## Port Configuration

| Service | Port | Access |
|---------|------|--------|
| vLLM Server | 8080 | Internal (localhost) |
| FastAPI | 8000 | External |
| Streamlit UI | 8501 | External |
| PostgreSQL | 5432 | Internal (localhost) |
| ClickHouse | 8123 | Internal (optional) |

---

## Command Reference

### Virtual Environment
```bash
# Create
uv venv --python 3.12 --seed

# Activate
source .venv/bin/activate

# Deactivate
deactivate
```

### Package Management
```bash
# Install all dependencies
uv pip install -e .

# Install vLLM
uv pip install vllm --torch-backend=auto

# Update all packages
uv pip install -e . --upgrade

# List installed packages
uv pip list
```

### Service Management
```bash
# Start API
uv run python api.py

# Start UI
uv run streamlit run main.py --server.port 8501 --server.address 0.0.0.0

# Start vLLM
python -m vllm.entrypoints.openai.api_server \
  --model meta-llama/Meta-Llama-3.1-8B-Instruct \
  --host 0.0.0.0 --port 8080 --dtype auto
```

### Systemd Services (Production)
```bash
# Check status
sudo systemctl status omnicortex-api omnicortex-ui

# View logs
sudo journalctl -u omnicortex-api -f

# Restart
sudo systemctl restart omnicortex-api omnicortex-ui
```

---

## Next Steps

1. ✅ **Cloud Deployment**: See [RUNPOD.md](RUNPOD.md) for RunPod deployment
2. ✅ **Database Setup**: See [POSTGRESQL.md](POSTGRESQL.md) for details
3. ✅ **vLLM Configuration**: See [vLLM.md](vLLM.md) for tuning
4. ✅ **Model Selection**: See [LLM.md](LLM.md) for options
5. ✅ **Project Overview**: See [PROJECT.md](PROJECT.md) for architecture

---

## Production Deployment

For production deployment on RunPod with automated setup:

```bash
# Use the automated deployment script
sudo ./scripts/deploy_runpod.sh
```

See [RUNPOD.md](RUNPOD.md) for complete deployment guide.

---

**Setup complete! Start creating agents and uploading documents.** 🚀
