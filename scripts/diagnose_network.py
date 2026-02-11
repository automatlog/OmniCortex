#!/usr/bin/env python3
"""
Network Diagnostics Script for OmniCortex
Tests connectivity and configuration between Frontend and Backend
"""
import requests
import socket
import sys
from typing import Dict, List, Tuple

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    END = '\033[0m'

def print_header(text: str):
    print(f"\n{Colors.BLUE}{'='*60}{Colors.END}")
    print(f"{Colors.BLUE}{text:^60}{Colors.END}")
    print(f"{Colors.BLUE}{'='*60}{Colors.END}\n")

def print_success(text: str):
    print(f"{Colors.GREEN}✅ {text}{Colors.END}")

def print_error(text: str):
    print(f"{Colors.RED}❌ {text}{Colors.END}")

def print_warning(text: str):
    print(f"{Colors.YELLOW}⚠️  {text}{Colors.END}")

def print_info(text: str):
    print(f"ℹ️  {text}")

def check_port_available(port: int, host: str = "localhost") -> bool:
    """Check if a port is available (not in use)"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    try:
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0  # 0 means port is in use (service running)
    except:
        return False

def check_backend_reachability() -> Tuple[bool, str]:
    """Test if backend is reachable"""
    try:
        response = requests.get("http://localhost:8000/", timeout=5)
        if response.status_code == 200:
            return True, "Backend reachable and responding"
        else:
            return False, f"Backend returned status {response.status_code}"
    except requests.exceptions.ConnectionError:
        return False, "Cannot connect to backend (connection refused)"
    except requests.exceptions.Timeout:
        return False, "Backend connection timed out"
    except Exception as e:
        return False, f"Backend check failed: {e}"

def check_health_endpoint() -> Tuple[bool, str, Dict]:
    """Test health endpoint"""
    try:
        response = requests.get("http://localhost:8000/health", timeout=5)
        data = response.json()
        
        if response.status_code == 200:
            return True, "Health endpoint working", data
        else:
            return False, f"Health endpoint returned {response.status_code}", data
    except Exception as e:
        return False, f"Health endpoint failed: {e}", {}

def check_cors_configuration() -> Tuple[bool, str]:
    """Test CORS configuration"""
    try:
        # Simulate a preflight request
        response = requests.options(
            "http://localhost:8000/agents",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
            timeout=5
        )
        
        cors_headers = {
            "Access-Control-Allow-Origin": response.headers.get("Access-Control-Allow-Origin"),
            "Access-Control-Allow-Methods": response.headers.get("Access-Control-Allow-Methods"),
            "Access-Control-Allow-Headers": response.headers.get("Access-Control-Allow-Headers"),
        }
        
        if cors_headers["Access-Control-Allow-Origin"]:
            return True, "CORS configured correctly"
        else:
            return False, "CORS headers missing"
    except Exception as e:
        return False, f"CORS check failed: {e}"

def check_port_conflicts() -> List[Tuple[int, bool, str]]:
    """Check for port conflicts"""
    ports = [
        (3000, "Next.js Frontend"),
        (8000, "FastAPI Backend"),
        (5433, "PostgreSQL"),
        (11434, "Ollama"),
    ]
    
    results = []
    for port, service in ports:
        in_use = check_port_available(port)
        results.append((port, in_use, service))
    
    return results

def provide_remediation(issues: List[str]):
    """Provide specific remediation steps"""
    print_header("Remediation Steps")
    
    if not issues:
        print_success("No issues detected!")
        return
    
    for i, issue in enumerate(issues, 1):
        print(f"\n{i}. {issue}")
        
        if "Backend not reachable" in issue:
            print_info("   → Start backend: python api.py")
            print_info("   → Check if port 8000 is available")
            print_info("   → Verify PostgreSQL and Ollama are running")
        
        elif "CORS" in issue:
            print_info("   → Check CORS middleware in api.py")
            print_info("   → Ensure http://localhost:3000 is in allow_origins")
            print_info("   → Restart backend after changes")
        
        elif "Health endpoint" in issue:
            print_info("   → Verify /health endpoint exists in api.py")
            print_info("   → Check database and Ollama connectivity")
            print_info("   → Review backend logs for errors")
        
        elif "Port" in issue and "conflict" in issue:
            print_info("   → Stop the conflicting service")
            print_info("   → Or change the port in configuration")
        
        elif "PostgreSQL" in issue:
            print_info("   → Start PostgreSQL: docker-compose up -d postgres")
            print_info("   → Or: pg_ctl start -D /path/to/data")
        
        elif "Ollama" in issue:
            print_info("   → Start Ollama: ollama serve")
            print_info("   → Pull model: ollama pull llama3.2:3b")

def main():
    print_header("OmniCortex Network Diagnostics")
    
    issues = []
    
    # Test 1: Backend Reachability
    print_info("Test 1: Backend Reachability")
    reachable, message = check_backend_reachability()
    if reachable:
        print_success(message)
    else:
        print_error(message)
        issues.append(f"Backend not reachable: {message}")
    print()
    
    # Test 2: Health Endpoint
    print_info("Test 2: Health Endpoint")
    healthy, message, data = check_health_endpoint()
    if healthy:
        print_success(message)
        if data:
            db_status = data.get("services", {}).get("database", {}).get("status")
            ollama_status = data.get("services", {}).get("ollama", {}).get("status")
            
            if db_status == "up":
                print_success(f"  Database: {db_status}")
            else:
                print_error(f"  Database: {db_status}")
                issues.append("Database not accessible")
            
            if ollama_status == "up":
                print_success(f"  Ollama: {ollama_status}")
            else:
                print_error(f"  Ollama: {ollama_status}")
                issues.append("Ollama not accessible")
    else:
        print_error(message)
        issues.append(f"Health endpoint issue: {message}")
    print()
    
    # Test 3: CORS Configuration
    print_info("Test 3: CORS Configuration")
    cors_ok, message = check_cors_configuration()
    if cors_ok:
        print_success(message)
    else:
        print_error(message)
        issues.append(f"CORS configuration issue: {message}")
    print()
    
    # Test 4: Port Conflicts
    print_info("Test 4: Port Status")
    port_results = check_port_conflicts()
    for port, in_use, service in port_results:
        if in_use:
            print_success(f"Port {port} ({service}): In use ✓")
        else:
            print_warning(f"Port {port} ({service}): Not in use")
            if port in [8000, 5433, 11434]:
                issues.append(f"Port {port} ({service}) not in use - service may not be running")
    print()
    
    # Summary
    print_header("Diagnostic Summary")
    if not issues:
        print_success("All checks passed! ✓")
        print_info("\nYour OmniCortex setup is correctly configured.")
        print_info("Frontend should be able to communicate with Backend.")
    else:
        print_error(f"Found {len(issues)} issue(s)")
        provide_remediation(issues)
    
    print("\n" + "="*60 + "\n")
    
    return 0 if not issues else 1

if __name__ == "__main__":
    sys.exit(main())
