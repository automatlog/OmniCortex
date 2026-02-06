"""
Quick check if vLLM server is running and ready
"""
import requests
import sys

def check_vllm():
    """Check if vLLM is running"""
    
    print("🔍 Checking vLLM server status...")
    print()
    
    try:
        # Try to connect
        response = requests.get("http://localhost:8000/v1/models", timeout=2)
        
        if response.status_code == 200:
            data = response.json()
            model = data["data"][0]["id"]
            
            print("✅ vLLM Server is RUNNING")
            print(f"   URL: http://localhost:8000")
            print(f"   Model: {model}")
            print()
            print("🎉 Ready to use!")
            print()
            print("Next steps:")
            print("1. Update .env: USE_VLLM=true")
            print("2. Run: python test_fixes.py")
            return True
        else:
            print(f"⚠️ Server responded with status {response.status_code}")
            return False
            
    except requests.exceptions.ConnectionError:
        print("❌ vLLM Server is NOT running")
        print()
        print("To start the server:")
        print("1. Open a new terminal")
        print("2. cd OmniCortex")
        print("3. python start_vllm_background.py")
        print()
        print("First run will download model (~4.5 GB, 5-10 min)")
        return False
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    success = check_vllm()
    sys.exit(0 if success else 1)
