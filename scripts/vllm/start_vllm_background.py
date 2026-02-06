"""
Start vLLM server in background (Windows compatible)
"""
import subprocess
import sys
import time
import os

def start_vllm():
    """Start vLLM server as background process"""
    
    # Disable uvloop for Windows compatibility
    env = os.environ.copy()
    env["VLLM_USE_UVLOOP"] = "0"
    
    cmd = [
        sys.executable,
        "-m", "vllm.entrypoints.openai.api_server",
        "--model", "TheBloke/Llama-2-7B-Chat-GPTQ",
        "--host", "0.0.0.0",
        "--port", "8000",
        "--dtype", "auto",
        "--max-model-len", "2048",
        "--gpu-memory-utilization", "0.85",
        "--max-num-seqs", "15",
        "--quantization", "gptq",
        "--disable-log-requests"
    ]
    
    print("="*60)
    print("Starting vLLM Server for 10 Agents")
    print("="*60)
    print(f"\nModel: TheBloke/Llama-2-7B-Chat-GPTQ")
    print(f"Port: 8000")
    print(f"Max Concurrent: 15 requests")
    print(f"\n⏳ First run will download model (~4.5 GB)")
    print(f"   This may take 5-10 minutes...")
    print(f"\n💡 Server will run in this window")
    print(f"   Press Ctrl+C to stop")
    print("="*60)
    print()
    
    try:
        # Start server (blocking) with Windows-compatible environment
        subprocess.run(cmd, env=env)
    except KeyboardInterrupt:
        print("\n\n⚠️ Server stopped by user")
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    start_vllm()
