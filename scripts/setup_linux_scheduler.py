"""
Linux Systemd & Cron Setup for OmniCortex Services
Creates systemd services and cron jobs for vLLM and Moshi
"""
import os
import sys
from pathlib import Path
import subprocess

BASE_DIR = Path(__file__).parent.parent.resolve()
PYTHON_EXE = sys.executable
SERVICE_MANAGER = BASE_DIR / "scripts" / "service_manager.py"
USER = os.environ.get("USER", "ubuntu")


def create_systemd_service():
    """Create systemd service file"""
    service_content = f"""[Unit]
Description=OmniCortex AI Services (vLLM + Moshi)
After=network.target

[Service]
Type=simple
User={USER}
WorkingDirectory={BASE_DIR}
Environment="PATH={BASE_DIR}/.venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart={BASE_DIR}/.venv/bin/python {SERVICE_MANAGER} monitor
Restart=always
RestartSec=10
StandardOutput=append:{BASE_DIR}/storage/logs/systemd.log
StandardError=append:{BASE_DIR}/storage/logs/systemd.log

# Resource limits (optional)
# MemoryLimit=16G
# CPUQuota=400%

[Install]
WantedBy=multi-user.target
"""
    
    service_file = BASE_DIR / "storage" / "omnicortex.service"
    service_file.parent.mkdir(parents=True, exist_ok=True)
    service_file.write_text(service_content)
    
    print(f"✅ Systemd service file created: {service_file}")
    return service_file


def create_cron_job():
    """Create cron job for monitoring"""
    cron_script = BASE_DIR / "storage" / "cron_monitor.sh"
    
    script_content = f"""#!/bin/bash
# OmniCortex Service Monitor (runs every 5 minutes)
cd {BASE_DIR}
source .venv/bin/activate

# Check if service manager is running
if ! pgrep -f "service_manager.py monitor" > /dev/null; then
    echo "$(date): Service manager not running, starting..." >> {BASE_DIR}/storage/logs/cron.log
    nohup python {SERVICE_MANAGER} monitor >> {BASE_DIR}/storage/logs/cron.log 2>&1 &
fi
"""
    
    cron_script.write_text(script_content)
    cron_script.chmod(0o755)
    
    print(f"✅ Cron script created: {cron_script}")
    return cron_script


def print_instructions(service_file, cron_script):
    """Print setup instructions"""
    print("\n" + "="*70)
    print("LINUX SCHEDULER SETUP INSTRUCTIONS")
    print("="*70)
    
    print("\n📋 OPTION 1: Systemd Service (Recommended)")
    print("-" * 70)
    print("Systemd will automatically start services on boot and restart on failure.\n")
    
    print("1. Copy service file to systemd:")
    print(f"   sudo cp {service_file} /etc/systemd/system/omnicortex.service")
    
    print("\n2. Reload systemd:")
    print("   sudo systemctl daemon-reload")
    
    print("\n3. Enable service (start on boot):")
    print("   sudo systemctl enable omnicortex.service")
    
    print("\n4. Start service now:")
    print("   sudo systemctl start omnicortex.service")
    
    print("\n5. Check status:")
    print("   sudo systemctl status omnicortex.service")
    
    print("\n6. View logs:")
    print("   sudo journalctl -u omnicortex.service -f")
    print(f"   tail -f {BASE_DIR}/storage/logs/systemd.log")
    
    print("\n📋 Systemd Management Commands:")
    print("-" * 70)
    print("   sudo systemctl start omnicortex     # Start service")
    print("   sudo systemctl stop omnicortex      # Stop service")
    print("   sudo systemctl restart omnicortex   # Restart service")
    print("   sudo systemctl status omnicortex    # Check status")
    print("   sudo systemctl disable omnicortex   # Disable auto-start")
    
    print("\n\n📋 OPTION 2: Cron Job (Fallback)")
    print("-" * 70)
    print("Cron will check every 5 minutes and restart if needed.\n")
    
    print("1. Edit crontab:")
    print("   crontab -e")
    
    print("\n2. Add this line:")
    print(f"   */5 * * * * {cron_script}")
    
    print("\n3. Verify cron job:")
    print("   crontab -l")
    
    print("\n4. View cron logs:")
    print(f"   tail -f {BASE_DIR}/storage/logs/cron.log")
    
    print("\n\n📋 OPTION 3: Manual Start (Development)")
    print("-" * 70)
    print("For testing and development:\n")
    print(f"   cd {BASE_DIR}")
    print("   source .venv/bin/activate")
    print(f"   python {SERVICE_MANAGER} monitor")
    
    print("\n\n📋 OPTION 4: Screen/Tmux (Persistent Session)")
    print("-" * 70)
    print("Run in a detached terminal session:\n")
    
    print("Using screen:")
    print(f"   screen -dmS omnicortex bash -c 'cd {BASE_DIR} && source .venv/bin/activate && python {SERVICE_MANAGER} monitor'")
    print("   screen -r omnicortex  # Reattach to view")
    
    print("\nUsing tmux:")
    print(f"   tmux new-session -d -s omnicortex 'cd {BASE_DIR} && source .venv/bin/activate && python {SERVICE_MANAGER} monitor'")
    print("   tmux attach -t omnicortex  # Reattach to view")
    
    print("\n\n📋 Verify Services Are Running")
    print("-" * 70)
    print("   # Check processes")
    print("   ps aux | grep vllm")
    print("   ps aux | grep moshi")
    print("   ps aux | grep service_manager")
    
    print("\n   # Check ports")
    print("   netstat -tlnp | grep 8080  # vLLM")
    print("   netstat -tlnp | grep 8998  # Moshi")
    
    print("\n   # Check service status")
    print(f"   python {SERVICE_MANAGER} status")
    
    print("\n   # Test endpoints")
    print("   curl http://localhost:8080/health")
    print("   curl http://localhost:8998/")
    
    print("\n" + "="*70)
    print("📚 Documentation: docs/SERVICE_MANAGEMENT.md")
    print("="*70 + "\n")


def create_startup_script():
    """Create a simple startup script"""
    startup_script = BASE_DIR / "start_services.sh"
    
    content = f"""#!/bin/bash
# OmniCortex Services Startup Script

cd {BASE_DIR}
source .venv/bin/activate

echo "🚀 Starting OmniCortex Services..."
python {SERVICE_MANAGER} monitor
"""
    
    startup_script.write_text(content)
    startup_script.chmod(0o755)
    
    print(f"✅ Startup script created: {startup_script}")
    print(f"   Run with: ./{startup_script.name}")


def check_prerequisites():
    """Check if required tools are installed"""
    print("📋 Checking prerequisites...\n")
    
    # Check Python
    try:
        result = subprocess.run([sys.executable, "--version"], capture_output=True, text=True)
        print(f"✅ Python: {result.stdout.strip()}")
    except Exception as e:
        print(f"❌ Python check failed: {e}")
        return False
    
    # Check virtual environment
    venv_path = BASE_DIR / ".venv"
    if venv_path.exists():
        print(f"✅ Virtual environment: {venv_path}")
    else:
        print(f"⚠️  Virtual environment not found: {venv_path}")
        print("   Run: ./setup_environments.sh")
    
    # Check service manager
    if SERVICE_MANAGER.exists():
        print(f"✅ Service manager: {SERVICE_MANAGER}")
    else:
        print(f"❌ Service manager not found: {SERVICE_MANAGER}")
        return False
    
    # Check systemd
    try:
        subprocess.run(["systemctl", "--version"], capture_output=True, check=True)
        print("✅ Systemd available")
    except:
        print("⚠️  Systemd not available (cron fallback available)")
    
    # Check cron
    try:
        subprocess.run(["crontab", "-l"], capture_output=True)
        print("✅ Cron available")
    except:
        print("⚠️  Cron not available")
    
    print()
    return True


if __name__ == "__main__":
    print("🚀 OmniCortex Linux Scheduler Setup\n")
    
    if not check_prerequisites():
        print("\n❌ Prerequisites check failed. Please fix issues above.")
        sys.exit(1)
    
    service_file = create_systemd_service()
    cron_script = create_cron_job()
    create_startup_script()
    
    print_instructions(service_file, cron_script)
    
    print("✅ Setup complete!")
