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
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

_CLIENT = None
_CLIENT_LOCK = threading.Lock()

_USAGE_BUFFER: List[List[Any]] = []
_CHAT_BUFFER: List[List[Any]] = []
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
    "question_tokens",
    "rag_query_tokens",
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

_ALLOWED_CHANNEL_NAMES = {"TEXT", "VOICE"}
_ALLOWED_CHANNEL_TYPES = {"UTILITY", "MARKETING", "AUTHENTICATION"}


def _clickhouse_enabled() -> bool:
    return os.getenv("CLICKHOUSE_ENABLED", "false").strip().lower() == "true"


def _clickhouse_db() -> str:
    return os.getenv("CLICKHOUSE_DB", "omnicortex")


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

        host = os.getenv("CLICKHOUSE_HOST", "localhost")
        port = int(os.getenv("CLICKHOUSE_PORT", "8123"))
        username = os.getenv("CLICKHOUSE_USER", "default")
        password = os.getenv("CLICKHOUSE_PASSWORD", "")
        secure = os.getenv("CLICKHOUSE_SECURE", "false").strip().lower() == "true"

        try:
            import clickhouse_connect

            _CLIENT = clickhouse_connect.get_client(
                host=host,
                port=port,
                username=username,
                password=password,
                database=_clickhouse_db(),
                secure=secure,
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
        _USAGE_BUFFER.clear()
        _CHAT_BUFFER.clear()

    if not usage_rows and not chat_rows:
        return

    client = get_clickhouse_client()
    if client is None:
        logger.warning("ClickHouse unavailable; dropping %s usage and %s chat rows", len(usage_rows), len(chat_rows))
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
    question_tokens: int = 0,
    rag_query_tokens: int = 0,
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
        max(0, int(question_tokens or 0)),
        max(0, int(rag_query_tokens or 0)),
        max(0, int(prompt_tokens or 0)),
        max(0, int(completion_tokens or 0)),
        float(latency_ms or 0.0),
        int(hit_rate or 0),
        float(cost or 0.0),
        str(status or "success"),
        str(error) if error else "",
    ]
    _append_row(_USAGE_BUFFER, row, "usage")
