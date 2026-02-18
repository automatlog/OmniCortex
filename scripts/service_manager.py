"""
OmniCortex Service Manager
Manages vLLM and Moshi API servers with:
- Auto-restart on failure
- Rotating log files
- Health checks
- Process monitoring
- Scheduled tasks (cron-like)
"""
import subprocess
import sys
import os
import time
import logging
from datetime import datetime
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Optional, Dict, List
import psutil
import signal
from dotenv import load_dotenv

# Load environment variables (HF_TOKEN, etc.)
load_dotenv()

# ============== CONFIGURATION ==============
BASE_DIR = Path(__file__).parent.parent
LOG_DIR = BASE_DIR / "storage" / "logs"
PID_DIR = BASE_DIR / "storage" / "pids"

# Ensure directories exist
LOG_DIR.mkdir(parents=True, exist_ok=True)
PID_DIR.mkdir(parents=True, exist_ok=True)

# Read model from environment (or .env file via dotenv loaded above)
VLLM_MODEL = os.getenv("VLLM_MODEL", "meta-llama/Llama-3.1-8B-Instruct")

# Service Configurations
SERVICES = {
    "vllm": {
        "cmd": [
            "python", "-m", "vllm.entrypoints.openai.api_server",
            "--model", VLLM_MODEL,
            "--host", "0.0.0.0",
            "--port", "8080",
            "--dtype", "auto",
            "--max-model-len", "8192",
            "--gpu-memory-utilization", "0.45",
            "--max-num-seqs", "100",
            "--disable-log-requests"
        ],
        "venv": ".venv",  # Virtual environment to use
        "env": {"VLLM_USE_UVLOOP": "0"},
        "health_url": "http://localhost:8080/health",
        "health_interval": 60,  # Check every 60 seconds
        "restart_delay": 10,
        "max_restarts": 5,
        "log_file": "vllm_server.log",
        "enabled": True
    },
    "moshi": {
        "cmd": ["python", "-m", "moshi.server", "--port", "8998"],
        "venv": ".moshi-venv",  # Virtual environment to use
        "env": None,
        "health_url": "http://localhost:8998",
        "health_interval": 60,
        "restart_delay": 10,
        "max_restarts": 5,
        "log_file": "moshi_server.log",
        "enabled": True
    },
    "api": {
        "cmd": ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"],
        "venv": ".venv",
        "env": None,
        "health_url": "http://localhost:8000/",
        "health_interval": 30,
        "restart_delay": 5,
        "max_restarts": 10,
        "log_file": "api_server.log",
        "enabled": True
    },
    "admin": {
        "cmd": ["npm", "run", "start"],  # Requires 'npm run build' first
        "venv": None,
        "cwd": "admin",  # Special handling needed in ServiceProcess for cwd?
        "env": None,
        "health_url": "http://localhost:3000",
        "health_interval": 60,
        "restart_delay": 10,
        "max_restarts": 5,
        "log_file": "admin_ui.log",
        "enabled": True
    }
}

# Ensure service log files exist up front.
for _service in SERVICES.values():
    (LOG_DIR / _service["log_file"]).touch(exist_ok=True)


# ============== LOGGING SETUP ==============
def setup_logger(name: str, log_file: str, level=logging.INFO) -> logging.Logger:
    """Create a rotating file logger"""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Rotating file handler (10MB per file, keep 5 backups)
    handler = RotatingFileHandler(
        LOG_DIR / log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    
    # Also log to console
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)
    
    return logger


# Main logger
main_logger = setup_logger("service_manager", "service_manager.log")


# ============== SERVICE MANAGER ==============
class ServiceProcess:
    """Manages a single service process"""
    
    def __init__(self, name: str, config: Dict):
        self.name = name
        self.config = config
        self.process: Optional[subprocess.Popen] = None
        self.restart_count = 0
        self.last_restart = None
        self.logger = setup_logger(f"{name}_service", config["log_file"])
        self.pid_file = PID_DIR / f"{name}.pid"
        
    def start(self) -> bool:
        """Start the service"""
        if not self.config.get("enabled", True):
            self.logger.info(f"Service {self.name} is disabled")
            return False
            
        if self.is_running():
            self.logger.warning(f"Service {self.name} is already running (PID: {self.process.pid})")
            return True
        
        try:
            # Prepare environment
            env = os.environ.copy()
            if self.config.get("env"):
                env.update(self.config["env"])
            
            # Activate virtual environment if specified
            venv_path = self.config.get("venv")
            if venv_path:
                venv_bin = BASE_DIR / venv_path / "bin"
                env["PATH"] = f"{venv_bin}:{env.get('PATH', '')}"
                env["VIRTUAL_ENV"] = str(BASE_DIR / venv_path)
            
            # Start process
            self.logger.info(f"Starting {self.name} service...")
            self.logger.info(f"Command: {' '.join(self.config['cmd'])}")
            
            log_file = LOG_DIR / self.config["log_file"]
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"\n\n{'='*60}\n")
                f.write(f"Service started at {datetime.now()}\n")
                f.write(f"{'='*60}\n\n")
                
                self.process = subprocess.Popen(
                    self.config["cmd"],
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    env=env,
                    cwd=BASE_DIR / self.config.get("cwd", ".")
                )
            
            # Save PID
            self.pid_file.write_text(str(self.process.pid))
            
            self.logger.info(f"✅ {self.name} started (PID: {self.process.pid})")
            self.last_restart = datetime.now()
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to start {self.name}: {e}")
            return False
    
    def stop(self, timeout: int = 30) -> bool:
        """Stop the service gracefully"""
        if not self.is_running():
            self.logger.info(f"{self.name} is not running")
            return True
        
        try:
            self.logger.info(f"Stopping {self.name} (PID: {self.process.pid})...")
            
            # Try graceful shutdown first
            self.process.terminate()
            
            try:
                self.process.wait(timeout=timeout)
                self.logger.info(f"✅ {self.name} stopped gracefully")
            except subprocess.TimeoutExpired:
                self.logger.warning(f"⚠️ {self.name} didn't stop gracefully, forcing...")
                self.process.kill()
                self.process.wait()
                self.logger.info(f"✅ {self.name} force stopped")
            
            # Clean up PID file
            if self.pid_file.exists():
                self.pid_file.unlink()
            
            self.process = None
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to stop {self.name}: {e}")
            return False
    
    def restart(self) -> bool:
        """Restart the service"""
        self.logger.info(f"Restarting {self.name}...")
        self.stop()
        time.sleep(self.config.get("restart_delay", 5))
        return self.start()
    
    def is_running(self) -> bool:
        """Check if process is running"""
        if self.process is None:
            return False
        
        # Check if process is still alive
        if self.process.poll() is not None:
            self.process = None
            return False
        
        return True
    
    def check_health(self) -> bool:
        """Check service health via HTTP endpoint"""
        if not self.is_running():
            return False
        
        health_url = self.config.get("health_url")
        if not health_url:
            return True  # No health check configured
        
        try:
            import requests
            response = requests.get(health_url, timeout=5)
            return response.status_code == 200
        except Exception:
            return False
    
    def monitor(self) -> bool:
        """Monitor and auto-restart if needed"""
        if not self.is_running():
            self.logger.warning(f"⚠️ {self.name} is not running")
            
            # Check restart limits
            max_restarts = self.config.get("max_restarts", 5)
            if self.restart_count >= max_restarts:
                self.logger.error(
                    f"❌ {self.name} exceeded max restarts ({max_restarts}). "
                    "Manual intervention required."
                )
                return False
            
            # Restart
            self.logger.info(f"🔄 Auto-restarting {self.name} (attempt {self.restart_count + 1}/{max_restarts})")
            if self.restart():
                self.restart_count += 1
                return True
            return False
        
        # Reset restart counter if running for a while
        if self.last_restart:
            uptime = (datetime.now() - self.last_restart).total_seconds()
            if uptime > 300:  # 5 minutes
                self.restart_count = 0
        
        return True
    
    def get_stats(self) -> Dict:
        """Get process statistics"""
        if not self.is_running():
            return {"status": "stopped"}
        
        try:
            proc = psutil.Process(self.process.pid)
            return {
                "status": "running",
                "pid": self.process.pid,
                "cpu_percent": proc.cpu_percent(interval=1),
                "memory_mb": proc.memory_info().rss / 1024 / 1024,
                "uptime_seconds": (datetime.now() - self.last_restart).total_seconds() if self.last_restart else 0,
                "restart_count": self.restart_count
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}


# ============== MAIN MANAGER ==============
class ServiceManager:
    """Manages all services"""
    
    def __init__(self):
        self.services: Dict[str, ServiceProcess] = {}
        self.running = False
        
        # Initialize services
        for name, config in SERVICES.items():
            self.services[name] = ServiceProcess(name, config)
    
    def start_all(self):
        """Start all enabled services"""
        main_logger.info("🚀 Starting all services...")
        for name, service in self.services.items():
            service.start()
    
    def stop_all(self):
        """Stop all services"""
        main_logger.info("🛑 Stopping all services...")
        for name, service in self.services.items():
            service.stop()
    
    def restart_all(self):
        """Restart all services"""
        main_logger.info("🔄 Restarting all services...")
        for name, service in self.services.items():
            service.restart()
    
    def monitor_loop(self, interval: int = 30):
        """Main monitoring loop"""
        main_logger.info(f"👁️ Starting monitoring loop (interval: {interval}s)")
        self.running = True
        
        try:
            while self.running:
                for name, service in self.services.items():
                    if service.config.get("enabled", True):
                        service.monitor()
                
                time.sleep(interval)
                
        except KeyboardInterrupt:
            main_logger.info("⚠️ Received interrupt signal")
        finally:
            self.stop_all()
    
    def status(self):
        """Print status of all services"""
        print("\n" + "="*60)
        print("SERVICE STATUS")
        print("="*60)
        
        for name, service in self.services.items():
            stats = service.get_stats()
            status = stats.get("status", "unknown")
            
            print(f"\n{name.upper()}:")
            print(f"  Status: {status}")
            
            if status == "running":
                print(f"  PID: {stats['pid']}")
                print(f"  CPU: {stats['cpu_percent']:.1f}%")
                print(f"  Memory: {stats['memory_mb']:.1f} MB")
                print(f"  Uptime: {stats['uptime_seconds']:.0f}s")
                print(f"  Restarts: {stats['restart_count']}")
        
        print("\n" + "="*60 + "\n")


# ============== CLI ==============
def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="OmniCortex Service Manager")
    parser.add_argument(
        "action",
        choices=["start", "stop", "restart", "status", "monitor"],
        help="Action to perform"
    )
    parser.add_argument(
        "--service",
        choices=list(SERVICES.keys()),
        help="Specific service to manage (default: all)"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=30,
        help="Monitoring interval in seconds (default: 30)"
    )
    
    args = parser.parse_args()
    
    manager = ServiceManager()
    
    if args.action == "start":
        if args.service:
            manager.services[args.service].start()
        else:
            manager.start_all()
    
    elif args.action == "stop":
        if args.service:
            manager.services[args.service].stop()
        else:
            manager.stop_all()
    
    elif args.action == "restart":
        if args.service:
            manager.services[args.service].restart()
        else:
            manager.restart_all()
    
    elif args.action == "status":
        manager.status()
    
    elif args.action == "monitor":
        manager.start_all()
        manager.monitor_loop(interval=args.interval)


if __name__ == "__main__":
    main()
