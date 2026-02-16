import asyncio
import json
import os
import sys

import websockets

BASE_URL = os.getenv("WS_BASE_URL", "ws://localhost:8000")
AGENT_ID = "test-agent-ws"


async def test_websocket():
    uri = f"{BASE_URL}/ws/chat/{AGENT_ID}"
    print(f"[PHASE4] Connecting to {uri} ...")
    try:
        async with websockets.connect(uri) as websocket:
            await websocket.send(json.dumps({"content": "Hello, World!"}))

            msg1 = json.loads(await websocket.recv())
            msg2 = json.loads(await websocket.recv())
            msg3 = json.loads(await websocket.recv())

            assert msg1.get("type") == "status" and msg1.get("status") == "thinking"
            assert msg2.get("type") == "message" and "Echo:" in msg2.get("content", "")
            assert msg3.get("type") == "status" and msg3.get("status") == "idle"
            print("[OK] WebSocket protocol test passed")
    except Exception as e:
        print(f"[FAIL] WebSocket test failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(test_websocket())
