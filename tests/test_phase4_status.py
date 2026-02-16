import asyncio
import json
import os
import sys

import websockets

BASE_URL = os.getenv("WS_BASE_URL", "ws://localhost:8000")
AGENT_ID = "test-agent-ws-json"


async def test_websocket_json():
    uri = f"{BASE_URL}/ws/chat/{AGENT_ID}"
    print(f"[PHASE4] Connecting to {uri} ...")
    try:
        async with websockets.connect(uri) as websocket:
            await websocket.send(json.dumps({"content": "Hello, JSON!"}))

            resp1 = json.loads(await websocket.recv())
            resp2 = json.loads(await websocket.recv())
            resp3 = json.loads(await websocket.recv())

            assert resp1.get("type") == "status" and resp1.get("status") == "thinking"
            assert resp2.get("type") == "message" and "Echo:" in resp2.get("content", "")
            assert resp3.get("type") == "status" and resp3.get("status") == "idle"
            print("[OK] WebSocket JSON status protocol test passed")
    except Exception as e:
        print(f"[FAIL] WebSocket JSON status test failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(test_websocket_json())
