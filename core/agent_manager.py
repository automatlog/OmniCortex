"""
Agent Management - CRUD operations for agents
"""
import uuid
from typing import List, Dict, Optional, Any

from .database import SessionLocal, Agent
from .rag.vector_store import delete_vector_store


def create_agent(
    name: str,
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
) -> str:
    """Create a new agent"""
    db = SessionLocal()
    try:
        existing = db.query(Agent).filter(Agent.name == name).first()
        if existing:
            raise ValueError(f"Agent '{name}' already exists")

        agent_id = str(uuid.uuid4())
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
        agent = db.query(Agent).filter(Agent.id == agent_id).first()
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
        agents = db.query(Agent).order_by(Agent.created_at.desc()).all()
        return [
            {
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
) -> bool:
    """Update agent details"""
    db = SessionLocal()
    try:
        agent = db.query(Agent).filter(Agent.id == agent_id).first()
        if not agent:
            return False

        if name:
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
            agent.logic = logic
        if conversation_end is not None:
            agent.conversation_end = conversation_end
        if agent_type is not None:
            agent.agent_type = agent_type
        if subagent_type is not None:
            agent.subagent_type = subagent_type
        if model_selection is not None:
            agent.model_selection = model_selection

        db.commit()
        return True
    finally:
        db.close()


def update_agent_metadata(agent_id: str, document_count: int = None, message_count: int = None):
    """Update agent counts"""
    db = SessionLocal()
    try:
        agent = db.query(Agent).filter(Agent.id == agent_id).first()
        if agent:
            if document_count is not None:
                agent.document_count = (agent.document_count or 0) + document_count
            if message_count is not None:
                agent.message_count = message_count
            db.commit()
    finally:
        db.close()


def delete_agent(agent_id: str) -> bool:
    """Delete agent and all associated data"""
    db = SessionLocal()
    try:
        agent = db.query(Agent).filter(Agent.id == agent_id).first()
        if not agent:
            return False

        # semantic cache rows are not FK-constrained; clear them explicitly
        from sqlalchemy import text as sa_text
        db.execute(
            sa_text("DELETE FROM omni_semantic_cache WHERE agent_id = :agent_id"),
            {"agent_id": agent_id},
        )

        delete_vector_store(agent_id)
        db.delete(agent)
        db.commit()
        print(f"[OK] Deleted agent: {agent.name}")
        return True
    finally:
        db.close()
