"""
Windows Task Scheduler Setup for OmniCortex Services
Creates scheduled tasks to run vLLM and Moshi services on Windows startup
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
PYTHON_EXE = sys.executable
SERVICE_MANAGER = BASE_DIR / "scripts" / "service_manager.py"


def create_task_xml(task_name: str, description: str, command: str) -> str:
    """Generate Windows Task Scheduler XML"""
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>{description}</Description>
  </RegistrationInfo>
  <Triggers>
    <BootTrigger>
      <Enabled>true</Enabled>
    </BootTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{PYTHON_EXE}</Command>
      <Arguments>{command}</Arguments>
      <WorkingDirectory>{BASE_DIR}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>"""


def setup_windows_task():
    """Create Windows scheduled task"""
    task_name = "OmniCortex_Services"
    xml_file = BASE_DIR / "storage" / "omnicortex_task.xml"
    
    # Create XML
    xml_content = create_task_xml(
        task_name=task_name,
        description="OmniCortex vLLM and Moshi API Services",
        command=f'"{SERVICE_MANAGER}" monitor'
    )
    
    # Save XML
    xml_file.parent.mkdir(parents=True, exist_ok=True)
    xml_file.write_text(xml_content, encoding='utf-16')
    
    print(f"✅ Task XML created: {xml_file}")
    print("\n" + "="*60)
    print("WINDOWS TASK SCHEDULER SETUP")
    print("="*60)
    print("\nOption 1: Automatic (requires admin)")
    print("-" * 60)
    print("Run this command in an ADMINISTRATOR PowerShell:")
    print(f'schtasks /Create /TN "{task_name}" /XML "{xml_file}" /F')
    
    print("\n\nOption 2: Manual Setup")
    print("-" * 60)
    print("1. Open Task Scheduler (taskschd.msc)")
    print("2. Click 'Import Task...'")
    print(f"3. Select: {xml_file}")
    print("4. Click OK")
    
    print("\n\nOption 3: Run as Windows Service (Advanced)")
    print("-" * 60)
    print("Install NSSM (Non-Sucking Service Manager):")
    print("  choco install nssm")
    print("\nThen run:")
    print(f'  nssm install OmniCortex "{PYTHON_EXE}" "{SERVICE_MANAGER}" monitor')
    print("  nssm start OmniCortex")
    
    print("\n" + "="*60 + "\n")


def create_startup_batch():
    """Create a simple batch file for manual startup"""
    batch_file = BASE_DIR / "start_services.bat"
    
    content = f"""@echo off
echo Starting OmniCortex Services...
cd /d "{BASE_DIR}"
"{PYTHON_EXE}" "{SERVICE_MANAGER}" monitor
pause
"""
    
    batch_file.write_text(content)
    print(f"✅ Startup batch file created: {batch_file}")
    print("   Double-click this file to start services manually")


if __name__ == "__main__":
    print("🚀 OmniCortex Windows Scheduler Setup\n")
    
    setup_windows_task()
    create_startup_batch()
    
    print("\n✅ Setup complete!")
    print("\nTo start services now:")
    print(f'  python "{SERVICE_MANAGER}" monitor')
