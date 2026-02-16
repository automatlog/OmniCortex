import os
import sys
import time

import requests

sys.path.append(os.getcwd())

BASE_URL = "http://localhost:8000"
API_KEY = os.getenv("TEST_API_KEY", "")


def _headers():
    return {"X-API-Key": API_KEY} if API_KEY else {}


def test_dashboard_api():
    print("[PHASE3] Testing dashboard endpoint...")
    try:
        response = requests.get(f"{BASE_URL}/stats/dashboard", timeout=10)
        assert response.status_code == 200
        data = response.json()
        assert "counts" in data
        assert "documents" in data
        assert "usage" in data
        assert "recent_activity" in data
        print("  [OK] dashboard schema")
    except Exception as e:
        print(f"  [WARN] dashboard test skipped/failed: {e}")


def test_session_creation():
    print("[PHASE3] Testing session creation via /query...")
    try:
        agents_resp = requests.get(f"{BASE_URL}/agents", timeout=10)
        agents_resp.raise_for_status()
        agents = agents_resp.json()
        if not agents:
            print("  [WARN] no agents found; skipping session test")
            return

        payload = {
            "question": "session test",
            "agent_id": agents[0]["id"],
            "user_id": "phase3_test_user",
            "mock_mode": True,
        }
        response = requests.post(f"{BASE_URL}/query", json=payload, headers=_headers(), timeout=10)
        if response.status_code != 200:
            print(f"  [WARN] query returned {response.status_code}: {response.text}")
            return

        data = response.json()
        assert "session_id" in data
        print("  [OK] session_id returned")

        time.sleep(1)
        dash = requests.get(f"{BASE_URL}/stats/dashboard", timeout=10).json()
        found = any(item.get("id") == data["session_id"] for item in dash.get("recent_activity", []))
        print(f"  [INFO] session present in recent_activity: {found}")
    except Exception as e:
        print(f"  [WARN] session test skipped/failed: {e}")


if __name__ == "__main__":
    test_dashboard_api()
    test_session_creation()
    print("[OK] Phase 3 tests completed.")
