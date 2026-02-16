from typing import List, Dict
from fastapi import WebSocket, WebSocketDisconnect

class ConnectionManager:
    """
    Manages active WebSocket connections for live chat.
    Stores connections by agent_id.
    """
    def __init__(self):
        # agent_id -> List[WebSocket]
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, agent_id: str):
        """Accepts connection and stores it."""
        await websocket.accept()
        if agent_id not in self.active_connections:
            self.active_connections[agent_id] = []
        self.active_connections[agent_id].append(websocket)
        print(f"🔌 WebSocket Connected: Agent {agent_id}")

    def disconnect(self, websocket: WebSocket, agent_id: str):
        """Removes connection on disconnect."""
        if agent_id in self.active_connections:
            if websocket in self.active_connections[agent_id]:
                self.active_connections[agent_id].remove(websocket)
            if not self.active_connections[agent_id]:
                del self.active_connections[agent_id]
        print(f"🔌 WebSocket Disconnected: Agent {agent_id}")

    async def send_personal_message(self, message: str, websocket: WebSocket):
        """Send message to a specific connection."""
        await websocket.send_text(message)

    async def broadcast(self, message: str, agent_id: str):
        """Broadcast message to all connections for an agent."""
        if agent_id in self.active_connections:
            for connection in self.active_connections[agent_id]:
                try:
                    await connection.send_text(message)
                except Exception as e:
                    print(f"⚠️ Error broadcasting to {agent_id}: {e}")

manager = ConnectionManager()
