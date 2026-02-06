#!/bin/bash
# Quick start script for vLLM server
# Usage: ./start_vllm.sh [model_name] [port] [gpu_id]

MODEL=${1:-"meta-llama/Meta-Llama-3.1-8B-Instruct"}
PORT=${2:-8000}
GPU_ID=${3:-0}

echo "🚀 Starting vLLM Server"
echo "   Model: $MODEL"
echo "   Port: $PORT"
echo "   GPU: $GPU_ID"
echo ""

# Set GPU
export CUDA_VISIBLE_DEVICES=$GPU_ID

# Start vLLM server
python -m vllm.entrypoints.openai.api_server \
    --model $MODEL \
    --host 0.0.0.0 \
    --port $PORT \
    --dtype auto \
    --max-model-len 4096 \
    --gpu-memory-utilization 0.9 \
    --max-num-seqs 256 \
    --disable-log-requests

# If you want to run in background:
# nohup python -m vllm.entrypoints.openai.api_server ... > vllm_$PORT.log 2>&1 &
