# RunPod Deployment Guide

Deploy OmniCortex on RunPod with NVIDIA GPUs using PyTorch Ubuntu template.

---

## Why RunPod?

RunPod offers cost-effective GPU instances with flexible pricing and instant deployment.

### RunPod vs Other Cloud Providers

| Aspect | RunPod |
|--------|--------|
| **Hourly Cost** | $0.34-0.79/hr (RTX 4090) |
| **GPU Options** | RTX 3090, RTX 4090, A40, A100 |
| **Setup Time** | 5 minutes |
| **Flexibility** | Per-second billing |
| **Templates** | Pre-configured PyTorch |
| **Scaling** | Instant pod creation |

### Cost Savings Example

**24/7 Production (1 month):**
- RunPod RTX 4090: ~$250/month
- **Highly cost-effective for GPU workloads**

---

## Recommended GPU Options

| GPU | VRAM | Price/hr* | Best For |
|-----|------|-----------|----------|
| **RTX 4090** | 24GB | $0.34-0.79 | **Recommended** (8B-70B models) |
| RTX 3090 | 24GB | $0.29-0.44 | Budget option |
| A40 | 48GB | $0.79-1.10 | Large models (70B+) |
| A100 80GB | 80GB | $1.89-2.49 | Multi-model serving |

*Prices vary by region and availability (Secure Cloud vs Community Cloud)*

### Recommended for OmniCortex
- **Development**: RTX 3090 (24GB) - $0.29/hr
- **Production**: RTX 4090 (24GB) - $0.34/hr
- **High Traffic**: 2x RTX 4090 or A40 (48GB)

---

## GPU Specifications

### RTX 4090 (Recommended)

| Feature | Spec |
|---------|------|
| Architecture | Ada Lovelace |
| VRAM | 24GB GDDR6X |
| Memory Bandwidth | 1,008 GB/s |
| FP32 Performance | 82.6 TFLOPS |
| Tensor Cores | 512 (4th gen) |
| Power | 450W |

**Perfect for:**
- Llama 3.1 8B (full precision) - Recommended
- Llama 3.1 70B (quantized)
- High throughput inference
- Multiple concurrent users

---

## Quick Start (5 Minutes)

### 1. Create RunPod Account

1. Go to [RunPod.io](https://runpod.io)
2. Sign up and add credits ($10 minimum)
3. Navigate to **Pods** → **+ Deploy**

### 2. Select Template

1. Choose **PyTorch** template (Ubuntu 22.04)
2. Or search for "pytorch ubuntu" in templates

### 3. Configure Pod

**GPU Selection:**
- GPU Type: RTX 4090 (or RTX 3090 for budget)
- GPU Count: 1 (or 2 for high traffic)
- Region: Choose nearest with availability

**Storage:**
- Container Disk: 50GB minimum
- Volume Disk: 100GB (for models and data)

**Ports:**
- Expose ports: 8000, 8080, 8501, 5432

### 4. Deploy Pod

Click **Deploy** and wait ~2 minutes for pod to start.

---

## Installation Steps

### 1. Connect to Pod

```bash
# Get SSH command from RunPod dashboard
ssh root@<POD_IP> -p <SSH_PORT> -i ~/.ssh/id_ed25519
```

Or use **Web Terminal** in RunPod dashboard.

### 2. Verify GPU

```bash
nvidia-smi
```

You should see your GPU(s) listed.

### 3. Clone Repository

```bash
cd /workspace
git clone <YOUR_REPO_URL> OmniCortex
cd OmniCortex
```

### 4. Run Deployment Script

```bash
chmod +x scripts/deploy_runpod.sh
./scripts/deploy_runpod.sh
```

**What the script does:**
1. Updates system packages
2. Installs PostgreSQL 16 + pgvector
3. Installs Python 3.12 + uv
4. Installs Docker (if not present)
5. Starts vLLM server
6. Creates virtual environment
7. Installs dependencies
8. Configures .env
9. Starts API and UI services

**Time:** 10-15 minutes (includes model download)

---

## Manual Installation

If you prefer manual setup:

### 1. Install Dependencies

```bash
# Update system
apt update && apt upgrade -y

# Install PostgreSQL + pgvector
apt install -y postgresql postgresql-contrib
apt install -y postgresql-16-pgvector

# Install Python 3.12
add-apt-repository ppa:deadsnakes/ppa -y
apt install -y python3.12 python3.12-venv python3.12-dev

# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.cargo/env
```

### 2. Setup Database

```bash
systemctl start postgresql
systemctl enable postgresql

sudo -u postgres psql -c "CREATE DATABASE omnicortex;"
sudo -u postgres psql -d omnicortex -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### 3. Start vLLM

```bash
docker run -d --gpus all --name vllm-server \
  --restart unless-stopped \
  -p 8080:8000 \
  -v /workspace/.cache/huggingface:/root/.cache/huggingface \
  -e HUGGING_FACE_HUB_TOKEN=your_token_here \
  vllm/vllm-openai:latest \
  --model meta-llama/Meta-Llama-3.1-8B-Instruct \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.90 \
  --dtype auto
```

### 4. Setup Application

```bash
cd /workspace/OmniCortex

# Create virtual environment
uv venv --python 3.12
source .venv/bin/activate

# Install dependencies
uv pip install -e .

# Configure environment
cp .env.example .env
nano .env  # Edit with your settings

# Start services
python api.py &
streamlit run main.py --server.port 8501 --server.address 0.0.0.0 &
```

---

## Configuration

### Environment Variables

Edit `/workspace/OmniCortex/.env`:

```env
# Database
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/omnicortex

# vLLM
VLLM_BASE_URL=http://localhost:8080/v1
VLLM_MODEL=meta-llama/Meta-Llama-3.1-8B-Instruct

# Voice Engine (LiquidAI)
VOICE_MODEL=LiquidAI/LFM2.5-Audio-1.5B
VOICE_MAX_INSTANCES=8

# HuggingFace Token
HUGGING_FACE_HUB_TOKEN=your_token_here

# WhatsApp (optional)
WHATSAPP_ACCESS_TOKEN=your_token
WHATSAPP_PHONE_ID=your_phone_id
```

### Port Mapping

RunPod automatically exposes ports. Access via:

- **Streamlit UI**: `https://<POD_ID>-8501.proxy.runpod.net`
- **API Docs**: `https://<POD_ID>-8000.proxy.runpod.net/docs`
- **vLLM**: Internal only (localhost:8080)

Get URLs from RunPod dashboard under **Connect** → **HTTP Ports**.

---

## Service Management

### Using systemd (Recommended)

Create service files:

```bash
# API Service
cat > /etc/systemd/system/omnicortex-api.service << 'EOF'
[Unit]
Description=OmniCortex API
After=network.target docker.service

[Service]
Type=simple
User=root
WorkingDirectory=/workspace/OmniCortex
Environment="PATH=/workspace/OmniCortex/.venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/workspace/OmniCortex/.venv/bin/python api.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# UI Service
cat > /etc/systemd/system/omnicortex-ui.service << 'EOF'
[Unit]
Description=OmniCortex UI
After=network.target omnicortex-api.service

[Service]
Type=simple
User=root
WorkingDirectory=/workspace/OmniCortex
Environment="PATH=/workspace/OmniCortex/.venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/workspace/OmniCortex/.venv/bin/streamlit run main.py --server.port 8501 --server.address 0.0.0.0
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Enable and start
systemctl daemon-reload
systemctl enable omnicortex-api omnicortex-ui
systemctl start omnicortex-api omnicortex-ui
```

### Check Status

```bash
# All services
systemctl status omnicortex-api omnicortex-ui
docker ps | grep vllm-server

# GPU usage
nvidia-smi

# Logs
journalctl -u omnicortex-api -f
journalctl -u omnicortex-ui -f
docker logs -f vllm-server
```

---

## Cost Optimization

### 1. Use Spot Instances (Community Cloud)

- **Savings**: Up to 70% cheaper
- **Risk**: Can be interrupted
- **Best for**: Development, testing

### 2. Stop Pod When Not in Use

```bash
# From RunPod dashboard
Pods → Your Pod → Stop
```

**Billing stops immediately** (per-second billing)

### Use Different Model Sizes

```bash
# 8B model (recommended, good balance)
--model meta-llama/Meta-Llama-3.1-8B-Instruct

# 70B model (requires 48GB+ VRAM)
--model meta-llama/Meta-Llama-3.1-70B-Instruct
```

### 4. Right-Size GPU

| Use Case | GPU | Monthly Cost* |
|----------|-----|---------------|
| Development | RTX 3090 | ~$210 |
| Production (low traffic) | RTX 4090 | ~$250 |
| Production (high traffic) | 2x RTX 4090 | ~$500 |

*24/7 operation on Secure Cloud*

---

## Monitoring

### GPU Usage

```bash
# Real-time monitoring
watch -n 1 nvidia-smi

# Or use nvtop
apt install nvtop -y
nvtop
```

### Application Metrics

```bash
# API health
curl http://localhost:8000/

# vLLM health
curl http://localhost:8080/health

# Prometheus metrics
curl http://localhost:8000/metrics
```

### RunPod Dashboard

Monitor from RunPod web interface:
- GPU utilization
- Network traffic
- Disk usage
- Cost tracking

---

## Troubleshooting

### GPU Not Detected

```bash
# Check GPU
nvidia-smi

# If error, restart pod from RunPod dashboard
```

### vLLM Out of Memory

```bash
# Reduce memory usage
docker stop vllm-server && docker rm vllm-server

docker run -d --gpus all --name vllm-server \
  --restart unless-stopped \
  -p 8080:8000 \
  -v /workspace/.cache/huggingface:/root/.cache/huggingface \
  -e HUGGING_FACE_HUB_TOKEN=your_token \
  vllm/vllm-openai:latest \
  --model meta-llama/Meta-Llama-3.1-8B-Instruct \
  --max-model-len 4096 \
  --gpu-memory-utilization 0.85 \
  --dtype auto
```

### Services Not Starting

```bash
# Check logs
journalctl -u omnicortex-api -n 50
journalctl -u omnicortex-ui -n 50

# Check ports
netstat -tulpn | grep -E '8000|8501'

# Restart
systemctl restart omnicortex-api omnicortex-ui
```

### Database Connection Failed

```bash
# Check PostgreSQL
systemctl status postgresql

# Restart
systemctl restart postgresql

# Test connection
psql -U postgres -d omnicortex -c "SELECT 1;"
```

### Model Download Fails

```bash
# Check HuggingFace token
echo $HUGGING_FACE_HUB_TOKEN

# Login manually
docker exec -it vllm-server bash
huggingface-cli login
```

---

## Persistence & Backups

### Data Persistence

RunPod pods have two storage types:

1. **Container Disk**: Ephemeral (lost on pod stop)
2. **Volume Disk**: Persistent (survives pod restarts)

**Important**: Store data on `/workspace` (volume disk)

```bash
# Database data
/workspace/postgresql/data

# Application data
/workspace/OmniCortex/storage

# Models cache
/workspace/.cache/huggingface
```

### Backup Strategy

```bash
# Backup database
pg_dump -U postgres omnicortex > /workspace/backup_$(date +%Y%m%d).sql

# Backup application data
tar -czf /workspace/storage_backup.tar.gz /workspace/OmniCortex/storage
```

### Restore from Backup

```bash
# Restore database
psql -U postgres omnicortex < /workspace/backup_20240130.sql

# Restore storage
tar -xzf /workspace/storage_backup.tar.gz -C /
```

---

## Advanced Configuration

### Multi-GPU Setup

For 2x RTX 4090:

```bash
docker run -d --gpus all --name vllm-server \
  --restart unless-stopped \
  -p 8080:8000 \
  -v /workspace/.cache/huggingface:/root/.cache/huggingface \
  -e HUGGING_FACE_HUB_TOKEN=your_token \
  vllm/vllm-openai:latest \
  --model meta-llama/Meta-Llama-3.1-70B-Instruct \
  --tensor-parallel-size 2 \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.90 \
  --dtype auto
```

### Custom Domain

1. Get pod URL from RunPod dashboard
2. Create CNAME record: `app.yourdomain.com` → `<POD_ID>-8501.proxy.runpod.net`
3. Access via `https://app.yourdomain.com`

### SSL/HTTPS

RunPod provides automatic HTTPS via proxy URLs. No additional configuration needed.

---

## Production Checklist

- [ ] Pod created with appropriate GPU
- [ ] SSH access configured
- [ ] Deployment script executed
- [ ] All services running
- [ ] vLLM responding
- [ ] Database accessible
- [ ] UI accessible via RunPod proxy URL
- [ ] API accessible via RunPod proxy URL
- [ ] .env configured with tokens
- [ ] Data stored on volume disk (/workspace)
- [ ] Backup strategy in place
- [ ] Monitoring setup
- [ ] Cost alerts configured

---

## Quick Reference

### Useful Commands

```bash
# Check services
systemctl status omnicortex-api omnicortex-ui
docker ps | grep vllm

# View logs
journalctl -u omnicortex-api -f
journalctl -u omnicortex-ui -f
docker logs -f vllm-server

# Restart everything
systemctl restart omnicortex-api omnicortex-ui
docker restart vllm-server

# GPU monitoring
watch -n 1 nvidia-smi

# Check ports
netstat -tulpn | grep -E '8000|8080|8501'
```

### Important Paths

- **Application**: `/workspace/OmniCortex`
- **Config**: `/workspace/OmniCortex/.env`
- **Logs**: `/workspace/OmniCortex/storage/logs/`
- **Database**: `/workspace/postgresql/data`
- **Models**: `/workspace/.cache/huggingface`

### Default Credentials

- **PostgreSQL**: `postgres` / `postgres`
- **Database**: `omnicortex`

---

## Next Steps

1. ✅ Deploy pod with PyTorch template
2. ✅ Run deployment script
3. ✅ Access UI via RunPod proxy URL
4. ✅ Create your first agent
5. ✅ Upload documents and test RAG
6. ✅ Configure WhatsApp integration (optional)
7. ✅ Setup monitoring and backups
8. ✅ Configure cost alerts

---

**Your OmniCortex deployment on RunPod is ready!** 🚀

**Features**: Llama 3.1 8B model + LiquidAI voice engine for reliable AI deployment
