"""
Per-agent YAML config snapshot writer.

Stores runtime agent configuration and cumulative token totals under:
storage/agents/<agent_name>/config.yaml
"""
from __future__ import annotations

import copy
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy import func

from .agent_manager import get_agent
from .database import SessionLocal, UsageLog

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - fallback only if dependency missing
    yaml = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_agent_dir_name(name: str, fallback_id: str) -> str:
    raw = (name or "").strip()
    if not raw:
        raw = fallback_id
    safe = "".join(c if c.isalnum() or c in (" ", "_", "-", ".") else "_" for c in raw)
    safe = safe.strip().replace(" ", "_").lower()
    return safe or fallback_id


def _ensure_writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_probe"
        probe.write_text("", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def _config_path_for_agent(agent: Dict[str, Any]) -> Optional[Path]:
    agent_id = str(agent.get("id") or "unknown_agent")
    agent_name = str(agent.get("name") or agent_id)
    folder = _safe_agent_dir_name(agent_name, agent_id)
    tmp_root = Path(tempfile.gettempdir()) / "omnicortex_agents"

    candidates = [
        Path("storage") / "agents" / folder,
        Path("storage") / "agents" / "by_id" / agent_id,
        tmp_root / folder,
    ]
    for base in candidates:
        if _ensure_writable_dir(base):
            return base / "config.yaml"

    fallback = tmp_root / "by_id" / agent_id
    if _ensure_writable_dir(fallback):
        return fallback / "config.yaml"
    return None


def _agent_snapshot(agent: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": agent.get("id"),
        "name": agent.get("name"),
        "description": agent.get("description"),
        "system_prompt": agent.get("system_prompt"),
        "system_prompt_source": agent.get("system_prompt_source"),
        "role_type": agent.get("role_type"),
        "industry": agent.get("industry"),
        "agent_type": agent.get("agent_type"),
        "subagent_type": agent.get("subagent_type"),
        "model_selection": agent.get("model_selection"),
        "user_id": agent.get("user_id"),
        "document_count": agent.get("document_count", 0),
        "message_count": agent.get("message_count", 0),
        "urls": agent.get("urls"),
        "conversation_starters": agent.get("conversation_starters"),
        "conversation_end": agent.get("conversation_end"),
        "image_urls": agent.get("image_urls"),
        "video_urls": agent.get("video_urls"),
        "created_at": agent.get("created_at"),
    }


def _usage_totals(agent_id: str) -> Dict[str, int]:
    db = SessionLocal()
    try:
        sums = (
            db.query(
                func.coalesce(func.sum(UsageLog.prompt_tokens), 0),
                func.coalesce(func.sum(UsageLog.completion_tokens), 0),
                func.coalesce(func.sum(UsageLog.query_tokens), 0),
                func.coalesce(func.sum(UsageLog.rag_query_tokens), 0),
            )
            .filter(UsageLog.agent_id == agent_id)
            .one()
        )
        return {
            "total_input_tokens": int(sums[0] or 0),
            "total_output_tokens": int(sums[1] or 0),
            "total_query_tokens": int(sums[2] or 0),
            "total_rag_query_tokens": int(sums[3] or 0),
        }
    finally:
        db.close()


def _load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    if yaml is None:
        return {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _write_yaml(path: Path, payload: Dict[str, Any]) -> None:
    if yaml is None:
        # Fallback: write JSON content in .yaml path if PyYAML is unavailable.
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _compact_event_payload(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not payload:
        return {}
    data = copy.deepcopy(payload)
    # Keep the event file readable even if scraped payload is huge.
    if isinstance(data.get("scraped_data"), list):
        data["scraped_data_count"] = len(data["scraped_data"])
        if len(data["scraped_data"]) > 5:
            data["scraped_data"] = data["scraped_data"][:5]
    for key in ("description", "system_prompt"):
        value = data.get(key)
        if isinstance(value, str) and len(value) > 4000:
            data[key] = value[:4000] + "...[truncated]"
    return data


def sync_agent_config(
    agent_id: str,
    *,
    event_type: Optional[str] = None,
    event_payload: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Persist/update storage/agents/<agent_name>/config.yaml.

    - On create/update: append lifecycle event with payload snapshot.
    - On usage sync: refresh cumulative token totals.
    """
    agent = get_agent(agent_id)
    if not agent:
        return

    path = _config_path_for_agent(agent)
    if path is None:
        return
    cfg = _load_yaml(path)

    now = _now_iso()
    cfg["version"] = 1
    cfg["agent"] = _agent_snapshot(agent)
    cfg["usage"] = {**_usage_totals(agent_id), "last_synced_at": now}

    lifecycle = cfg.get("lifecycle")
    if not isinstance(lifecycle, dict):
        lifecycle = {}
    lifecycle["last_event_at"] = now
    lifecycle["last_event_type"] = event_type or "sync"
    cfg["lifecycle"] = lifecycle

    if event_type in {"create", "update"}:
        events = cfg.get("events")
        if not isinstance(events, list):
            events = []
        events.append(
            {
                "type": event_type,
                "at": now,
                "payload": _compact_event_payload(event_payload),
            }
        )
        cfg["events"] = events[-30:]

    _write_yaml(path, cfg)
