"""
Test vLLM setup and benchmark performance
"""
import time
import asyncio
from openai import OpenAI, AsyncOpenAI
import sys

# Configuration
VLLM_ENDPOINTS = [
    "http://localhost:8001/v1",
    "http://localhost:8002/v1",
    "http://localhost:8003/v1",
]

MODEL = "meta-llama/Meta-Llama-3.1-8B-Instruct"


def test_single_request():
    """Test a single request to vLLM"""
    print("\n🧪 Testing single request...")
    
    client = OpenAI(
        base_url=VLLM_ENDPOINTS[0],
        api_key="not-needed"
    )
    
    start = time.time()
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "user", "content": "Hello! Tell me a short joke."}
        ],
        max_tokens=100
    )
    latency = time.time() - start
    
    print(f"✅ Response received in {latency:.2f}s")
    print(f"📝 Response: {response.choices[0].message.content}")
    print(f"📊 Tokens: {response.usage.total_tokens}")
    
    return latency


async def test_concurrent_requests(num_requests=10):
    """Test concurrent requests"""
    print(f"\n🧪 Testing {num_requests} concurrent requests...")
    
    client = AsyncOpenAI(
        base_url=VLLM_ENDPOINTS[0],
        api_key="not-needed"
    )
    
    async def single_request(request_id):
        start = time.time()
        try:
            response = await client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "user", "content": f"Request {request_id}: What is 2+2?"}
                ],
                max_tokens=50
            )
            latency = time.time() - start
            return {
                "id": request_id,
                "latency": latency,
                "tokens": response.usage.total_tokens,
                "success": True
            }
        except Exception as e:
            return {
                "id": request_id,
                "latency": time.time() - start,
                "error": str(e),
                "success": False
            }
    
    # Run concurrent requests
    start_time = time.time()
    tasks = [single_request(i) for i in range(num_requests)]
    results = await asyncio.gather(*tasks)
    total_time = time.time() - start_time
    
    # Analyze results
    successful = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]
    
    if successful:
        latencies = [r["latency"] for r in successful]
        tokens = [r["tokens"] for r in successful]
        
        print(f"\n✅ Results:")
        print(f"   Total time: {total_time:.2f}s")
        print(f"   Successful: {len(successful)}/{num_requests}")
        print(f"   Failed: {len(failed)}")
        print(f"   Avg latency: {sum(latencies)/len(latencies):.2f}s")
        print(f"   Min latency: {min(latencies):.2f}s")
        print(f"   Max latency: {max(latencies):.2f}s")
        print(f"   Avg tokens: {sum(tokens)/len(tokens):.0f}")
        print(f"   Throughput: {num_requests/total_time:.2f} req/s")
    
    if failed:
        print(f"\n❌ Failed requests:")
        for r in failed:
            print(f"   Request {r['id']}: {r['error']}")
    
    return results


def test_load_balancing():
    """Test load balancing across multiple endpoints"""
    print(f"\n🧪 Testing load balancing across {len(VLLM_ENDPOINTS)} endpoints...")
    
    import random
    
    for i in range(10):
        endpoint = random.choice(VLLM_ENDPOINTS)
        client = OpenAI(base_url=endpoint, api_key="not-needed")
        
        try:
            start = time.time()
            response = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": f"Request {i}"}],
                max_tokens=20
            )
            latency = time.time() - start
            print(f"   ✅ Request {i} → {endpoint} ({latency:.2f}s)")
        except Exception as e:
            print(f"   ❌ Request {i} → {endpoint} failed: {e}")


async def benchmark_50_agents():
    """Simulate 50 concurrent agents"""
    print("\n🚀 Benchmarking 50 concurrent agents...")
    print("   This simulates your production load")
    
    # Use all endpoints with round-robin
    clients = [
        AsyncOpenAI(base_url=endpoint, api_key="not-needed")
        for endpoint in VLLM_ENDPOINTS
    ]
    
    async def agent_conversation(agent_id):
        client = clients[agent_id % len(clients)]
        
        messages = [
            f"Agent {agent_id}: What is your name?",
            f"Agent {agent_id}: Tell me about yourself.",
            f"Agent {agent_id}: What can you help me with?"
        ]
        
        total_latency = 0
        total_tokens = 0
        
        for msg in messages:
            try:
                start = time.time()
                response = await client.chat.completions.create(
                    model=MODEL,
                    messages=[{"role": "user", "content": msg}],
                    max_tokens=100
                )
                latency = time.time() - start
                total_latency += latency
                total_tokens += response.usage.total_tokens
            except Exception as e:
                print(f"   ❌ Agent {agent_id} error: {e}")
                return None
        
        return {
            "agent_id": agent_id,
            "total_latency": total_latency,
            "total_tokens": total_tokens,
            "avg_latency": total_latency / len(messages)
        }
    
    # Run 50 agents concurrently
    start_time = time.time()
    tasks = [agent_conversation(i) for i in range(50)]
    results = await asyncio.gather(*tasks)
    total_time = time.time() - start_time
    
    # Filter successful results
    results = [r for r in results if r is not None]
    
    if results:
        latencies = [r["avg_latency"] for r in results]
        tokens = [r["total_tokens"] for r in results]
        
        print(f"\n✅ 50 Agent Benchmark Results:")
        print(f"   Total time: {total_time:.2f}s")
        print(f"   Successful agents: {len(results)}/50")
        print(f"   Avg latency per message: {sum(latencies)/len(latencies):.2f}s")
        print(f"   Min latency: {min(latencies):.2f}s")
        print(f"   Max latency: {max(latencies):.2f}s")
        print(f"   Total tokens: {sum(tokens)}")
        print(f"   Throughput: {len(results)*3/total_time:.2f} msg/s")
        
        # Cost estimate
        cost_per_1m_tokens = 0.0  # Free for self-hosted
        print(f"\n💰 Cost Analysis:")
        print(f"   Total tokens: {sum(tokens)}")
        print(f"   Cost (self-hosted): $0.00")
        print(f"   Cost (GROQ): ${sum(tokens)/1_000_000 * 0.27:.2f}")
        print(f"   Savings: 100%")


def main():
    print("="*60)
    print("vLLM Testing & Benchmarking Suite")
    print("="*60)
    
    # Check if vLLM is running
    print("\n🔍 Checking vLLM endpoints...")
    for endpoint in VLLM_ENDPOINTS:
        try:
            client = OpenAI(base_url=endpoint, api_key="not-needed")
            models = client.models.list()
            print(f"   ✅ {endpoint} - OK")
        except Exception as e:
            print(f"   ❌ {endpoint} - {e}")
            print(f"\n⚠️ Please start vLLM first:")
            print(f"   ./start_vllm_cluster.sh 3 8001")
            sys.exit(1)
    
    # Run tests
    try:
        # Test 1: Single request
        test_single_request()
        
        # Test 2: Concurrent requests
        asyncio.run(test_concurrent_requests(10))
        
        # Test 3: Load balancing
        if len(VLLM_ENDPOINTS) > 1:
            test_load_balancing()
        
        # Test 4: 50 agent benchmark
        print("\n" + "="*60)
        response = input("Run 50 agent benchmark? (y/n): ")
        if response.lower() == 'y':
            asyncio.run(benchmark_50_agents())
        
        print("\n" + "="*60)
        print("✅ All tests completed!")
        print("="*60)
        
    except KeyboardInterrupt:
        print("\n\n⚠️ Tests interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
