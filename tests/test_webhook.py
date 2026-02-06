"""
OmniCortex Webhook Test Script
Single file for testing webhook capture and agent reply functionality.
"""
import requests
import json
import time

# ============== CONFIGURATION ==============
# Read tunnel URL from tunnel.log or set manually
try:
    with open("tunnel.log", "r") as f:
        for line in f:
            if "trycloudflare.com" in line:
                import re
                match = re.search(r'https://[a-z\-]+\.trycloudflare\.com', line)
                if match:
                    TUNNEL_URL = match.group(0)
                    break
        else:
            TUNNEL_URL = "http://127.0.0.1:8001"  # Fallback to local
except:
    TUNNEL_URL = "http://127.0.0.1:8001"

print(f"🌐 Using Base URL: {TUNNEL_URL}")

# ============== SAMPLE PAYLOADS ==============

# WhatsApp Business Account Webhook Payload
WHATSAPP_PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [
        {
            "id": "897874963190139",
            "changes": [
                {
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "display_phone_number": "15558033154",
                            "phone_number_id": "948362531685989"
                        },
                        "contacts": [
                            {
                                "profile": {"name": "Test User"},
                                "wa_id": "919428587817"
                            }
                        ],
                        "messages": [
                            {
                                "from": "919428587817",
                                "id": "wamid.TEST123456789",
                                "timestamp": "1769059142",
                                "text": {"body": "Hello, who are you?"},
                                "type": "text"
                            }
                        ]
                    },
                    "field": "messages"
                }
            ]
        }
    ]
}

# Simple JSON Payload
SIMPLE_PAYLOAD = {
    "message": "What can you do for me?",
    "user_id": "test_user_123"
}


# ============== TEST FUNCTIONS ==============

def test_endpoint(name: str, url: str, payload: dict, method: str = "POST"):
    """Test a webhook endpoint"""
    print(f"\n{'='*50}")
    print(f"🧪 Test: {name}")
    print(f"📍 URL: {url}")
    print(f"📤 Method: {method}")
    
    try:
        start = time.time()
        
        if method == "POST":
            response = requests.post(url, json=payload, timeout=30)
        elif method == "GET":
            response = requests.get(url, timeout=30)
        else:
            print(f"❌ Unknown method: {method}")
            return
            
        latency = time.time() - start
        
        print(f"✅ Status: {response.status_code} ({latency:.2f}s)")
        
        if response.status_code == 200:
            try:
                data = response.json()
                status = data.get("status", "unknown")
                
                if status == "success":
                    print(f"🎉 Agent Response: {data.get('answer', 'N/A')[:150]}...")
                    print(f"🤖 Agent ID: {data.get('agent_id')}")
                elif status == "captured":
                    print(f"📁 Webhook Captured: {data.get('message')}")
                elif status == "ignored":
                    print(f"⚠️ Ignored: {data.get('reason')}")
                elif status == "error":
                    print(f"❌ Error: {data.get('detail')}")
                else:
                    print(f"📦 Response: {json.dumps(data, indent=2)[:300]}")
            except:
                print(f"📦 Raw Response: {response.text[:300]}")
        else:
            print(f"❌ Error: {response.text[:200]}")
            
    except requests.exceptions.Timeout:
        print("❌ Request timed out")
    except requests.exceptions.ConnectionError:
        print("❌ Connection failed - Is the server running?")
    except Exception as e:
        print(f"❌ Error: {e}")


def run_all_tests():
    """Run all webhook tests"""
    print("\n" + "="*60)
    print("🔬 OmniCortex Webhook Test Suite")
    print("="*60)
    
    # Test 1: Standard Agent Reply
    test_endpoint(
        name="Agent Reply (WhatsApp Payload)",
        url=f"{TUNNEL_URL}/webhooks/agent-reply",
        payload=WHATSAPP_PAYLOAD
    )
    
    # Test 2: Dynamic Path Capture
    test_endpoint(
        name="Dynamic Path Capture",
        url=f"{TUNNEL_URL}/webhooks/capture/sales_agent_2026",
        payload=WHATSAPP_PAYLOAD
    )
    
    # Test 3: Simple JSON Payload
    test_endpoint(
        name="Simple JSON Message",
        url=f"{TUNNEL_URL}/webhooks/agent-reply",
        payload=SIMPLE_PAYLOAD
    )
    
    # Test 4: GET Request (Meta Verification Simulation)
    test_endpoint(
        name="GET Verification",
        url=f"{TUNNEL_URL}/webhooks/agent-reply?hub.mode=subscribe&hub.challenge=12345",
        payload={},
        method="GET"
    )
    
    print("\n" + "="*60)
    print("✅ Test Suite Complete")
    print("="*60)


# ============== MAIN ==============
if __name__ == "__main__":
    run_all_tests()
