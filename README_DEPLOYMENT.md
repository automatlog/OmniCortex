# OmniCortex Deployment Hub

Welcome to the deployment center. Choose the guide that fits your needs:

- **[Deployment Guide](DEPLOYMENT_GUIDE.md)**: Full, step-by-step instructions for Production.
- **[Quick Reference](DEPLOYMENT_QUICK_REFERENCE.md)**: Commands and ports cheat sheet.
- **[Deployment Checklist](DEPLOYMENT_CHECKLIST.md)**: Printable checklist to ensure nothing is missed.
- **[Service Management](scripts/service_manager.py)**: The Python script that powers the deployment.

## Fast Track
For a standard Linux GPU server:

```bash
# 1. Setup
./setup_environments.sh

# 2. Run
source .venv/bin/activate
python scripts/service_manager.py monitor
```
