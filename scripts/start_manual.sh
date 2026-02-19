#!/bin/bash
# Manual Start Script for OmniCortex (Non-Systemd/Docker/RunPod)
# Usage: bash start_manual.sh

PROJECT_DIR="/workspace"
VENV_DIR="${PROJECT_DIR}/.venv"
LOG_DIR="${PROJECT_DIR}/storage/logs"

mkdir -p "$LOG_DIR"

echo "🛑 Stopping existing services..."
pkill -f vllm.entrypoints.openai.api_server || true
pkill -f uvicorn || true
pkill -f "next-server" || true

echo "🚀 Starting vLLM (Custom Config)..."
export VLLM_ATTENTION_BACKEND=TORCH_SDPA
export CUDA_LAUNCH_BLOCKING=1
export PATH="${VENV_DIR}/bin:$PATH"

# User-specified vLLM command (Background)
nohup python3 -m vllm.entrypoints.openai.api_server \
  --model meta-llama/Llama-3.1-8B-Instruct \
  --port 8080 \
  --host 0.0.0.0 \
  --max-model-len 4096 \
  --dtype float16 \
  --enforce-eager \
  --trust-remote-code \
  > "${LOG_DIR}/vllm_server.log" 2>&1 &

echo "🚀 Starting API..."
nohup uvicorn api:app --host 0.0.0.0 --port 8000 \
  > "${LOG_DIR}/api_server.log" 2>&1 &

echo "🚀 Starting Admin (npm run dev)..."
cd "${PROJECT_DIR}/admin"
# Detect node
NODE_BIN=$(which node 2>/dev/null || echo "/root/.nvm/versions/node/v22/bin/node")
nohup $NODE_BIN node_modules/.bin/next dev -H 0.0.0.0 -p 3000 \
  > "${LOG_DIR}/admin_ui.log" 2>&1 &

echo "✅ All services started in background!"
echo "Logs: tail -f ${LOG_DIR}/*.log"
