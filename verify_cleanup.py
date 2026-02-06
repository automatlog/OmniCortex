#!/usr/bin/env python3
"""
Verify Cleanup - Check that all files are properly organized
"""
import os
from pathlib import Path

def check_file_exists(path, should_exist=True):
    """Check if file exists and matches expectation"""
    exists = Path(path).exists()
    status = "✅" if exists == should_exist else "❌"
    expectation = "EXISTS" if should_exist else "NOT EXISTS"
    actual = "EXISTS" if exists else "NOT EXISTS"
    
    if exists == should_exist:
        print(f"{status} {path} - {expectation}")
        return True
    else:
        print(f"{status} {path} - Expected: {expectation}, Actual: {actual}")
        return False

def main():
    print("🔍 Verifying Cleanup...\n")
    
    all_good = True
    
    # Check production scripts exist
    print("📁 Production Scripts (should exist):")
    production_scripts = [
        "scripts/service_manager.py",
        "scripts/setup_linux_scheduler.py",
        "scripts/setup_windows_scheduler.py",
        "scripts/create_bulk_agents.py",
        "scripts/reingest_documents.py",
        "scripts/deploy_remote.sh",
    ]
    for script in production_scripts:
        all_good &= check_file_exists(script, should_exist=True)
    
    print("\n📁 Test Files (should exist in tests/):")
    test_files = [
        "tests/test_api.py",
        "tests/test_agents.py",
        "tests/test_vllm.py",
        "tests/quick_test_vllm.py",
        "tests/check_vllm_status.py",
        "tests/agent_questions_data.py",
        "tests/create_agent_test_suite.py",
        "tests/generate_agent_tests.py",
        "tests/evaluate_rag.py",
        "tests/locustfile.py",
        "tests/stress_test_heavy.py",
    ]
    for test_file in test_files:
        all_good &= check_file_exists(test_file, should_exist=True)
    
    print("\n🗑️ Redundant Files (should NOT exist):")
    redundant_files = [
        "scripts/vllm/start_vllm_background.py",
        "scripts/vllm/start_vllm.sh",
        "scripts/create_42_agents.py",
        "scripts/run_vllm_moshi_servers.py",
        "scripts/nuclear_fix.sh",
        "scripts/start.sh",
        "scripts/start_personaplex.sh",
        "scripts/agent_questions_data.py",
        "scripts/create_agent_test_suite.py",
        "scripts/generate_agent_tests.py",
    ]
    for redundant in redundant_files:
        all_good &= check_file_exists(redundant, should_exist=False)
    
    print("\n📂 Empty Folders (should NOT exist):")
    empty_folders = [
        "scripts/vllm",
    ]
    for folder in empty_folders:
        path = Path(folder)
        if path.exists():
            if not any(path.iterdir()):
                print(f"⚠️ {folder} - EXISTS but EMPTY (should be removed)")
                all_good = False
            else:
                print(f"✅ {folder} - EXISTS and NOT EMPTY")
        else:
            print(f"✅ {folder} - NOT EXISTS")
    
    print("\n" + "="*60)
    if all_good:
        print("✅ ALL CHECKS PASSED - Cleanup successful!")
    else:
        print("❌ SOME CHECKS FAILED - Review issues above")
    print("="*60)
    
    return 0 if all_good else 1

if __name__ == "__main__":
    exit(main())
