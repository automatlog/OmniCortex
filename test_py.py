import asyncio
import websockets


async def handler(websocket):
    print("✅ GATEWAY CONNECTED SUCCESSFULLY!")
    try:
        async for message in websocket:
            if isinstance(message, bytes):
                print(f"🎤 Audio Received: {len(message)} bytes")
                # Return audio for testing (Echo)
                await websocket.send(message)
    except Exception as e:
        print(f"❌ Connection Error: {e}")


async def main():
    # 0.0.0.0 listen for RunPod
    async with websockets.serve(handler, "0.0.0.0", 14496):
        print("🚀 AI AGENT RUNNING ON PORT 14496")
        print("📡 Waiting for Gateway on External Port 10934...")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
