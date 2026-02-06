# OmniCortex Deployment Guide

## Overview
This guide covers deploying OmniCortex on various platforms (Linux, Docker, RunPod).

## Prerequisites
- **OS**: Linux (Ubuntu 22.04+ recommended) or Windows (WSL2)
- **GPU**: NVIDIA GPU with 16GB+ VRAM (Recommended: 24GB+ like A100/A10g/RTX 4090)
- **Drivers**: CUDA 12.1+ installed
- **Software**: Docker, Python 3.12, Node.js 18+

## Deployment Options

### 1. Linux Service (Recommended for Production)
This method runs vLLM, Moshi, API, and Admin as systemd services.

1.  **Run Setup Script**:
    ```bash
    ./setup_environments.sh
    ```
2.  **Generate Service Files**:
    ```bash
    source .venv/bin/activate
    python scripts/setup_linux_scheduler.py
    ```
3.  **Install Systemd Service**:
    ```bash
    sudo cp storage/omnicortex.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable omnicortex
    sudo systemctl start omnicortex
    ```

### 2. Manual Run (Development/Testing)
Use the Python Service Manager to run everything in the foreground.

```bash
source .venv/bin/activate
python scripts/service_manager.py monitor
```

### 3. RunPod / Remote GPU Cloud
For RunPod, use the provided templates or start from a PyTorch base image.

1.  SSH into your Pod.
2.  Clone the repository.
3.  Run `./setup_environments.sh`.
4.  Start services: `python scripts/service_manager.py monitor`.

## Security Hardening (Production)
1.  **Firewall**: Allow ports 8000 (API), 3000 (Admin) only via Reverse Proxy (Nginx).
2.  **SSL**: Use Certbot to secure domains.
3.  **Authentication**: Ensure `.env` passwords are complex.

## Troubleshooting
- **Logs**: Check `storage/logs/` for individual service logs.
- **Ports**: Ensure ports 8000, 8080, 8998, 3000 are free.
- **GPU**: Run `nvidia-smi` to verify GPU visibility.
