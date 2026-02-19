#!/bin/bash
# Stop OmniCortex Services (nohup/manual)

echo "🛑 Stopping vLLM..."
pkill -f "vllm.entrypoints.openai.api_server" || echo "  - vLLM not found"

echo "🛑 Stopping API..."
pkill -f "uvicorn api:app" || echo "  - API not found"

echo "🛑 Stopping Admin Frontend..."
pkill -f "next-server" || echo "  - next-server not found"
pkill -f "next dev" || echo "  - next dev not found"

echo "✅ All OmniCortex services stopped."
