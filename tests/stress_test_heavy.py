"""
🔥 OmniCortex Heavy Stress Test
Simulates 100 concurrent users interacting with 42 agents.
Mixes Text Query (50%) and Voice Chat (50%).

Usage:
    uv run python tests/stress_test_heavy.py
    
Requirements:
    pip install httpx asyncio
"""
import asyncio
import httpx
import random
import time
import sys
import wave
import io
import math
from typing import List, Dict

# CONFIGURATION
BASE_URL = "http://localhost:8000"
CONCURRENT_USERS = 100
TEST_DURATION_SECONDS = 60  # Run for 60s (or set to 0 for infinite)
THINK_TIME_RANGE = (1.0, 5.0)  # Seconds between requests

# METRICS
STATS = {
    "requests": 0,
    "errors": 0,
    "text_ok": 0,
    "voice_ok": 0,
    "latency": [],
    "start_time": 0
}

def generate_dummy_wav() -> bytes:
    """Generate a 1-second sine wave WAV file in memory"""
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wav_file:
        # Settings: 1 channel, 2 bytes/sample, 44100 rate
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(44100)
        
        # Generate 1 sec of audio
        duration = 1.0
        frequency = 440.0
        n_frames = int(duration * 44100)
        data = bytearray()
        
        for i in range(n_frames):
            value = int(32767.0 * math.sin(2.0 * math.pi * frequency * i / 44100))
            data += value.to_bytes(2, byteorder='little', signed=True)
            
        wav_file.writeframes(data)
        
    return buffer.getvalue()

DUMMY_WAV = generate_dummy_wav()


async def get_agents(client: httpx.AsyncClient) -> List[str]:
    """Fetch all available agent IDs"""
    try:
        resp = await client.get(f"{BASE_URL}/agents")
        resp.raise_for_status()
        agents = resp.json()
        ids = [a['id'] for a in agents]
        print(f"✅ Found {len(ids)} agents.")
        return ids
    except Exception as e:
        print(f"❌ Failed to fetch agents: {e}")
        return []


async def simulate_user(user_id: int, agent_ids: List[str], stop_event: asyncio.Event):
    """Simulate a single user loop"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        while not stop_event.is_set():
            # Pick Agent
            if not agent_ids:
                break
            agent_id = random.choice(agent_ids)
            
            # Pick Mode (Text vs Voice)
            mode = "voice" if random.random() > 0.5 else "text"
            
            t0 = time.time()
            success = False
            
            try:
                if mode == "text":
                    # Text Query
                    payload = {
                        "question": f"User {user_id}: fast check {random.randint(1, 1000)}",
                        "agent_id": agent_id,
                        "max_history": 2,
                        "model_selection": random.choice(["Meta Llama 3.1", "Nemotron"])
                    }
                    resp = await client.post(f"{BASE_URL}/query", json=payload)
                    if resp.status_code == 200:
                        STATS["text_ok"] += 1
                        success = True
                    else:
                        raise Exception(f"HTTP {resp.status_code}")

                else:
                    # Voice Chat (Simulated Upload)
                    # We use /voice/chat endpoint
                    files = {'audio': ('test.wav', DUMMY_WAV, 'audio/wav')}
                    data = {'agent_id': agent_id}
                    resp = await client.post(f"{BASE_URL}/voice/chat", files=files, data=data)
                    if resp.status_code == 200:
                        STATS["voice_ok"] += 1
                        success = True
                    else:
                        raise Exception(f"HTTP {resp.status_code}")

            except Exception as e:
                STATS["errors"] += 1
                # print(f"⚠️ User {user_id} Error: {e}")
            
            finally:
                lat = time.time() - t0
                STATS["requests"] += 1
                STATS["latency"].append(lat)
            
            # Think time
            await asyncio.sleep(random.uniform(*THINK_TIME_RANGE))


async def monitor_results(stop_event: asyncio.Event):
    """Print stats every second"""
    print(f"{'Time':<10} | {'Req/s':<10} | {'Errs':<10} | {'Avg Lat':<10} | {'Text':<8} | {'Voice':<8}")
    print("-" * 70)
    
    start_time = time.time()
    last_reqs = 0
    
    while not stop_event.is_set():
        await asyncio.sleep(1)
        now = time.time()
        elapsed = now - start_time
        
        curr_reqs = STATS["requests"]
        rps = (curr_reqs - last_reqs)
        last_reqs = curr_reqs
        
        avg_lat = 0
        if STATS["latency"]:
            avg_lat = sum(STATS["latency"][-100:]) / min(len(STATS["latency"]), 100)
            
        print(f"{elapsed:<10.1f} | {rps:<10} | {STATS['errors']:<10} | {avg_lat:<10.2f} | {STATS['text_ok']:<8} | {STATS['voice_ok']:<8}")


async def main():
    print(f"🔥 Starting Stress Test: {CONCURRENT_USERS} Users")
    
    # 1. Setup
    async with httpx.AsyncClient() as client:
        # Check API Health
        try:
            await client.get(BASE_URL)
        except:
            print(f"❌ API not running at {BASE_URL}. Start it first!")
            return

        # Get Agents
        agent_ids = await get_agents(client)
        if not agent_ids:
            print("❌ No agents found. create some first!")
            return
            
    # 2. Launch Users
    stop_event = asyncio.Event()
    
    tasks = []
    # User Tasks
    for i in range(CONCURRENT_USERS):
        tasks.append(asyncio.create_task(simulate_user(i, agent_ids, stop_event)))
        
    # Monitor Task
    monitor = asyncio.create_task(monitor_results(stop_event))
    
    # 3. Run
    try:
        if TEST_DURATION_SECONDS > 0:
            await asyncio.sleep(TEST_DURATION_SECONDS)
            stop_event.set()
        else:
            # Infinite run until Ctrl+C
            while True:
                await asyncio.sleep(1)
                
    except KeyboardInterrupt:
        print("\n🛑 Stopping...")
        stop_event.set()
        
    await asyncio.gather(*tasks, return_exceptions=True)
    
    # 4. Final Stats
    total_reqs = STATS["requests"]
    duration = time.time() - STATS.get("start_time", time.time()) # Approx
    
    print("\n" + "="*50)
    print("FINAL RESULTS")
    print("="*50)
    print(f"Total Requests: {total_reqs}")
    print(f"Total Errors:   {STATS['errors']}")
    print(f"Text Selects:   {STATS['text_ok']}")
    print(f"Voice Selects:  {STATS['voice_ok']}")
    if STATS["latency"]:
        print(f"Avg Latency:    {sum(STATS['latency'])/len(STATS['latency']):.2f}s")
    print("="*50)

if __name__ == "__main__":
    STATS["start_time"] = time.time()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
