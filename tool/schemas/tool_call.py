from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ToolCallRequest:
    tool_name: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    request_id: Optional[str] = None
    agent_id: Optional[str] = None


@dataclass
class ToolCallResult:
    tool_name: str
    ok: bool
    output: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    request_id: Optional[str] = None

