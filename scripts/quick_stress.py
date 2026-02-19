
import asyncio
import httpx
import time
import random
import argparse
import os

# Configuration
DEFAULT_API_URL = "http://localhost:8000/query"
DEFAULT_CONCURRENT_REQUESTS = 5
DEFAULT_TOTAL_REQUESTS = 20

# Sample Questions to vary traffic
QUESTIONS = [
    "Who are you?",
    "What can you do?",
    "Tell me a joke.",
    "Summarize your capabilities.",
    "Give me a short poem.",
]

async def send_request(client, agent_id, request_id, api_key):
    """Sends a single request and returns latency in seconds."""
    question = random.choice(QUESTIONS)
    payload = {
        "question": question,
        "agent_id": agent_id,
        "stream": False
    }
    headers = {}
    if api_key:
        headers["X-API-Key"] = api_key
    
    start_time = time.perf_counter()
    try:
        response = await client.post(DEFAULT_API_URL, json=payload, headers=headers, timeout=60.0)
        end_time = time.perf_counter()
        latency = end_time - start_time
        
        status = response.status_code
        if status == 200:
            print(f"✅ Req #{request_id}: {latency:.2f}s | {question}")
            return latency
        else:
            print(f"❌ Req #{request_id}: Failed ({status}) | {latency:.2f}s")
            return None
    except Exception as e:
        print(f"⚠️ Req #{request_id}: Error {e}")
        return None

async def run_stress_test(agent_id, concurrent, total, api_key):
    print(f"\n🚀 Starting Stress Test")
    print(f"Target: {DEFAULT_API_URL}")
    print(f"Agent ID: {agent_id}")
    print(f"Concurrency: {concurrent}")
    print(f"Total Requests: {total}\n")

    async with httpx.AsyncClient() as client:
        tasks = []
        latencies = []
        
        start_global = time.perf_counter()
        
        # Simple batch processing for now to respect total count roughly
        for i in range(0, total, concurrent):
            batch_size = min(concurrent, total - i)
            batch_tasks = [send_request(client, agent_id, i + j + 1, api_key) for j in range(batch_size)]
            results = await asyncio.gather(*batch_tasks)
            latencies.extend([r for r in results if r is not None])
            
        end_global = time.perf_counter()
        total_duration = end_global - start_global
        
        # Reporting
        if latencies:
            avg_latency = sum(latencies) / len(latencies)
            max_latency = max(latencies)
            min_latency = min(latencies)
            throughput = len(latencies) / total_duration
            
            print("\n" + "="*40)
            print("📊 STRESS TEST RESULTS")
            print("="*40)
            print(f"Total Successful: {len(latencies)}/{total}")
            print(f"Total Duration:   {total_duration:.2f}s")
            print(f"Throughput:       {throughput:.2f} req/s")
            print(f"Average Latency:  {avg_latency:.2f}s")
            print(f"Min Latency:      {min_latency:.2f}s")
            print(f"Max Latency:      {max_latency:.2f}s")
            print("="*40 + "\n")
        else:
            print("\n❌ All requests failed.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Quick Stress Test for OmniCortex")
    parser.add_argument("--agent-id", required=True, help="Agent ID to test against")
    parser.add_argument("--concurrent", type=int, default=DEFAULT_CONCURRENT_REQUESTS, help="Concurrent requests")
    parser.add_argument("--total", type=int, default=DEFAULT_TOTAL_REQUESTS, help="Total requests to send")
    parser.add_argument("--api-key", required=False, help="API Key for authentication")
    
    args = parser.parse_args()
    
    asyncio.run(run_stress_test(args.agent_id, args.concurrent, args.total, args.api_key))
