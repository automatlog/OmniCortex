import os
import sys
import uuid

sys.path.append(os.getcwd())

from core.database import Agent, Channel, SessionLocal, Tool
from core.whatsapp import WhatsAppHandler


def test_phase2_crud():
    print("[PHASE2] Testing CRUD for channels and tools...")

    channel_id = str(uuid.uuid4())
    tool_id = str(uuid.uuid4())

    db = SessionLocal()
    try:
        channel = Channel(
            id=channel_id,
            name="Test WhatsApp",
            type="whatsapp",
            provider="meta",
            config={"phone_number_id": "123456"},
        )
        db.add(channel)
        db.commit()

        saved_channel = db.query(Channel).filter(Channel.id == channel_id).first()
        assert saved_channel is not None
        assert saved_channel.name == "Test WhatsApp"
        print("  [OK] channel persistence")

        agent = db.query(Agent).first()
        if not agent:
            agent = Agent(id="phase2_test_agent", name="Phase2TestAgent")
            db.add(agent)
            db.commit()

        tool = Tool(
            id=tool_id,
            name="Appointment Flow",
            type="flow",
            content={"flow_id": "123", "screen": "book_appt"},
            agent_id=agent.id,
        )
        db.add(tool)
        db.commit()

        saved_tool = db.query(Tool).filter(Tool.id == tool_id).first()
        assert saved_tool is not None
        assert saved_tool.type == "flow"
        print("  [OK] tool persistence")
    finally:
        cleanup = SessionLocal()
        try:
            t = cleanup.query(Tool).filter(Tool.id == tool_id).first()
            if t:
                cleanup.delete(t)
            c = cleanup.query(Channel).filter(Channel.id == channel_id).first()
            if c:
                cleanup.delete(c)
            cleanup.commit()
        finally:
            cleanup.close()
            db.close()


def test_whatsapp_methods_exist():
    print("[PHASE2] Testing WhatsApp handler capabilities...")
    handler = WhatsAppHandler()
    assert hasattr(handler, "send_interactive_message")
    assert hasattr(handler, "send_flow_message")
    print("  [OK] send_interactive_message and send_flow_message are available")


if __name__ == "__main__":
    test_phase2_crud()
    test_whatsapp_methods_exist()
    print("[OK] Phase 2 tests completed.")
