# OmniCortex Service Management Guide

Complete guide for managing vLLM and Moshi API services with automated monitoring, logging, and scheduling.

---

## Overview

The service management system provides:
- ✅ **Auto-restart** on failure
- ✅ **Rotating logs** (10MB per file, 5 backups)
- ✅ **Health monitoring** via HTTP endpoints
- ✅ **Process statistics** (CPU, memory, uptime)
- ✅ **Windows Task Scheduler** integration
- ✅ **Cron-like scheduling** capabilities

---

## Quick Start

### 1. Install Dependencies

```bash
# Activate main environment
source .venv/bin/activate

# Install required packages
pip install psutil requests
```

### 2. Start Services

```bash
# Start all services with monitoring
python scripts/service_manager.py monitor

# Start specific service
python scripts/service_manager.py start --service vllm
python scripts/service_manager.py start --service moshi

# Check status
python scripts/service_manager.py status
```

### 3. Setup Auto-Start

**Linux (Systemd - Recommended):**
```bash
# Generate systemd service configuration
python scripts/setup_linux_scheduler.py

# Install and enable service
sudo cp storage/omnicortex.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable omnicortex.service
sudo systemctl start omnicortex.service
```

**Windows:**
```bash
# Generate Windows Task Scheduler configuration
python scripts/setup_windows_scheduler.py

# Then follow the instructions to:
# - Import task into Task Scheduler, OR
# - Run the generated batch file, OR
# - Install as Windows Service with NSSM
```

---

## Service Manager Commands

### Start Services
```bash
# Start all services
python scripts/service_manager.py start

# Start specific service
python scripts/service_manager.py start --service vllm
python scripts/service_manager.py start --service moshi
```

### Stop Services
```bash
# Stop all services
python scripts/service_manager.py stop

# Stop specific service
python scripts/service_manager.py stop --service vllm
```

### Restart Services
```bash
# Restart all services
python scripts/service_manager.py restart

# Restart specific service
python scripts/service_manager.py restart --service vllm
```

### Monitor Services
```bash
# Start monitoring loop (auto-restart on failure)
python scripts/service_manager.py monitor

# Custom monitoring interval (default: 30s)
python scripts/service_manager.py monitor --interval 60
```

### Check Status
```bash
python scripts/service_manager.py status
```

Output example:
```
============================================================
SERVICE STATUS
============================================================

VLLM:
  Status: running
  PID: 12345
  CPU: 45.2%
  Memory: 8192.5 MB
  Uptime: 3600s
  Restarts: 0

MOSHI:
  Status: running
  PID: 12346
  CPU: 12.3%
  Memory: 2048.1 MB
  Uptime: 3600s
  Restarts: 0
============================================================
```

---

## Configuration

Edit `scripts/service_manager.py` to customize:

### vLLM Configuration
```python
"vllm": {
    "cmd": [
        sys.executable, "-m", "vllm.entrypoints.openai.api_server",
        "--model", "nvidia/Llama-3.1-8B-Instruct-NVFP4",
        "--host", "0.0.0.0",
        "--port", "8080",
        "--max-model-len", "8192",
        "--gpu-memory-utilization", "0.90",
        "--max-num-seqs", "100",
    ],
    "health_url": "http://localhost:8080/health",
    "health_interval": 60,
    "restart_delay": 10,
    "max_restarts": 5,
    "enabled": True
}
```

### Moshi Configuration
```python
"moshi": {
    "cmd": [sys.executable, "-m", "moshi.server", "--port", "8998"],
    "health_url": "http://localhost:8998",
    "health_interval": 60,
    "restart_delay": 10,
    "max_restarts": 5,
    "enabled": True
}
```

### Disable a Service
```python
"moshi": {
    # ... other config ...
    "enabled": False  # Set to False to disable
}
```

---

## Logging

### Log Files Location
```
storage/logs/
├── service_manager.log      # Main manager logs
├── vllm_server.log          # vLLM service logs
└── moshi_server.log         # Moshi service logs
```

### Log Rotation
- **Max size**: 10MB per file
- **Backups**: 5 files kept
- **Format**: `YYYY-MM-DD HH:MM:SS | LEVEL | Message`

### View Logs
```bash
# Real-time monitoring
tail -f storage/logs/vllm_server.log
tail -f storage/logs/moshi_server.log

# Windows PowerShell
Get-Content storage/logs/vllm_server.log -Wait -Tail 50
```

---

## Linux Systemd Setup (Recommended)

### Automatic Setup

1. Run setup script:
```bash
python scripts/setup_linux_scheduler.py
```

2. Install systemd service:
```bash
sudo cp storage/omnicortex.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable omnicortex.service
sudo systemctl start omnicortex.service
```

3. Verify service:
```bash
sudo systemctl status omnicortex.service
```

### Systemd Management

```bash
# Start service
sudo systemctl start omnicortex

# Stop service
sudo systemctl stop omnicortex

# Restart service
sudo systemctl restart omnicortex

# Check status
sudo systemctl status omnicortex

# View logs
sudo journalctl -u omnicortex -f

# Disable auto-start
sudo systemctl disable omnicortex
```

### Cron Job (Alternative)

If systemd is not available, use cron:

1. Run setup script:
```bash
python scripts/setup_linux_scheduler.py
```

2. Edit crontab:
```bash
crontab -e
```

3. Add this line (check every 5 minutes):
```bash
*/5 * * * * /path/to/OmniCortex/storage/cron_monitor.sh
```

4. Verify:
```bash
crontab -l
```

### Screen/Tmux (Development)

For persistent terminal sessions:

**Using screen:**
```bash
screen -dmS omnicortex bash -c 'cd /path/to/OmniCortex && source .venv/bin/activate && python scripts/service_manager.py monitor'

# Reattach to view
screen -r omnicortex

# Detach: Ctrl+A, then D
```

**Using tmux:**
```bash
tmux new-session -d -s omnicortex 'cd /path/to/OmniCortex && source .venv/bin/activate && python scripts/service_manager.py monitor'

# Reattach to view
tmux attach -t omnicortex

# Detach: Ctrl+B, then D
```

---

## Windows Task Scheduler Setup

### Automatic Setup (Requires Admin)

1. Run setup script:
```bash
python scripts/setup_windows_scheduler.py
```

2. Open **Administrator PowerShell** and run:
```powershell
schtasks /Create /TN "OmniCortex_Services" /XML "storage/omnicortex_task.xml" /F
```

3. Verify in Task Scheduler:
```powershell
schtasks /Query /TN "OmniCortex_Services"
```

### Manual Setup

1. Run setup script to generate XML:
```bash
python scripts/setup_windows_scheduler.py
```

2. Open Task Scheduler (`taskschd.msc`)
3. Click **Action** → **Import Task...**
4. Select `storage/omnicortex_task.xml`
5. Click **OK**

### Batch File (Simple)

Double-click `start_services.bat` to start services manually.

---

## Windows Service (Advanced)

For production deployments, install as a Windows Service using NSSM:

### Install NSSM
```powershell
# Using Chocolatey
choco install nssm

# Or download from: https://nssm.cc/download
```

### Create Service
```powershell
# Install service
nssm install OmniCortex "C:\path\to\python.exe" "C:\path\to\scripts\service_manager.py" monitor

# Configure service
nssm set OmniCortex AppDirectory "C:\path\to\OmniCortex"
nssm set OmniCortex DisplayName "OmniCortex AI Services"
nssm set OmniCortex Description "vLLM and Moshi API Services"
nssm set OmniCortex Start SERVICE_AUTO_START

# Start service
nssm start OmniCortex
```

### Manage Service
```powershell
# Check status
nssm status OmniCortex

# Stop service
nssm stop OmniCortex

# Restart service
nssm restart OmniCortex

# Remove service
nssm remove OmniCortex confirm
```

---

## Health Monitoring

### Health Check Endpoints

- **vLLM**: `http://localhost:8080/health`
- **Moshi**: `http://localhost:8998/` (checks connectivity)

### Manual Health Check
```bash
# vLLM
curl http://localhost:8080/health

# Moshi
curl http://localhost:8998/
```

### Auto-Restart Logic

1. Service process exits → Auto-restart immediately
2. Health check fails → Log warning (no restart)
3. Max restarts exceeded (5) → Stop auto-restart, require manual intervention
4. Service runs for 5+ minutes → Reset restart counter

---

## Troubleshooting

### Services Won't Start

1. **Check Python environment**:
```bash
python --version  # Should be 3.12+
pip list | grep vllm
pip list | grep moshi
```

2. **Check GPU availability**:
```bash
nvidia-smi
```

3. **Check ports**:
```bash
netstat -ano | findstr :8080
netstat -ano | findstr :8998
```

4. **Check logs**:
```bash
type storage\logs\vllm_server.log
type storage\logs\moshi_server.log
```

### Service Keeps Restarting

1. Check error logs for crash reasons
2. Reduce GPU memory utilization:
```python
"--gpu-memory-utilization", "0.80"  # Instead of 0.90
```

3. Reduce max sequences:
```python
"--max-num-seqs", "50"  # Instead of 100
```

### High Memory Usage

1. **vLLM**: Reduce model length or GPU utilization
```python
"--max-model-len", "4096"  # Instead of 8192
"--gpu-memory-utilization", "0.85"
```

2. **Monitor with**:
```bash
python scripts/service_manager.py status
```

### Permission Errors (Windows)

Run PowerShell/CMD as **Administrator** when:
- Creating scheduled tasks
- Installing Windows services
- Accessing system directories

---

## Advanced: Cron-like Scheduling

### Add Scheduled Tasks

Edit `scripts/service_manager.py` and add to `ServiceManager`:

```python
def scheduled_tasks(self):
    """Run scheduled maintenance tasks"""
    import schedule
    
    # Daily log cleanup at 2 AM
    schedule.every().day.at("02:00").do(self.cleanup_old_logs)
    
    # Restart services weekly
    schedule.every().sunday.at("03:00").do(self.restart_all)
    
    # Health report every hour
    schedule.every().hour.do(self.send_health_report)
    
    while self.running:
        schedule.run_pending()
        time.sleep(60)
```

### Install Schedule Library
```bash
pip install schedule
```

---

## Integration with OmniCortex API

The services are automatically used by the FastAPI backend:

```python
# api.py uses vLLM automatically
VLLM_BASE_URL = "http://localhost:8080/v1"

# Moshi is used for voice endpoints
MOSHI_URL = "http://localhost:8998"
```

No additional configuration needed once services are running.

---

## Performance Tuning

### High Throughput (Many Users)
```python
"--max-num-seqs", "256",
"--gpu-memory-utilization", "0.95",
"--disable-log-requests"
```

### Low Latency (Few Users)
```python
"--max-num-seqs", "32",
"--use-v2-block-manager"
```

### Memory Constrained
```python
"--max-model-len", "4096",
"--gpu-memory-utilization", "0.80",
"--swap-space", "10"
```

---

## Monitoring Dashboard (Optional)

### Prometheus Metrics

vLLM exposes metrics at `http://localhost:8080/metrics`

### Grafana Setup

1. Install Prometheus + Grafana
2. Configure Prometheus to scrape vLLM:
```yaml
scrape_configs:
  - job_name: 'vllm'
    static_configs:
      - targets: ['localhost:8080']
```

3. Import vLLM dashboard in Grafana

---

## Summary

| Feature | Command |
|---------|---------|
| Start all services | `python scripts/service_manager.py start` |
| Monitor with auto-restart | `python scripts/service_manager.py monitor` |
| Check status | `python scripts/service_manager.py status` |
| Setup Windows scheduler | `python scripts/setup_windows_scheduler.py` |
| View logs | `type storage\logs\vllm_server.log` |

---

## Support

For issues:
1. Check logs in `storage/logs/`
2. Run `python scripts/service_manager.py status`
3. Verify GPU with `nvidia-smi`
4. Check ports with `netstat -ano | findstr :8080`
