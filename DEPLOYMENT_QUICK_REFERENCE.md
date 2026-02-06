# Deployment Quick Reference

## Quick Commands

| Action | Command |
| :--- | :--- |
| **Setup Env** | `./setup_environments.sh` |
| **Start Services** | `python scripts/service_manager.py monitor` |
| **Check Status** | `python scripts/service_manager.py status` |
| **Install Service** | `python scripts/setup_linux_scheduler.py` |
| **View Logs** | `tail -f storage/logs/*.log` |

## Ports

| Service | Port | Description |
| :--- | :--- | :--- |
| **API** | `8000` | FastAPI Backend |
| **Admin** | `3000` | Next.js Dashboard |
| **vLLM** | `8080` | LLM Inference Server |
| **Moshi** | `8998` | Voice/TTS Server |
| **Postgres** | `5432` | Database (or 5433 local) |

## Key Concepts
- **.venv**: Main Python environment (API, vLLM).
- **.moshi-venv**: Dedicated environment for Moshi (Voice).
- **Service Manager**: Python script that acts like Supervisor/Cron.
