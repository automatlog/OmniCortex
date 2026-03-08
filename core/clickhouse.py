"""
ClickHouse analytics writer.

No-role chat model:
- One row per turn in chat_archive.
- content stores JSON string: {"user": "...", "ai": "..."}.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
import zlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_CLIENT = None
_CLIENT_LOCK = threading.Lock()

_USAGE_BUFFER: List[List[Any]] = []
_CHAT_BUFFER: List[List[Any]] = []
_AGENT_EVENT_BUFFER: List[List[Any]] = []
_BUFFER_LOCK = threading.Lock()

_FLUSHER_STARTED = False
_FLUSHER_LOCK = threading.Lock()

_ZERO_UUID = uuid.UUID("00000000-0000-0000-0000-000000000000")
_I32_MIN = -(2**31)
_I32_MAX = 2**31 - 1

_USAGE_COLS = [
    "timestamp",
    "request_id",
    "session_id",
    "id",
    "user_id",
    "product_id",
    "channel_name",
    "channel_type",
    "model",
    "query_tokens",
    "prompt_tokens",
    "completion_tokens",
    "latency",
    "hit_rate",
    "cost",
    "status",
    "error",
]

_CHAT_COLS = [
    "timestamp",
    "id",
    "user_id",
    "request_id",
    "content",
    "started_at",
    "ended_at",
    "session_id",
    "status",
    "error",
]

_AGENT_EVENT_COLS = [
    "timestamp",
    "event_id",
    "id",
    "user_id",
    "status",
    "created_at",
    "deleted_at",
    "agent_name",
    "model_selection",
    "role_type",
    "subagent_type",
    "vector_store",
    "vector_chunks",
    "parent_chunks",
    "payload",
    "error",
]

_ALLOWED_CHANNEL_NAMES = {"TEXT", "VOICE"}
_ALLOWED_CHANNEL_TYPES = {"UTILITY", "MARKETING", "AUTHENTICATION"}


def _clickhouse_enabled() -> bool:
    return os.getenv("CLICKHOUSE_ENABLED", "false").strip().lower() == "true"


def _clickhouse_db() -> str:
    return os.getenv("CLICKHOUSE_DB", "omnicortex")


def _as_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _clickhouse_connection_string_raw() -> str:
    # Supports requested mixed-case key and an uppercase alternative.
    return (
        os.getenv("ClickHouseAIConnectionString", "").strip()
        or os.getenv("CLICKHOUSE_AI_CONNECTION_STRING", "").strip()
    )


def _parse_clickhouse_connection_string(raw: str) -> Dict[str, str]:
    if not raw:
        return {}

    parsed: Dict[str, str] = {}
    for token in raw.split(";"):
        part = token.strip()
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        parsed[key.strip().lower()] = value.strip().strip("\"' ")
    return parsed


def _clickhouse_batch_size() -> int:
    try:
        return max(1, int(os.getenv("CLICKHOUSE_BATCH_SIZE", "100")))
    except Exception:
        return 100


def _clickhouse_flush_interval() -> float:
    try:
        return max(0.25, float(os.getenv("CLICKHOUSE_FLUSH_INTERVAL", "1.5")))
    except Exception:
        return 1.5


def _clickhouse_max_buffer_rows() -> int:
    try:
        return max(100, int(os.getenv("CLICKHOUSE_MAX_BUFFER_ROWS", "5000")))
    except Exception:
        return 5000


def _safe_uuid(value: Optional[str]) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    if value is None:
        return _ZERO_UUID
    text = str(value).strip()
    if not text:
        return _ZERO_UUID
    try:
        return uuid.UUID(text)
    except Exception:
        return _ZERO_UUID


def _safe_int32(value: Optional[Any]) -> int:
    if value is None:
        return 0
    try:
        number = int(value)
        if _I32_MIN <= number <= _I32_MAX:
            return number
    except Exception:
        pass
    h = zlib.crc32(str(value).encode("utf-8"))
    if h > _I32_MAX:
        h -= 2**32
    return int(h)


def _channel_name(value: Optional[str]) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "TEXT"

    upper = raw.upper()
    if upper in _ALLOWED_CHANNEL_NAMES:
        return upper

    lower = raw.lower()
    if lower == "voice":
        return "VOICE"

    # Backward compatibility for existing OmniCortex channels.
    if lower in {"web", "whatsapp", "websocket", "webhook", "text"}:
        return "TEXT"

    return "TEXT"


def _channel_type(value: Optional[Any]) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "UTILITY"

    upper = raw.upper()
    if upper in _ALLOWED_CHANNEL_TYPES:
        return upper

    # Backward compatibility for numeric category inputs.
    numeric_map = {
        "1": "UTILITY",
        "2": "MARKETING",
        "3": "AUTHENTICATION",
    }
    if raw in numeric_map:
        return numeric_map[raw]

    return "UTILITY"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_datetime(value: Optional[Any]) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _start_flusher_once() -> None:
    global _FLUSHER_STARTED
    if _FLUSHER_STARTED:
        return
    with _FLUSHER_LOCK:
        if _FLUSHER_STARTED:
            return
        thread = threading.Thread(target=_flush_worker, name="clickhouse-flusher", daemon=True)
        thread.start()
        _FLUSHER_STARTED = True


def _flush_worker() -> None:
    while True:
        time.sleep(_clickhouse_flush_interval())
        _flush_buffers()


def get_clickhouse_client():
    if not _clickhouse_enabled():
        return None

    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT

    with _CLIENT_LOCK:
        if _CLIENT is not None:
            return _CLIENT

        conn = _parse_clickhouse_connection_string(_clickhouse_connection_string_raw())
        host = conn.get("host") or os.getenv("CLICKHOUSE_HOST", "localhost")
        port = int(conn.get("port") or os.getenv("CLICKHOUSE_PORT", "8123"))
        username = (
            conn.get("user")
            or conn.get("username")
            or os.getenv("CLICKHOUSE_USER", "default")
        )
        password = conn.get("password") or os.getenv("CLICKHOUSE_PASSWORD", "")
        database = conn.get("database") or _clickhouse_db()
        secure = _as_bool(conn.get("secure"), _as_bool(os.getenv("CLICKHOUSE_SECURE", "false")))
        compress = _as_bool(conn.get("compress"), _as_bool(os.getenv("CLICKHOUSE_COMPRESS", "false")))

        try:
            import clickhouse_connect

            _CLIENT = clickhouse_connect.get_client(
                host=host,
                port=port,
                username=username,
                password=password,
                database=database,
                secure=secure,
                compress=compress,
            )
            return _CLIENT
        except ImportError:
            logger.warning("ClickHouse driver is not installed (clickhouse-connect).")
            return None
        except Exception as exc:
            logger.warning("ClickHouse connection failed: %s", exc)
            return None


def _append_row(buffer_ref: List[List[Any]], row: List[Any], buffer_name: str) -> None:
    if not _clickhouse_enabled():
        return

    _start_flusher_once()
    should_flush = False
    with _BUFFER_LOCK:
        buffer_ref.append(row)
        max_rows = _clickhouse_max_buffer_rows()
        if len(buffer_ref) > max_rows:
            overflow = len(buffer_ref) - max_rows
            del buffer_ref[:overflow]
            logger.warning("ClickHouse %s buffer overflow, dropped %s rows", buffer_name, overflow)
        should_flush = len(buffer_ref) >= _clickhouse_batch_size()

    if should_flush:
        _flush_buffers()


def _flush_buffers() -> None:
    if not _clickhouse_enabled():
        return

    with _BUFFER_LOCK:
        usage_rows = list(_USAGE_BUFFER)
        chat_rows = list(_CHAT_BUFFER)
        agent_event_rows = list(_AGENT_EVENT_BUFFER)
        _USAGE_BUFFER.clear()
        _CHAT_BUFFER.clear()
        _AGENT_EVENT_BUFFER.clear()

    if not usage_rows and not chat_rows and not agent_event_rows:
        return

    client = get_clickhouse_client()
    if client is None:
        logger.warning(
            "ClickHouse unavailable; dropping %s usage, %s chat, %s agent_event rows",
            len(usage_rows),
            len(chat_rows),
            len(agent_event_rows),
        )
        return

    if usage_rows:
        try:
            client.insert("usage_logs", usage_rows, column_names=_USAGE_COLS)
        except Exception as exc:
            logger.warning("ClickHouse usage_logs insert failed: %s", exc)

    if chat_rows:
        try:
            client.insert("chat_archive", chat_rows, column_names=_CHAT_COLS)
        except Exception as exc:
            logger.warning("ClickHouse chat_archive insert failed: %s", exc)

    if agent_event_rows:
        try:
            client.insert("agent_logs", agent_event_rows, column_names=_AGENT_EVENT_COLS)
        except Exception as exc:
            logger.warning("ClickHouse agent_logs insert failed: %s", exc)


def log_chat_to_clickhouse(
    agent_id: Optional[str],
    user_message: str,
    assistant_message: str,
    request_id: Optional[str] = None,
    session_id: Optional[str] = None,
    user_id: Optional[Any] = None,
    status: str = "success",
    error: Optional[str] = None,
    started_at: Optional[datetime] = None,
    ended_at: Optional[datetime] = None,
) -> None:
    """Queue one chat turn row for ClickHouse."""
    if not _clickhouse_enabled():
        return

    started = started_at or _now_utc()
    ended = ended_at or _now_utc()
    content_json = json.dumps(
        {"user": str(user_message or ""), "ai": str(assistant_message or "")},
        ensure_ascii=False,
    )

    row = [
        ended,  # timestamp
        _safe_uuid(agent_id),
        _safe_int32(user_id),
        str(request_id or ""),
        content_json,
        started,
        ended,
        str(session_id or ""),
        str(status or "success"),
        str(error) if error else "",
    ]
    _append_row(_CHAT_BUFFER, row, "chat")


def log_usage_to_clickhouse(
    agent_id: Optional[str],
    model: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    query_tokens: int = 0,
    rag_query_tokens: int = 0,  # kept for backward-compatible callers; not persisted
    latency_ms: float = 0.0,
    cost: float = 0.0,
    request_id: Optional[str] = None,
    session_id: Optional[str] = None,
    user_id: Optional[Any] = None,
    channel_name: str = "TEXT",
    status: str = "success",
    error: Optional[str] = None,
    product_id: int = 0,
    hit_rate: float = 0.0,
    channel_type: Optional[Any] = None,
) -> None:
    """Queue one LLM usage row for ClickHouse."""
    if not _clickhouse_enabled():
        return

    normalized_channel_name = _channel_name(channel_name)
    normalized_channel_type = _channel_type(channel_type)

    row = [
        _now_utc(),
        str(request_id or ""),
        str(session_id or ""),
        _safe_uuid(agent_id),
        _safe_int32(user_id),
        int(product_id or 0),
        normalized_channel_name,
        normalized_channel_type,
        str(model or "unknown"),
        max(0, int(query_tokens or 0)),
        max(0, int(prompt_tokens or 0)),
        max(0, int(completion_tokens or 0)),
        float(latency_ms or 0.0),
        int(hit_rate or 0),
        float(cost or 0.0),
        str(status or "success"),
        str(error) if error else "",
    ]
    _append_row(_USAGE_BUFFER, row, "usage")


def log_agent_event_to_clickhouse(
    agent_id: Optional[str],
    status: str = "Active",
    agent_name: Optional[str] = None,
    user_id: Optional[Any] = None,
    created_at: Optional[Any] = None,
    deleted_at: Optional[Any] = None,
    model_selection: Optional[str] = None,
    role_type: Optional[str] = None,
    subagent_type: Optional[str] = None,
    industry: Optional[str] = None,
    vector_store: Optional[str] = None,
    vector_chunks: int = 0,
    parent_chunks: int = 0,
    event_id: Optional[str] = None,
    payload: Optional[dict] = None,
    error: Optional[str] = None,
) -> None:
    """Queue one agent lifecycle event row for ClickHouse."""
    if not _clickhouse_enabled():
        return

    payload_text = ""
    if payload:
        try:
            payload_text = json.dumps(payload, ensure_ascii=False)
        except Exception:
            payload_text = str(payload)

    created_ts = _coerce_datetime(created_at) or _now_utc()
    deleted_ts = _coerce_datetime(deleted_at)
    normalized_subagent_type = str(subagent_type or industry or "")

    row = [
        _now_utc(),
        str(event_id or uuid.uuid4()),
        _safe_uuid(agent_id),
        _safe_int32(user_id),
        str(status or ""),
        created_ts,
        deleted_ts,
        str(agent_name or ""),
        str(model_selection or ""),
        str(role_type or ""),
        normalized_subagent_type,
        str(vector_store or ""),
        max(0, int(vector_chunks or 0)),
        max(0, int(parent_chunks or 0)),
        payload_text,
        str(error) if error else "",
    ]
    _append_row(_AGENT_EVENT_BUFFER, row, "agent_logs")
