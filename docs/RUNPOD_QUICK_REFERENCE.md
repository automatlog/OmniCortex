# OmniCortex RunPod Deployment - Quick Reference Guide

## 📋 Table of Contents
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Deployment](#deployment)
- [Management](#management)
- [Troubleshooting](#troubleshooting)
- [Cost Optimization](#cost-optimization)

---

## Prerequisites

### 1. RunPod Account Setup
```bash
# Sign up at https://runpod.io
# Get your API key from: https://www.runpod.io/console/user/settings

# Set API key
export RUNPOD_API_KEY="your-api-key-here"
```

### 2. Install runpodctl (CLI Tool)
```bash
# Linux/Mac
wget -qO- https://github.com/runpod/runpodctl/releases/latest/download/runpodctl-linux-amd64 -O /tmp/runpodctl
chmod +x /tmp/runpodctl
sudo mv /tmp/runpodctl /usr/local/bin/runpodctl

# Verify installation
runpodctl version
```

### 3. Set Required Environment Variables
```bash
# Required
export RUNPOD_API_KEY="your-runpod-api-key"
export POSTGRES_PASSWORD="your-secure-db-password"
export HUGGINGFACE_TOKEN="hf_your_huggingface_token"

# Optional (WhatsApp integration)
export WHATSAPP_ACCESS_TOKEN="your-whatsapp-token"
export WHATSAPP_PHONE_ID="your-phone-id"

# Save to ~/.bashrc or ~/.zshrc for persistence
```

---

## Quick Start

### 1. Download Configuration Files
```bash
# Download configuration
curl -O https://raw.githubusercontent.com/your-org/OmniCortex/main/runpod_config.yaml

# Download deployment script
curl -O https://raw.githubusercontent.com/your-org/OmniCortex/main/deploy_runpod.sh
chmod +x deploy_runpod.sh
```

### 2. Review and Customize Configuration
```bash
# Open configuration file
nano runpod_config.yaml

# Key settings to review:
# - GPU type (line 23)
# - Cloud type: SECURE vs COMMUNITY (line 30)
# - Storage sizes (lines 118-119)
# - Model selection (line 161)
```

### 3. Deploy
```bash
# Deploy to RunPod
./deploy_runpod.sh

# Or with custom config
./deploy_runpod.sh --config my_custom_config.yaml

# Dry run (preview without deploying)
./deploy_runpod.sh --dry-run
```

---

## Configuration

### GPU Selection Guide

| GPU Model | VRAM | Best For | Cost/Hour | Recommended Models |
|-----------|------|----------|-----------|-------------------|
| RTX 4090 | 24GB | Small models | $0.69 | Llama-3.2-3B, Mistral-7B |
| RTX 6000 Ada | 48GB | Medium models | $0.77 | Llama-3.1-8B, Mistral-7B |
| A40 | 48GB | Production | $0.99 | Llama-3.1-8B |
| RTX 6000 Pro | 96GB | Large models | $1.84 | Llama-3.3-70B |
| A100 80GB | 80GB | Enterprise | $2.49 | Llama-3.1-70B |

### Model Selection by GPU

**For RTX 6000 Ada (48GB):**
```yaml
vllm:
  model: "meta-llama/Meta-Llama-3.1-8B-Instruct"  # 16GB VRAM
  max_model_len: 8192
  gpu_memory_utilization: 0.90
```

**For RTX 6000 Pro (96GB):**
```yaml
vllm:
  model: "meta-llama/Llama-3.3-70B-Instruct"  # 70GB VRAM
  max_model_len: 16384
  gpu_memory_utilization: 0.90
```

### Storage Configuration

```yaml
storage:
  container_disk_gb: 50    # Ephemeral (resets on restart)
  volume_disk_gb: 100      # Persistent (survives restarts)
```

**Storage Guidelines:**
- Container disk: OS, temp files, cache
- Volume disk: Models, data, logs, database
- Minimum 50GB for container, 100GB for volume

---

## Deployment

### Method 1: Using Deployment Script (Recommended)
```bash
# Standard deployment
./deploy_runpod.sh

# The script will:
# 1. Check prerequisites
# 2. Validate environment variables
# 3. Parse configuration
# 4. Show cost estimates
# 5. Create pod
# 6. Display connection info
```

### Method 2: Manual Deployment via CLI
```bash
# Create pod manually
runpodctl create pod \
  --name "omnicortex-prod" \
  --gpuType "RTX 6000 Ada Generation" \
  --imageName "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04" \
  --containerDiskSize 50 \
  --volumeSize 100 \
  --ports "22/tcp,8000/tcp,8501/tcp" \
  --env "POSTGRES_PASSWORD=$POSTGRES_PASSWORD" \
  --cloudType "SECURE"
```

### Method 3: Using RunPod Web Interface
1. Go to https://www.runpod.io/console/pods
2. Click "Deploy"
3. Select GPU type
4. Choose template: "PyTorch 2.4.0"
5. Configure storage and ports
6. Set environment variables
7. Click "Deploy"

---

## Management

### Pod Operations

```bash
# List all pods
runpodctl get pods

# Get pod details
runpodctl get pod POD_ID

# Start pod
runpodctl start pod POD_ID

# Stop pod (saves costs)
runpodctl stop pod POD_ID

# Remove pod
runpodctl remove pod POD_ID

# View logs
runpodctl logs POD_ID

# Execute command in pod
runpodctl exec POD_ID -- bash -c "nvidia-smi"
```

### Connecting to Your Pod

#### SSH Access
```bash
# Get connection info
POD_IP=$(runpodctl get pod POD_ID | jq -r '.desiredStatus.publicIp')
SSH_PORT=$(runpodctl get pod POD_ID | jq -r '.desiredStatus.ports."22/tcp"')

# Connect
ssh root@$POD_IP -p $SSH_PORT
```

#### Access Services
```bash
# Streamlit UI
http://<POD_IP>:8501

# API Backend
http://<POD_IP>:8000

# API Documentation
http://<POD_IP>:8000/docs

# vLLM Server (internal)
http://localhost:8080
```

### Monitoring

#### GPU Usage
```bash
# SSH into pod
ssh root@<POD_IP> -p <SSH_PORT>

# Watch GPU usage
watch -n 1 nvidia-smi

# Check vLLM logs
tail -f /workspace/logs/vllm.log

# Check API logs
tail -f /workspace/logs/api.log

# Check Streamlit logs
tail -f /workspace/logs/streamlit.log
```

#### System Resources
```bash
# Disk usage
df -h

# Memory usage
free -h

# Running processes
htop

# Network connections
netstat -tlnp
```

---

## Troubleshooting

### Common Issues

#### 1. Pod Won't Start
```bash
# Check pod status
runpodctl get pod POD_ID

# View logs
runpodctl logs POD_ID

# Common causes:
# - Insufficient GPU availability
# - Invalid configuration
# - Missing environment variables
```

#### 2. Models Not Loading
```bash
# SSH into pod
ssh root@<POD_IP> -p <SSH_PORT>

# Check HuggingFace token
echo $HUGGINGFACE_TOKEN

# Manually download model
cd /workspace/models
python -c "from transformers import AutoModel; AutoModel.from_pretrained('meta-llama/Meta-Llama-3.1-8B-Instruct')"

# Check disk space
df -h /workspace
```

#### 3. Out of Memory (OOM)
```bash
# Reduce GPU memory utilization
# Edit in pod: /workspace/OmniCortex/config.yaml
gpu_memory_utilization: 0.80  # Lower from 0.90

# Reduce max model length
max_model_len: 4096  # Lower from 8192

# Reduce concurrent requests
max_num_seqs: 50  # Lower from 100

# Restart vLLM
pkill -f vllm
python -m vllm.entrypoints.openai.api_server ...
```

#### 4. Service Not Accessible
```bash
# Check if service is running
netstat -tlnp | grep 8000  # API
netstat -tlnp | grep 8501  # Streamlit
netstat -tlnp | grep 8080  # vLLM

# Check firewall
ufw status

# Test locally first
curl http://localhost:8000/health
curl http://localhost:8501
```

#### 5. Database Connection Issues
```bash
# Check PostgreSQL status
service postgresql status

# Start PostgreSQL
service postgresql start

# Check connection
psql -U postgres -d omnicortex -c "SELECT version();"

# Reset password
psql -U postgres -c "ALTER USER postgres PASSWORD '$POSTGRES_PASSWORD';"
```

### Debug Mode

```bash
# Enable debug logging
export LOG_LEVEL="DEBUG"

# Restart services with debug
cd /workspace/OmniCortex
python -m uvicorn main:app --reload --log-level debug
```

---

## Cost Optimization

### 1. Use Spot Instances (50% Cheaper)
```yaml
runpod:
  use_spot: true
  bid_per_gpu: 0.50  # Max bid price
```

**Pros:** 50% cheaper
**Cons:** Can be interrupted with 30-second warning

### 2. Auto-Shutdown Configuration
```yaml
runpod:
  idle_timeout_minutes: 30  # Stop after 30 min idle
  max_runtime_hours: 24     # Max runtime before shutdown
```

### 3. Community Cloud (70% Cheaper)
```yaml
runpod:
  cloud_type: "COMMUNITY"  # vs "SECURE"
```

**Pros:** 70% cheaper
**Cons:** Lower reliability, consumer-grade hardware

### 4. Right-Size Your GPU

| Workload | Recommended GPU | Monthly Cost |
|----------|----------------|--------------|
| Development/Testing | RTX 4090 (24GB) | $497 |
| Small Production | RTX 6000 Ada (48GB) | $554 |
| Medium Production | A40 (48GB) | $713 |
| Large Models | RTX 6000 Pro (96GB) | $1,325 |

### 5. Storage Optimization
```bash
# Clean model cache periodically
rm -rf /workspace/models/huggingface/hub/*

# Use smaller storage
container_disk_gb: 30  # Instead of 50
volume_disk_gb: 50     # Instead of 100
```

### 6. Model Quantization
```yaml
optimization:
  quantization:
    enabled: true
    bits: 8  # or 4 for more compression
```

**Benefits:**
- 50% less VRAM usage (8-bit)
- 75% less VRAM usage (4-bit)
- Slightly lower quality

### Cost Tracking Commands
```bash
# View current costs
runpodctl get pod POD_ID | jq '.desiredStatus.cost'

# Calculate running costs
HOURS=$(runpodctl get pod POD_ID | jq '.desiredStatus.uptime' | awk '{print $1/3600}')
RATE=0.77  # Your GPU rate
echo "Current cost: \$$(echo "$HOURS * $RATE" | bc)"

# Set budget alerts (in config)
cost_management:
  daily_budget_usd: 20.00
  alert_at_percent: 80
```

---

## Advanced Configuration

### Multi-GPU Setup
```yaml
runpod:
  gpu_count: 2

vllm:
  tensor_parallel_size: 2  # Must match GPU count
```

### Custom Start Script
```yaml
runpod:
  start_command: |
    #!/bin/bash
    # Your custom initialization
    apt-get update
    apt-get install -y your-package
    # Start services
    ./start_services.sh
```

### Persistent SSH Keys
```bash
# On your local machine
cat ~/.ssh/id_rsa.pub

# In RunPod dashboard, add SSH key
# Or add to pod:
echo "your-public-key" >> /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
```

---

## Useful Links

- **RunPod Dashboard:** https://www.runpod.io/console
- **RunPod Documentation:** https://docs.runpod.io
- **GPU Pricing:** https://www.runpod.io/console/gpu-instance/community/explore
- **OmniCortex Docs:** https://docs.omnicortex.ai
- **Support:** https://github.com/your-org/OmniCortex/issues

---

## Quick Commands Cheat Sheet

```bash
# Deployment
./deploy_runpod.sh                    # Deploy with default config
./deploy_runpod.sh --dry-run          # Preview deployment

# Pod Management
runpodctl get pods                    # List all pods
runpodctl stop pod POD_ID             # Stop pod
runpodctl start pod POD_ID            # Start pod
runpodctl remove pod POD_ID           # Delete pod

# Monitoring
runpodctl logs POD_ID                 # View logs
ssh root@IP -p PORT                   # SSH access
tail -f /workspace/logs/vllm.log      # Watch vLLM logs

# Troubleshooting
nvidia-smi                            # GPU status
htop                                  # System resources
df -h                                 # Disk usage
netstat -tlnp                         # Port status

# Cost Management
runpodctl stop pod POD_ID             # Stop when not in use
```

---

## Emergency Shutdown

```bash
# If costs are running high, immediately stop all pods:
runpodctl get pods | jq -r '.[].id' | xargs -I {} runpodctl stop pod {}

# Or via web interface:
# https://www.runpod.io/console/pods → Stop All
```

---

**Need Help?**
- 📧 Email: support@omnicortex.ai
- 💬 Discord: https://discord.gg/omnicortex
- 📖 Documentation: https://docs.omnicortex.ai
- 🐛 Report Issues: https://github.com/your-org/OmniCortex/issues
