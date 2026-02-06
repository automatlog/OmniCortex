# OmniCortex Deployment Checklist

## Pre-Deployment
- [ ] **Hardware**: Server has NVIDIA GPU with sufficient VRAM?
- [ ] **Drivers**: `nvidia-smi` confirms CUDA 12.1+?
- [ ] **OS**: Linux (Ubuntu 22.04) or Windows (WSL2)?
- [ ] **Dependencies**: `docker`, `python3.12`, `node`, `npm`, `uv` installed?

## Environment Setup
- [ ] Run `./setup_environments.sh` (No errors?)
- [ ] Check `.env` matches `.env.example`?
- [ ] Database credentials correct?
- [ ] `local_pg_data` excluded from git?

## Service Setup
- [ ] Generate Linux Services: `python scripts/setup_linux_scheduler.py`
- [ ] Enable Systemd: `sudo systemctl enable omnicortex`
- [ ] Start Service: `sudo systemctl start omnicortex`

## Verification
- [ ] Check Logs: `tail -f storage/logs/service_manager.log`
- [ ] API Health: `curl http://localhost:8000/docs`
- [ ] vLLM Health: `curl http://localhost:8080/health`
- [ ] Admin UI: `http://localhost:3000` accessible?
- [ ] Moshi: Voice server responding on 8998?

## Post-Deployment
- [ ] Security: Firewall enabled (UFW)?
- [ ] Backup: Database backup scheduled?
- [ ] Monitoring: Logs rotating correctly?
