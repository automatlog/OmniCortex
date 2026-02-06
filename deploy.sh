#!/bin/bash
# OmniCortex One-Click Deploy Script
set -e

echo "🚀 Starting OmniCortex Deployment..."

# 1. Environment Setup
if [ ! -d ".venv" ] || [ ! -d ".moshi-venv" ]; then
    echo "📦 Setting up environments..."
    ./setup_environments.sh
else
    echo "✅ Environments already exist."
fi

# 2. Service Management
echo "🔄 Starting Service Manager..."
source .venv/bin/activate

# Check if already running
if pgrep -f "service_manager.py monitor" > /dev/null; then
    echo "✅ Service Manager is already running."
    python scripts/service_manager.py status
else
    # Start in background via nohup if on server, or direct execution
    echo "▶️ Starting services (vLLM, Moshi, API, Admin)..."
    python scripts/service_manager.py monitor
fi

echo ""
echo "=================================================="
echo "🎉 DEPLOYMENT ACTIVE"
echo "=================================================="
echo "Services:"
echo " - Frontend:    http://localhost:3000"
echo " - Backend:     http://localhost:8000"
echo " - Voice AI:    http://localhost:8998"
echo " - vLLM:        http://localhost:8080"
echo ""
echo "To view logs:"
echo "   tail -f storage/logs/service_manager.log"
echo "=================================================="
