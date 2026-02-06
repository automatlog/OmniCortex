# setup_environments.sh Analysis & Recommendations

## Current Setup Overview

The `setup_environments.sh` script implements a **dual-environment strategy** to handle conflicting PyTorch requirements:

### Environment 1: Main (.venv)
- **Purpose**: vLLM, API, Streamlit
- **Python**: 3.12
- **PyTorch**: 2.4.0 (stable, cu121)
- **Key Packages**: vLLM 0.6.3, Transformers 4.46.0, Sentence-Transformers

### Environment 2: Moshi (.moshi-venv)
- **Purpose**: PersonaPlex/Moshi voice model
- **Python**: 3.12
- **PyTorch**: Nightly (cu126)
- **Key Packages**: Moshi

---

## Analysis

### ✅ Strengths

1. **Conflict Resolution**: Separates incompatible PyTorch versions
   - vLLM requires stable PyTorch 2.4.0
   - Moshi requires nightly PyTorch for Blackwell GPU (sm_120)

2. **Clean Slate**: Uses `rm -rf` to ensure fresh installs
   - Prevents dependency conflicts
   - Ensures reproducible builds

3. **Explicit Versions**: Pins specific versions
   - vLLM 0.6.3
   - Transformers 4.46.0
   - PyTorch 2.4.0

4. **Clear Documentation**: Provides usage instructions at the end

### ⚠️ Issues & Recommendations

#### 1. **Bash Script on Windows**
**Issue**: Script uses bash (`#!/bin/bash`) but you're on Windows (cmd shell)

**Solutions**:
- **Option A**: Run in Git Bash or WSL
- **Option B**: Convert to PowerShell (recommended for Windows)
- **Option C**: Use Python script (cross-platform)

#### 2. **Hard Reset Every Time**
**Issue**: `rm -rf .venv` destroys environment on every run

**Recommendation**: Add conditional check:
```bash
if [ -d ".venv" ]; then
    read -p "Environment exists. Recreate? (y/n) " -n 1 -r
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf .venv
    fi
fi
```

#### 3. **Missing Error Handling**
**Issue**: `set -e` stops on first error, but no cleanup

**Recommendation**: Add trap for cleanup:
```bash
trap 'echo "❌ Setup failed at line $LINENO"' ERR
```

#### 4. **No Validation**
**Issue**: Doesn't verify installations succeeded

**Recommendation**: Add validation:
```bash
# After vLLM install
python -c "import vllm; print(f'✅ vLLM {vllm.__version__}')" || echo "❌ vLLM failed"
```

#### 5. **CUDA Version Assumptions**
**Issue**: Assumes cu121/cu126 are available

**Recommendation**: Detect CUDA version:
```bash
CUDA_VERSION=$(nvidia-smi | grep "CUDA Version" | awk '{print $9}')
echo "Detected CUDA: $CUDA_VERSION"
```

#### 6. **No Dependency Caching**
**Issue**: Re-downloads everything on each run

**Recommendation**: Use `uv` cache or pip cache:
```bash
export UV_CACHE_DIR=/workspace/.uv-cache
```

---

## Recommended Improvements

### 1. PowerShell Version (Windows-Native)

Create `setup_environments.ps1`:

```powershell
# setup_environments.ps1
$ErrorActionPreference = "Stop"

Write-Host "🚀 Starting Full Environment Setup..." -ForegroundColor Green
Set-Location $PSScriptRoot

# Check CUDA
$cudaVersion = (nvidia-smi | Select-String "CUDA Version").ToString().Split()[-1]
Write-Host "✅ Detected CUDA: $cudaVersion" -ForegroundColor Cyan

# Main Environment
Write-Host "`n📦 Setting up Main Environment (.venv)..." -ForegroundColor Yellow

if (Test-Path ".venv") {
    $response = Read-Host "Environment exists. Recreate? (y/n)"
    if ($response -eq "y") {
        Remove-Item -Recurse -Force .venv
    }
}

uv venv .venv --python 3.12 --seed
.\.venv\Scripts\Activate.ps1

Write-Host "⬇️ Installing PyTorch..." -ForegroundColor Cyan
uv pip install torch==2.4.0 torchvision==0.19.0 torchaudio==2.4.0 --index-url https://download.pytorch.org/whl/cu121

Write-Host "🧠 Installing vLLM..." -ForegroundColor Cyan
uv pip install vllm==0.6.3

Write-Host "📦 Installing dependencies..." -ForegroundColor Cyan
uv pip install transformers==4.46.0 sentence-transformers==3.2.1 accelerate streamlit

# Validate
python -c "import vllm; print(f'✅ vLLM {vllm.__version__}')"
python -c "import torch; print(f'✅ PyTorch {torch.__version__}')"

deactivate

Write-Host "`n✅ Setup Complete!" -ForegroundColor Green
```

### 2. Python Version (Cross-Platform)

Create `setup_environments.py`:

```python
#!/usr/bin/env python3
"""
Cross-platform environment setup for OmniCortex
"""
import subprocess
import sys
import os
from pathlib import Path

def run(cmd, env_name=None):
    """Run command and check result"""
    print(f"▶️ {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"❌ Failed: {result.stderr}")
        sys.exit(1)
    return result.stdout

def setup_main_env():
    """Setup main environment"""
    print("\n" + "="*60)
    print("MAIN ENVIRONMENT (.venv)")
    print("="*60)
    
    # Create venv
    if Path(".venv").exists():
        response = input("Environment exists. Recreate? (y/n): ")
        if response.lower() == "y":
            import shutil
            shutil.rmtree(".venv")
    
    run(["uv", "venv", ".venv", "--python", "3.12", "--seed"])
    
    # Determine activation script
    if sys.platform == "win32":
        activate = ".venv\\Scripts\\activate.bat"
        pip_cmd = [".venv\\Scripts\\python.exe", "-m", "pip"]
    else:
        activate = ".venv/bin/activate"
        pip_cmd = [".venv/bin/python", "-m", "pip"]
    
    # Install PyTorch
    print("⬇️ Installing PyTorch...")
    run([*pip_cmd, "install", "torch==2.4.0", "torchvision==0.19.0", 
         "--index-url", "https://download.pytorch.org/whl/cu121"])
    
    # Install vLLM
    print("🧠 Installing vLLM...")
    run([*pip_cmd, "install", "vllm==0.6.3"])
    
    # Validate
    print("\n✅ Validating installation...")
    run([pip_cmd[0], "-c", "import vllm; print(f'vLLM {vllm.__version__}')"])
    
    print("✅ Main environment ready!")

if __name__ == "__main__":
    setup_main_env()
```

### 3. Add Requirements Files

Create `requirements-main.txt`:
```txt
# Main Environment
torch==2.4.0
torchvision==0.19.0
torchaudio==2.4.0
vllm==0.6.3
transformers==4.46.0
sentence-transformers==3.2.1
accelerate
streamlit
fastapi
uvicorn
psycopg2-binary
sqlalchemy
```

Create `requirements-moshi.txt`:
```txt
# Moshi Environment
--pre
--index-url https://download.pytorch.org/whl/nightly/cu126
torch
torchvision
torchaudio
moshi
```

Then simplify setup:
```bash
# Main
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -r requirements-main.txt

# Moshi
uv venv .moshi-venv --python 3.12
source .moshi-venv/bin/activate
uv pip install -r requirements-moshi.txt
```

---

## Windows-Specific Recommendations

### 1. Use PowerShell Instead of Bash
```powershell
# Activate environment
.\.venv\Scripts\Activate.ps1

# Run commands
python -m vllm.entrypoints.openai.api_server ...
```

### 2. Handle Long Paths
```powershell
# Enable long paths in Windows
New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" `
  -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force
```

### 3. Use Windows Services
Instead of bash scripts, use Windows Task Scheduler or NSSM (see SERVICE_MANAGEMENT.md)

---

## Testing the Setup

### 1. Verify Main Environment
```bash
source .venv/bin/activate  # Linux/Mac
.\.venv\Scripts\Activate.ps1  # Windows

python -c "import vllm; print(vllm.__version__)"
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

### 2. Verify Moshi Environment
```bash
source .moshi-venv/bin/activate  # Linux/Mac
.\.moshi-venv\Scripts\Activate.ps1  # Windows

python -c "import moshi; print('Moshi OK')"
python -c "import torch; print(torch.__version__)"
```

### 3. Test vLLM Server
```bash
source .venv/bin/activate
python -m vllm.entrypoints.openai.api_server \
  --model nvidia/Llama-3.1-8B-Instruct-NVFP4 \
  --port 8080 \
  --max-model-len 2048  # Small for testing
```

### 4. Test Moshi Server
```bash
source .moshi-venv/bin/activate
python -m moshi.server --port 8998
```

---

## Migration Path

### Current State
```
setup_environments.sh (bash) → Manual activation → Manual server start
```

### Recommended State
```
setup_environments.ps1 (PowerShell) → service_manager.py → Windows Task Scheduler
```

### Migration Steps

1. **Convert setup script**:
```bash
# Create PowerShell version
python scripts/create_powershell_setup.py
```

2. **Setup service manager**:
```bash
# Install dependencies
pip install psutil requests

# Test service manager
python scripts/service_manager.py status
```

3. **Configure Windows scheduler**:
```bash
python scripts/setup_windows_scheduler.py
```

4. **Validate**:
```bash
# Check services are running
python scripts/service_manager.py status

# Check logs
type storage\logs\vllm_server.log
```

---

## Summary

| Aspect | Current | Recommended |
|--------|---------|-------------|
| **Setup Script** | Bash | PowerShell (Windows) or Python (cross-platform) |
| **Environment Management** | Manual activation | Automated via service manager |
| **Service Startup** | Manual | Windows Task Scheduler / Service |
| **Monitoring** | None | Automated with health checks |
| **Logging** | Basic | Rotating logs with retention |
| **Error Handling** | `set -e` | Comprehensive try-catch with cleanup |

---

## Next Steps

1. ✅ **Created**: `scripts/service_manager.py` - Automated service management
2. ✅ **Created**: `scripts/setup_windows_scheduler.py` - Windows integration
3. ✅ **Created**: `docs/SERVICE_MANAGEMENT.md` - Complete documentation
4. 🔄 **TODO**: Convert `setup_environments.sh` to PowerShell
5. 🔄 **TODO**: Add validation tests to setup script
6. 🔄 **TODO**: Create requirements.txt files for easier dependency management

---

## Conclusion

The current `setup_environments.sh` is functional but has limitations on Windows. The new service management system provides:

- ✅ Cross-platform compatibility
- ✅ Automated monitoring and restart
- ✅ Proper logging with rotation
- ✅ Windows Task Scheduler integration
- ✅ Health checks and statistics
- ✅ Easy configuration and management

Use the new system for production deployments!
