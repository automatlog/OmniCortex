import os
import sys

from fastapi.testclient import TestClient

# Ensure we can import from project root.
sys.path.append(os.path.dirname(os.path.abspath(__file__)) + "/../")

from api import app
from core.auth import create_new_api_key
from core.database import SessionLocal

# Disable startup/shutdown hooks so this test validates auth flow only.
app.router.on_startup.clear()
app.router.on_shutdown.clear()

client = TestClient(app)


def test_auth_flow():
    print("[AUTH] Testing Authentication Flow...")

    print("  [1/4] Access /query without key")
    response = client.post("/query", json={"question": "hi"})
    if response.status_code != 403:
        print(f"  [FAIL] Expected 403, got {response.status_code}")
        sys.exit(1)
    print("  [OK] blocked (403)")

    print("  [2/4] Create API key")
    db = SessionLocal()
    try:
        new_key = create_new_api_key("test_user_auth", db)
        print(f"  [KEY] {new_key[:6]}...")
    finally:
        db.close()

    print("  [3/4] Access /query with valid key")
    response = client.post(
        "/query",
        json={"question": "hi", "mock_mode": True},
        headers={"X-API-Key": new_key},
    )
    if response.status_code != 200:
        print(f"  [FAIL] Expected 200, got {response.status_code} - {response.text}")
        sys.exit(1)
    print("  [OK] success (200)")

    print("  [4/4] Access /query with invalid key")
    response = client.post(
        "/query",
        json={"question": "hi"},
        headers={"X-API-Key": "invalid_key_123"},
    )
    if response.status_code != 403:
        print(f"  [FAIL] Expected 403, got {response.status_code}")
        sys.exit(1)
    print("  [OK] blocked (403)")

    print("[OK] Auth Flow Test Passed")


if __name__ == "__main__":
    test_auth_flow()
