"""
Agent Management - CRUD operations for agents
"""
import os
import threading
import time
from typing import List, Dict, Optional, Any

from .database import SessionLocal, Agent
from .rag.vector_store import delete_vector_store


_DELETE_RETRY_ATTEMPTS = max(1, int(os.getenv("AGENT_DELETE_VECTOR_RETRIES", "5")))
_DELETE_RETRY_DELAY_SECONDS = max(0.1, float(os.getenv("AGENT_DELETE_VECTOR_RETRY_DELAY", "2")))

# Safe filter: skip .deleted check if the column doesn't exist on the model
_HAS_DELETED = hasattr(Agent, "deleted")


def _safe_int(value: Optional[str], default: int) -> int:
    """Safely convert env var string to int, returning default on error."""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default

def _not_deleted():
    """Return filter clause for non-deleted agents, or True if column missing."""
    if _HAS_DELETED:
        return Agent.deleted.is_(False)
    return True

def _is_deleted():
    """Return filter clause for soft-deleted agents, or False if column missing."""
    if _HAS_DELETED:
        return Agent.deleted.is_(True)
    return False


def _finalize_deleted_agent(agent_id: str) -> None:
    """Delete vectors first, then hard-delete an already soft-deleted agent row."""
    for attempt in range(1, _DELETE_RETRY_ATTEMPTS + 1):
        db = SessionLocal()
        try:
            agent = db.query(Agent).filter(Agent.id == agent_id).first()
            if not agent:
                return
            if not bool(agent.deleted):
                return
        finally:
            db.close()

        if delete_vector_store(agent_id):
            db = SessionLocal()
            try:
                agent = db.query(Agent).filter(Agent.id == agent_id, _is_deleted()).first()
                if agent:
                    db.delete(agent)
                    db.commit()
                    print(f"[OK] Finalized agent deletion: {agent_id}")
            except Exception as exc:
                db.rollback()
                print(f"[WARN] Failed to finalize deleted agent {agent_id}: {exc}")
            finally:
                db.close()
            return

        if attempt < _DELETE_RETRY_ATTEMPTS:
            time.sleep(_DELETE_RETRY_DELAY_SECONDS * attempt)

    print(
        f"[WARN] Vector cleanup retries exhausted for agent {agent_id}; "
        "agent remains soft-deleted"
    )


def _schedule_deleted_agent_cleanup(agent_id: str) -> None:
    worker = threading.Thread(target=_finalize_deleted_agent, args=(agent_id,), daemon=True)
    worker.start()


def create_agent(
    name: str,
    id: str,
    description: str = "",
    system_prompt: str = None,
    system_prompt_source: str = None,
    role_type: str = None,
    industry: str = None,
    urls: List[str] = None,
    conversation_starters: List[str] = None,
    image_urls: List[str] = None,
    video_urls: List[str] = None,
    scraped_data: List[Dict] = None,
    logic: Any = None,
    conversation_end: List[Dict] = None,
    agent_type: str = None,
    subagent_type: str = None,
    model_selection: str = None,
    user_id: str = None,
    owner_token_id: str = None,
) -> str:
    """Create a new agent"""
    db = SessionLocal()
    try:
        existing = db.query(Agent).filter(Agent.name == name, _not_deleted()).first()
        if existing:
            raise ValueError(f"Agent '{name}' already exists")

        agent_id = str(id).strip() if id is not None else ""
        if not agent_id:
            raise ValueError("id is required")
        id_exists = db.query(Agent).filter(Agent.id == agent_id, _not_deleted()).first()
        if id_exists:
            raise ValueError(f"Agent id '{agent_id}' already exists")

        extra_data = {}
        if owner_token_id:
            extra_data["owner_token_id"] = str(owner_token_id).strip()
        if user_id is not None:
            extra_data["creator_user_id"] = str(user_id).strip()

        agent = Agent(
            id=agent_id,
            name=name,
            description=description,
            system_prompt=system_prompt,
            system_prompt_source=system_prompt_source,
            role_type=role_type,
            industry=industry,
            urls=urls,
            conversation_starters=conversation_starters,
            image_urls=image_urls,
            video_urls=video_urls,
            scraped_data=scraped_data,
            logic=logic,
            conversation_end=conversation_end,
            agent_type=agent_type,
            subagent_type=subagent_type,
            model_selection=model_selection,
            user_id=user_id,
            extra_data=extra_data or {},
        )
        db.add(agent)
        db.commit()
        print(f"[OK] Created agent: {name} (Role: {role_type})")
        return agent_id
    finally:
        db.close()


def get_agent(agent_id: str) -> Optional[Dict]:
    """Get agent by ID"""
    db = SessionLocal()
    try:
        agent = db.query(Agent).filter(Agent.id == agent_id, _not_deleted()).first()
        if not agent:
            return None
        metadata = agent.extra_data or {}

        return {
            "id": agent.id,
            "name": agent.name,
            "description": agent.description,
            "system_prompt": agent.system_prompt,
            "system_prompt_source": agent.system_prompt_source or metadata.get("system_prompt_source"),
            "role_type": agent.role_type,
            "industry": agent.industry,
            "urls": agent.urls,
            "conversation_starters": agent.conversation_starters,
            "image_urls": agent.image_urls,
            "video_urls": agent.video_urls,
            "scraped_data": agent.scraped_data,
            "logic": agent.logic if agent.logic is not None else metadata.get("logic"),
            "conversation_end": agent.conversation_end if agent.conversation_end is not None else metadata.get("conversation_end"),
            "agent_type": agent.agent_type if agent.agent_type is not None else metadata.get("agent_type"),
            "subagent_type": agent.subagent_type if agent.subagent_type is not None else metadata.get("subagent_type"),
            "model_selection": agent.model_selection if agent.model_selection is not None else metadata.get("model_selection"),
            "user_id": agent.user_id,
            "document_count": agent.document_count or 0,
            "message_count": agent.message_count or 0,
            "created_at": agent.created_at.isoformat() if agent.created_at else None,
            "metadata": metadata,
        }
    finally:
        db.close()


def get_all_agents() -> List[Dict]:
    """Get all agents"""
    db = SessionLocal()
    try:
        agents = db.query(Agent).filter(_not_deleted()).order_by(Agent.created_at.desc()).all()
        return [
            {
                "metadata": a.extra_data or {},
                "id": a.id,
                "name": a.name,
                "description": a.description,
                "system_prompt": a.system_prompt,
                "system_prompt_source": a.system_prompt_source or ((a.extra_data or {}).get("system_prompt_source")),
                "role_type": a.role_type,
                "industry": a.industry,
                "urls": a.urls,
                "conversation_starters": a.conversation_starters,
                "image_urls": a.image_urls,
                "video_urls": a.video_urls,
                "scraped_data": a.scraped_data,
                "logic": a.logic if a.logic is not None else ((a.extra_data or {}).get("logic")),
                "conversation_end": a.conversation_end if a.conversation_end is not None else ((a.extra_data or {}).get("conversation_end")),
                "agent_type": a.agent_type if a.agent_type is not None else ((a.extra_data or {}).get("agent_type")),
                "subagent_type": a.subagent_type if a.subagent_type is not None else ((a.extra_data or {}).get("subagent_type")),
                "model_selection": a.model_selection if a.model_selection is not None else ((a.extra_data or {}).get("model_selection")),
                "user_id": a.user_id,
                "document_count": a.document_count or 0,
                "message_count": a.message_count or 0,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in agents
        ]
    finally:
        db.close()


def update_agent(
    agent_id: str,
    name: str = None,
    description: str = None,
    system_prompt: str = None,
    system_prompt_source: str = None,
    role_type: str = None,
    industry: str = None,
    urls: List[str] = None,
    conversation_starters: List[str] = None,
    image_urls: List[str] = None,
    video_urls: List[str] = None,
    scraped_data: List[Dict] = None,
    logic: Any = None,
    conversation_end: List[Dict] = None,
    agent_type: str = None,
    subagent_type: str = None,
    model_selection: str = None,
    user_id: str = None,
    extra_data: Dict = None,
) -> bool:
    """Update agent details"""
    db = SessionLocal()
    try:
        agent = db.query(Agent).filter(Agent.id == agent_id, _not_deleted()).first()
        if not agent:
            return False

        if name is not None:
            agent.name = name
        if description is not None:
            agent.description = description
        if system_prompt is not None:
            agent.system_prompt = system_prompt
        if system_prompt_source is not None:
            agent.system_prompt_source = system_prompt_source
        if role_type is not None:
            agent.role_type = role_type
        if industry is not None:
            agent.industry = industry
        if urls is not None:
            agent.urls = urls
        if conversation_starters is not None:
            agent.conversation_starters = conversation_starters
        if image_urls is not None:
            agent.image_urls = image_urls
        if video_urls is not None:
            agent.video_urls = video_urls
        if scraped_data is not None:
            agent.scraped_data = scraped_data
        if logic is not None:
            if isinstance(logic, dict) and isinstance(agent.logic, dict):
                merged = dict(agent.logic)
                merged.update(logic)
                agent.logic = merged
            else:
                agent.logic = logic
        if conversation_end is not None:
            agent.conversation_end = conversation_end
        if agent_type is not None:
            agent.agent_type = agent_type
        if subagent_type is not None:
            agent.subagent_type = subagent_type
        if model_selection is not None:
            agent.model_selection = model_selection
        if user_id is not None:
            agent.user_id = user_id
        if extra_data is not None:
            # Merge into existing extra_data to preserve owner_token_id etc.
            existing = agent.extra_data or {}
            existing.update(extra_data)
            agent.extra_data = existing

        db.commit()
        return True
    finally:
        db.close()


def update_agent_metadata(agent_id: str, document_count: int = None, message_count: int = None):
    """Update agent counts"""
    db = SessionLocal()
    try:
        agent = db.query(Agent).filter(Agent.id == agent_id, _not_deleted()).first()
        if agent:
            if document_count is not None:
                agent.document_count = (agent.document_count or 0) + document_count
            if message_count is not None:
                agent.message_count = message_count
            db.commit()
    finally:
        db.close()


def resolve_retrieval_config(agent_id: str, agent: dict = None) -> dict:
    """Resolve retrieval settings: agent.logic.retrieval > env > hardcoded defaults."""
    if agent is None and agent_id:
        agent = get_agent(agent_id)
    logic = (agent.get("logic") or {}) if agent else {}
    agent_cfg = logic.get("retrieval") or {} if isinstance(logic, dict) else {}
    return {
        "use_hybrid_search": agent_cfg.get(
            "use_hybrid_search",
            os.getenv("USE_HYBRID_SEARCH", "true").lower() == "true",
        ),
        "use_reranker": agent_cfg.get(
            "use_reranker",
            os.getenv("USE_RERANKER", "false").lower() == "true",
        ),
        "reranker_model": agent_cfg.get(
            "reranker_model",
            os.getenv("RERANKER_MODEL_NAME", "BAAI/bge-reranker-large"),
        ),
        "top_k": agent_cfg.get("top_k", 4),
        "voice_top_k": agent_cfg.get("voice_top_k", 3),
    }


def resolve_voice_config(agent_id: str, agent: dict = None) -> dict:
    """Resolve voice settings: agent.logic.voice > env > hardcoded defaults."""
    if agent is None and agent_id:
        agent = get_agent(agent_id)
    logic = (agent.get("logic") or {}) if agent else {}
    agent_cfg = logic.get("voice") or {} if isinstance(logic, dict) else {}
    return {
        "enabled": agent_cfg.get("enabled", True),
        "mode": agent_cfg.get(
            "mode",
            os.getenv("VOICE_DEFAULT_MODE", "personaplex"),
        ),
        "voice_prompt": agent_cfg.get("voice_prompt", "NATF0.pt"),
        "sample_rate": agent_cfg.get("sample_rate", 8000),
        "rag_enabled": agent_cfg.get(
            "rag_enabled",
            os.getenv("VOICE_RAG_ENABLED", "true").lower() == "true",
        ),
        "rag_top_k": agent_cfg.get(
            "rag_top_k",
            _safe_int(os.getenv("VOICE_RAG_TOP_K"), 3),
        ),
        "context_query": agent_cfg.get("context_query", ""),
    }


def delete_agent(agent_id: str) -> bool:
    """Soft-delete first, then finalize deletion in a retriable background worker."""
    db = SessionLocal()
    try:
        agent = db.query(Agent).filter(Agent.id == agent_id).first()
        if not agent:
            return False

        if bool(agent.deleted):
            _schedule_deleted_agent_cleanup(agent_id)
            return True

        agent_name = agent.name

        # semantic cache rows are not FK-constrained; clear them explicitly
        from sqlalchemy import text as sa_text
        db.execute(
            sa_text("DELETE FROM omni_semantic_cache WHERE agent_id = :agent_id"),
            {"agent_id": agent_id},
        )

        agent.deleted = True
        db.commit()

        _schedule_deleted_agent_cleanup(agent_id)
        print(f"[OK] Marked agent deleted: {agent_name}")
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
