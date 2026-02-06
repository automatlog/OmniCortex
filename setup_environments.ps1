# OmniCortex Environment Setup (PowerShell)
# Windows-native version of setup_environments.sh

$ErrorActionPreference = "Stop"

Write-Host "`n🚀 Starting Full Environment Setup (Dual-Env Strategy)..." -ForegroundColor Green
Write-Host "="*60 -ForegroundColor Cyan

# Check prerequisites
Write-Host "`n📋 Checking prerequisites..." -ForegroundColor Yellow

# Check Python
try {
    $pythonVersion = python --version 2>&1
    Write-Host "✅ Python: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "❌ Python not found. Install Python 3.12+" -ForegroundColor Red
    exit 1
}

# Check UV
try {
    $uvVersion = uv --version 2>&1
    Write-Host "✅ UV: $uvVersion" -ForegroundColor Green
} catch {
    Write-Host "❌ UV not found. Install with: pip install uv" -ForegroundColor Red
    exit 1
}

# Check CUDA
try {
    $cudaInfo = nvidia-smi 2>&1 | Select-String "CUDA Version"
    if ($cudaInfo) {
        $cudaVersion = ($cudaInfo -split '\s+')[-1]
        Write-Host "✅ CUDA Version: $cudaVersion" -ForegroundColor Green
    }
} catch {
    Write-Host "⚠️ nvidia-smi not found. GPU may not be available." -ForegroundColor Yellow
}

# ==========================================
# 1. Main Environment (vLLM, API, Streamlit)
# ==========================================
Write-Host "`n" + ("="*60) -ForegroundColor Cyan
Write-Host "MAIN ENVIRONMENT (.venv)" -ForegroundColor Yellow
Write-Host ("="*60) -ForegroundColor Cyan

if (Test-Path ".venv") {
    Write-Host "⚠️ .venv already exists" -ForegroundColor Yellow
    $response = Read-Host "Recreate? This will delete existing environment (y/n)"
    if ($response -eq "y") {
        Write-Host "🗑️ Removing old environment..." -ForegroundColor Yellow
        Remove-Item -Recurse -Force .venv
    } else {
        Write-Host "⏭️ Skipping main environment setup" -ForegroundColor Cyan
        $skipMain = $true
    }
}

if (-not $skipMain) {
    Write-Host "`n📦 Creating virtual environment..." -ForegroundColor Cyan
    uv venv .venv --python 3.12 --seed
    
    Write-Host "🔌 Activating environment..." -ForegroundColor Cyan
    & .\.venv\Scripts\Activate.ps1
    
    Write-Host "`n⬇️ Installing PyTorch Stable (cu121)..." -ForegroundColor Cyan
    uv pip install torch==2.4.0 torchvision==0.19.0 torchaudio==2.4.0 --index-url https://download.pytorch.org/whl/cu121
    
    Write-Host "`n🧠 Installing vLLM..." -ForegroundColor Cyan
    uv pip install vllm==0.6.3
    
    Write-Host "`n📦 Installing App Dependencies..." -ForegroundColor Cyan
    uv pip install transformers==4.46.0 sentence-transformers==3.2.1
    uv pip install accelerate streamlit audio-recorder-streamlit elevenlabs hf_transfer
    uv pip install langchain langchain-community langchain-openai
    uv pip install psycopg2-binary sqlalchemy pgvector
    uv pip install fastapi uvicorn prometheus-client
    uv pip install psutil requests  # For service manager
    
    Write-Host "`n✅ Validating installation..." -ForegroundColor Cyan
    python -c "import vllm; print(f'✅ vLLM {vllm.__version__}')"
    python -c "import torch; print(f'✅ PyTorch {torch.__version__}')"
    python -c "import transformers; print(f'✅ Transformers {transformers.__version__}')"
    
    Write-Host "`n✅ Main Environment Ready!" -ForegroundColor Green
    deactivate
}

# ==========================================
# 2. Moshi Environment (PersonaPlex)
# ==========================================
Write-Host "`n" + ("="*60) -ForegroundColor Cyan
Write-Host "MOSHI ENVIRONMENT (.moshi-venv)" -ForegroundColor Yellow
Write-Host ("="*60) -ForegroundColor Cyan

if (Test-Path ".moshi-venv") {
    Write-Host "⚠️ .moshi-venv already exists" -ForegroundColor Yellow
    $response = Read-Host "Recreate? This will delete existing environment (y/n)"
    if ($response -eq "y") {
        Write-Host "🗑️ Removing old environment..." -ForegroundColor Yellow
        Remove-Item -Recurse -Force .moshi-venv
    } else {
        Write-Host "⏭️ Skipping Moshi environment setup" -ForegroundColor Cyan
        $skipMoshi = $true
    }
}

if (-not $skipMoshi) {
    Write-Host "`n📦 Creating virtual environment..." -ForegroundColor Cyan
    uv venv .moshi-venv --python 3.12 --seed
    
    Write-Host "🔌 Activating environment..." -ForegroundColor Cyan
    & .\.moshi-venv\Scripts\Activate.ps1
    
    Write-Host "`n🌙 Installing PyTorch Nightly (cu126)..." -ForegroundColor Cyan
    uv pip install --pre torch torchvision torchaudio --index-url https://download.pytorch.org/whl/nightly/cu126
    
    Write-Host "`n🗣️ Installing Moshi..." -ForegroundColor Cyan
    uv pip install moshi
    
    Write-Host "`n✅ Validating installation..." -ForegroundColor Cyan
    python -c "import torch; print(f'✅ PyTorch {torch.__version__}')"
    python -c "import moshi; print('✅ Moshi installed')"
    
    Write-Host "`n✅ Moshi Environment Ready!" -ForegroundColor Green
    deactivate
}

# ==========================================
# 3. Setup Complete
# ==========================================
Write-Host "`n" + ("="*60) -ForegroundColor Green
Write-Host "🎉 SETUP COMPLETE!" -ForegroundColor Green
Write-Host ("="*60) -ForegroundColor Green

Write-Host "`nUsage Instructions:" -ForegroundColor Yellow
Write-Host "`n🔹 For MAIN APP (Streamlit/vLLM/API):" -ForegroundColor Cyan
Write-Host "   .\.venv\Scripts\Activate.ps1"
Write-Host "   python api.py"
Write-Host "   # or"
Write-Host "   streamlit run main.py"

Write-Host "`n🔹 For MOSHI (PersonaPlex):" -ForegroundColor Cyan
Write-Host "   .\.moshi-venv\Scripts\Activate.ps1"
Write-Host "   python -m moshi.server --port 8998"

Write-Host "`n🔹 For SERVICE MANAGEMENT (Recommended):" -ForegroundColor Cyan
Write-Host "   .\.venv\Scripts\Activate.ps1"
Write-Host "   python scripts/service_manager.py monitor"

Write-Host "`n🔹 Setup Windows Auto-Start:" -ForegroundColor Cyan
Write-Host "   python scripts/setup_windows_scheduler.py"

Write-Host "`n" + ("="*60) -ForegroundColor Green
Write-Host "📚 Documentation:" -ForegroundColor Yellow
Write-Host "   - Service Management: docs/SERVICE_MANAGEMENT.md"
Write-Host "   - Setup Analysis: docs/SETUP_ANALYSIS.md"
Write-Host "   - vLLM Guide: docs/vLLM.md"
Write-Host ("="*60) -ForegroundColor Green
Write-Host ""
