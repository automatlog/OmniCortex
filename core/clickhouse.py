"""
ClickHouse Analytics & Archiving
"""
import os
import logging
from datetime import datetime
import threading
import uuid

# Global client cache
_CLIENT = None

def get_clickhouse_client():
    """Get or create ClickHouse client"""
    global _CLIENT
    if _CLIENT:
        return _CLIENT
    
    host = os.getenv("CLICKHOUSE_HOST", "192.168.29.140")
    port = int(os.getenv("CLICKHOUSE_PORT", "8123"))
    username = os.getenv("CLICKHOUSE_USER", "default")
    password = os.getenv("CLICKHOUSE_PASSWORD", "smart123")
    
    try:
        import clickhouse_connect
        _CLIENT = clickhouse_connect.get_client(
            host=host, 
            port=port, 
            username=username, 
            password=password,
            database="omnicortex"
        )
        return _CLIENT
    except ImportError:
        print("⚠️ ClickHouse driver not installed.")
        return None
    except Exception as e:
        print(f"⚠️ ClickHouse connection failed: {e}")
        return None


def log_chat_to_clickhouse(agent_id: str, role: str, content: str, session_id: str = "default",
                           user_id: int = 0, user_name: str = "", product_id: int = 0, channel_name: str = "web"):
    """
    Log chat message to ClickHouse
    """
    def _log():
        try:
            client = get_clickhouse_client()
            if not client:
                return
            
            # Table: chat_archive 
            # Columns: id, timestamp, agent_id, user_id, user_name, product_id, channel_name, role, content, started_at, ended_at, session_id
            now = datetime.now()
            data = [[
                uuid.uuid4(),           # id
                now,                    # timestamp
                agent_id or "unknown",  # agent_id
                user_id,
                user_name,
                product_id,
                channel_name,
                role,
                content,
                now,                    # started_at (msg time)
                now,                    # ended_at (msg time)
                session_id
            ]]
            
            cols = ['id', 'timestamp', 'agent_id', 'user_id', 'user_name', 'product_id', 'channel_name', 
                    'role', 'content', 'started_at', 'ended_at', 'session_id']
            
            client.insert('chat_archive', data, column_names=cols)
        except Exception as e:
            print(f"⚠️ ClickHouse Log Error: {e}")

    # Run in background
    try:
        threading.Thread(target=_log).start()
    except Exception:
        pass


def log_usage_to_clickhouse(agent_id: str, model: str, prompt_tokens: int, completion_tokens: int, latency: float, cost: float,
                            user_id: int = 0, user_name: str = "", product_id: int = 0, channel_name: str = "web"):
    """
    Log usage stats to ClickHouse
    """
    def _log():
        try:
            client = get_clickhouse_client()
            if not client:
                return
            
            # Table: usage_logs
            data = [[
                datetime.now(),
                agent_id or "unknown",
                user_id,
                user_name,
                product_id,
                channel_name,
                model,
                prompt_tokens,
                completion_tokens,
                latency,
                cost
            ]]
            
            cols = ['timestamp', 'agent_id', 'user_id', 'user_name', 'product_id', 'channel_name', 
                    'model', 'prompt_tokens', 'completion_tokens', 'latency', 'cost']
            
            client.insert('usage_logs', data, column_names=cols)
        except Exception as e:
            print(f"⚠️ ClickHouse Log Error: {e}")

    try:
        threading.Thread(target=_log).start()
    except Exception:
        pass
