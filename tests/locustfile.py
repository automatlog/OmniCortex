"""
🦗 Locust Load Testing for OmniCortex
Simulates 1000+ concurrent users to identify infrastructure bottlenecks.

Usage:
    # Install locust first
    uv pip install locust
    
    # Run with web UI (recommended)
    uv run locust -f tests/locustfile.py --host http://localhost:8000
    
    # Run headless (CI/CD)
    uv run locust -f tests/locustfile.py --host http://localhost:8000 \
        --headless -u 1000 -r 50 -t 5m
        
Options:
    -u 1000     = 1000 total users
    -r 50       = spawn 50 users/second
    -t 5m       = run for 5 minutes
"""

from locust import HttpUser, task, between, events
import random
import time
import json

# =============================================================================
# CONFIGURATION
# =============================================================================

MOCK_MODE = False  # Set to True to bypass LLM calls during load testing

# Cache agent IDs to avoid repeated API calls
AGENT_IDS = []

# =============================================================================
# USER BEHAVIOR SIMULATION
# =============================================================================

class ChatUser(HttpUser):
    """
    Simulates a user interacting with OmniCortex.
    Mix of text queries and voice interactions.
    """
    wait_time = between(1, 5)  # Think time between requests
    
    def on_start(self):
        """Called when user starts - fetch available agents"""
        global AGENT_IDS
        if not AGENT_IDS:
            try:
                resp = self.client.get("/agents")
                if resp.status_code == 200:
                    AGENT_IDS = [a["id"] for a in resp.json()]
            except:
                pass
    
    @task(10)  # Weight: 10 (most common action)
    def send_text_query(self):
        """Send a text question to a random agent"""
        if not AGENT_IDS:
            return
            
        agent_id = random.choice(AGENT_IDS)
        
        payload = {
            "question": f"Load test query {random.randint(1, 10000)}",
            "agent_id": agent_id,
            "max_history": 2,
            "mock_mode": MOCK_MODE  # If API supports mock mode
        }
        
        with self.client.post(
            "/query",
            json=payload,
            catch_response=True,
            name="/query [text]"
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"HTTP {response.status_code}")
    
    @task(3)  # Weight: 3 (less common than text)
    def list_agents(self):
        """List all agents (lightweight operation)"""
        self.client.get("/agents", name="/agents [list]")
    
    @task(1)  # Weight: 1 (rare operation)
    def health_check(self):
        """Check API health"""
        self.client.get("/", name="/ [health]")


class PowerUser(HttpUser):
    """
    Simulates a power user with rapid-fire queries.
    Less think time, more aggressive.
    """
    wait_time = between(0.5, 2)
    
    def on_start(self):
        global AGENT_IDS
        if not AGENT_IDS:
            try:
                resp = self.client.get("/agents")
                if resp.status_code == 200:
                    AGENT_IDS = [a["id"] for a in resp.json()]
            except:
                pass
    
    @task(10)
    def rapid_queries(self):
        """Send multiple queries quickly"""
        if not AGENT_IDS:
            return
            
        agent_id = random.choice(AGENT_IDS)
        
        questions = [
            "What are your capabilities?",
            "Tell me about your knowledge base",
            "How can you help me?",
            "What topics do you cover?",
            "Summarize your main function"
        ]
        
        payload = {
            "question": random.choice(questions),
            "agent_id": agent_id,
            "max_history": 0,
            "mock_mode": MOCK_MODE
        }
        
        self.client.post("/query", json=payload, name="/query [power]")


# =============================================================================
# EVENT HOOKS FOR REPORTING
# =============================================================================

@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print("=" * 60)
    print("🚀 OmniCortex Load Test Started")
    print(f"   Target: {environment.host}")
    print(f"   Mock Mode: {MOCK_MODE}")
    print("=" * 60)


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    print("\n" + "=" * 60)
    print("✅ Load Test Complete")
    print("=" * 60)


# =============================================================================
# CUSTOM METRICS (Optional)
# =============================================================================

@events.request.add_listener
def track_request(request_type, name, response_time, response_length, response, **kwargs):
    """Track custom metrics per request"""
    if response.status_code >= 400:
        # Log errors for debugging
        try:
            error_body = response.text[:200]
            print(f"⚠️ {name}: {response.status_code} - {error_body}")
        except:
            pass
