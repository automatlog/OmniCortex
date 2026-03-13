import os
import sys
import socket
from dotenv import load_dotenv

# Load .env
load_dotenv()

print("--- Environment Variables ---")
print(f"VLLM1_BASE_URL: {os.getenv('VLLM1_BASE_URL')}")
print(f"VLLM1_MODEL: {os.getenv('VLLM1_MODEL')}")
print(f"VLLM2_BASE_URL: {os.getenv('VLLM2_BASE_URL')}")
print(f"VLLM2_MODEL: {os.getenv('VLLM2_MODEL')}")
print(f"VLLM_BASE_URL (legacy): {os.getenv('VLLM_BASE_URL')}")
print(f"LLAMA_BASE_URL (legacy): {os.getenv('LLAMA_BASE_URL')}")
print(f"DATABASE_URL: {os.getenv('DATABASE_URL')}")

print("\n--- Network Connectivity ---")
def check_port(host, port):
    try:
        sock = socket.create_connection((host, port), timeout=2)
        sock.close()
        return True
    except (socket.timeout, ConnectionRefusedError):
        return False

print(f"Port 8080 (vLLM): {'OPEN' if check_port('localhost', 8080) else 'CLOSED'}")
print(f"Port 8081 (vLLM): {'OPEN' if check_port('localhost', 8081) else 'CLOSED'}")
print(f"Port 11434 (Ollama): {'OPEN' if check_port('localhost', 11434) else 'CLOSED'}")

print("\n--- Torchvision Import Test ---")
try:
    import torch
    print(f"Torcb version: {torch.__version__}")
    import torchvision
    print(f"Torchvision version: {torchvision.__version__}")
except Exception as e:
    print(f"Import Error: {e}")
