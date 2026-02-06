"""
Quick test script for vLLM setup
Tests basic functionality before running full tests
"""
import sys
import time
from openai import OpenAI

def test_connection():
    """Test if vLLM server is running"""
    print("\n🔍 Testing vLLM connection...")
    
    try:
        client = OpenAI(
            base_url="http://localhost:8000/v1",
            api_key="not-needed"
        )
        
        # List models
        models = client.models.list()
        print(f"✅ Connected to vLLM server")
        print(f"   Available model: {models.data[0].id}")
        return True
        
    except Exception as e:
        print(f"❌ Cannot connect to vLLM server")
        print(f"   Error: {e}")
        print(f"\n💡 Make sure vLLM is running:")
        print(f"   start_vllm_10agents.bat")
        return False


def test_simple_request():
    """Test a simple request"""
    print("\n🧪 Testing simple request...")
    
    client = OpenAI(
        base_url="http://localhost:8000/v1",
        api_key="not-needed"
    )
    
    try:
        start = time.time()
        response = client.chat.completions.create(
            model="TheBloke/Llama-2-7B-Chat-GPTQ",
            messages=[
                {"role": "user", "content": "Say 'Hello, I am working!' in one sentence."}
            ],
            max_tokens=50
        )
        latency = time.time() - start
        
        answer = response.choices[0].message.content
        tokens = response.usage.total_tokens
        
        print(f"✅ Request successful!")
        print(f"   Latency: {latency:.2f}s")
        print(f"   Tokens: {tokens}")
        print(f"   Response: {answer}")
        
        if latency > 2.0:
            print(f"\n⚠️ Warning: Latency is high ({latency:.2f}s)")
            print(f"   Expected: 0.5-1.0s for first request")
            print(f"   This is normal for first request (model loading)")
        
        return True
        
    except Exception as e:
        print(f"❌ Request failed: {e}")
        return False


def test_concurrent_requests():
    """Test 5 concurrent requests"""
    print("\n🧪 Testing 5 concurrent requests...")
    
    import asyncio
    from openai import AsyncOpenAI
    
    async def run_test():
        client = AsyncOpenAI(
            base_url="http://localhost:8000/v1",
            api_key="not-needed"
        )
        
        async def single_request(i):
            start = time.time()
            try:
                response = await client.chat.completions.create(
                    model="TheBloke/Llama-2-7B-Chat-GPTQ",
                    messages=[
                        {"role": "user", "content": f"Request {i}: What is 2+2?"}
                    ],
                    max_tokens=20
                )
                latency = time.time() - start
                return {"id": i, "latency": latency, "success": True}
            except Exception as e:
                return {"id": i, "error": str(e), "success": False}
        
        # Run 5 concurrent requests
        start_time = time.time()
        tasks = [single_request(i) for i in range(5)]
        results = await asyncio.gather(*tasks)
        total_time = time.time() - start_time
        
        successful = [r for r in results if r["success"]]
        failed = [r for r in results if not r["success"]]
        
        if successful:
            latencies = [r["latency"] for r in successful]
            print(f"✅ Concurrent test successful!")
            print(f"   Total time: {total_time:.2f}s")
            print(f"   Successful: {len(successful)}/5")
            print(f"   Avg latency: {sum(latencies)/len(latencies):.2f}s")
            print(f"   Max latency: {max(latencies):.2f}s")
            
            if max(latencies) > 2.0:
                print(f"\n⚠️ Warning: Some requests are slow")
                print(f"   This might indicate GPU memory pressure")
                print(f"   Try closing other GPU applications")
        
        if failed:
            print(f"\n❌ {len(failed)} requests failed:")
            for r in failed:
                print(f"   Request {r['id']}: {r['error']}")
            return False
        
        return True
    
    try:
        return asyncio.run(run_test())
    except Exception as e:
        print(f"❌ Concurrent test failed: {e}")
        return False


def check_gpu():
    """Check GPU status"""
    print("\n🖥️ Checking GPU status...")
    
    import subprocess
    
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu", "--format=csv,noheader"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            info = result.stdout.strip().split(", ")
            gpu_name = info[0]
            mem_used = info[1]
            mem_total = info[2]
            gpu_util = info[3]
            
            print(f"✅ GPU Status:")
            print(f"   Name: {gpu_name}")
            print(f"   Memory: {mem_used} / {mem_total}")
            print(f"   Utilization: {gpu_util}")
            
            # Parse memory
            mem_used_mb = int(mem_used.split()[0])
            mem_total_mb = int(mem_total.split()[0])
            mem_percent = (mem_used_mb / mem_total_mb) * 100
            
            if mem_percent > 95:
                print(f"\n⚠️ Warning: GPU memory is very high ({mem_percent:.0f}%)")
                print(f"   Close other GPU applications")
            elif mem_percent < 50:
                print(f"\n💡 GPU memory usage is low ({mem_percent:.0f}%)")
                print(f"   vLLM might not be running yet")
        else:
            print(f"⚠️ Could not get GPU status")
            
    except FileNotFoundError:
        print(f"⚠️ nvidia-smi not found")
        print(f"   Make sure NVIDIA drivers are installed")
    except Exception as e:
        print(f"⚠️ Error checking GPU: {e}")


def main():
    print("="*60)
    print("vLLM Quick Test")
    print("="*60)
    
    # Check GPU
    check_gpu()
    
    # Test connection
    if not test_connection():
        sys.exit(1)
    
    # Test simple request
    if not test_simple_request():
        sys.exit(1)
    
    # Test concurrent requests
    print("\n" + "="*60)
    response = input("Run concurrent test? (y/n): ")
    if response.lower() == 'y':
        test_concurrent_requests()
    
    print("\n" + "="*60)
    print("✅ All tests passed!")
    print("="*60)
    print("\nYour vLLM setup is working correctly!")
    print("\nNext steps:")
    print("1. Update .env: USE_VLLM=true")
    print("2. Run: python test_fixes.py")
    print("3. Run: python stress_test_full.py")
    print("="*60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️ Test interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
