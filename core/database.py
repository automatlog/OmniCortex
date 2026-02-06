"""
PostgreSQL Database Models with pgvector support
"""
from typing import List, Dict, Optional
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey, Index, JSON, Float, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector
from .config import DATABASE_URL

# Database setup with connection pooling
engine = create_engine(
    DATABASE_URL, 
    echo=False,
    pool_size=20,           # Maintain 20 connections
    max_overflow=40,        # Allow up to 40 extra connections
    pool_pre_ping=True,     # Health check connections
    pool_recycle=3600       # Recycle connections after 1 hour
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ============== MODELS ==============

class Agent(Base):
    """Agent model for multi-agent support"""
    __tablename__ = "omni_agents"
    
    id = Column(String, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    description = Column(Text)
    system_prompt = Column(Text)  # Custom instructions
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    document_count = Column(Integer, default=0)
    message_count = Column(Integer, default=0)
    extra_data = Column(JSON, default={})  # For future extension (renamed from metadata)
    
    # Relationships
    messages = relationship("Message", back_populates="agent", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="agent", cascade="all, delete-orphan")


class Message(Base):
    """Message model for conversation history"""
    __tablename__ = "omni_messages"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(String, ForeignKey("omni_agents.id", ondelete="CASCADE"))
    role = Column(String, nullable=False)  # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    
    agent = relationship("Agent", back_populates="messages")
    
    __table_args__ = (
        Index('idx_omni_agent_messages', 'agent_id', 'timestamp'),
    )


class Document(Base):
    """Document model for tracking uploaded files"""
    __tablename__ = "omni_documents"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(String, ForeignKey("omni_agents.id", ondelete="CASCADE"), nullable=False)
    filename = Column(String, nullable=False)
    file_type = Column(String)
    file_size = Column(Integer)
    content_preview = Column(Text)
    chunk_count = Column(Integer, default=0)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
    extra_data = Column(JSON, default={})
    embedding_time = Column(Float, default=0.0)  # Time taken to embed
    
    agent = relationship("Agent", back_populates="documents")
    
    __table_args__ = (
        Index('idx_omni_agent_documents', 'agent_id'),
    )


class UsageLog(Base):
    """Usage log for tracking tokens and cost"""
    __tablename__ = "omni_usage"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(String, ForeignKey("omni_agents.id", ondelete="SET NULL"))
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    model_name = Column(String)
    cost = Column(Float, default=0.0)
    latency = Column(Float, default=0.0)  # API latency in seconds
    
    agent = relationship("Agent")


class WebhookLog(Base):
    """Webhook log for capturing incoming webhooks"""
    __tablename__ = "omni_webhook_logs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    received_at = Column(DateTime(timezone=True), server_default=func.now())
    method = Column(String, nullable=False)
    url = Column(String, nullable=False)
    query_params = Column(Text)
    headers = Column(Text)  # JSON string
    body = Column(Text)  # JSON string
    source_ip = Column(String)
    
    __table_args__ = (
        Index('idx_omni_webhook_received', 'received_at'),
    )


class ParentChunk(Base):
    """Store large parent chunks for small-to-large retrieval"""
    __tablename__ = "omni_parent_chunks"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    content = Column(Text, nullable=False)
    source_doc_id = Column(Integer, ForeignKey("omni_documents.id", ondelete="CASCADE"), nullable=True)
    
    # Since children are in VectorDB (pgvector table), we just persist ID here.


class SemanticCache(Base):
    """Semantic Cache for frequent queries using pgvector"""
    __tablename__ = "omni_semantic_cache"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    question = Column(Text, nullable=False)
    embedding = Column(Vector(384))  # Assuming 384 dim (all-MiniLM), adjust if different
    answer = Column(Text, nullable=False)
    agent_id = Column(String, nullable=True)  # Optional: Cache per agent
    hit_count = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # We'll create HNSW index via SQL or relying on pgvector extension defaults
    # For now, standard table definition is enough for SQLAlchemy to map it.


# ============== DATABASE OPERATIONS ==============


def init_db():
    """Initialize database tables and performance indexes"""
    Base.metadata.create_all(bind=engine)
    print("[OK] OmniCortex database tables created")
    
    # Create performance indexes (idempotent)
    db = SessionLocal()
    try:
        # HNSW Index for Semantic Cache (fast vector similarity)
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_cache_embedding_hnsw 
            ON omni_semantic_cache 
            USING hnsw(embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64);
        """))
        
        # GIN Index for Full-Text Search on Parent Chunks
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_parent_fts 
            ON omni_parent_chunks 
            USING GIN(to_tsvector('english', content));
        """))
        
        db.commit()
        print("[OK] Performance indexes created (HNSW + GIN)")
    except Exception as e:
        print(f"[WARN] Index creation skipped: {e}")
        db.rollback()
    finally:
        db.close()


def get_session():
    """Get database session"""
    return SessionLocal()

# Usage Operations
def log_usage(agent_id: str, prompt_tokens: int, completion_tokens: int, 
              model_name: str, latency: float = 0.0):
    """Log token usage and latency"""
    db = SessionLocal()
    try:
        # Simple cost estimation
        cost_input = 0.0
        cost_output = 0.0
        
        if "llama-3" in model_name.lower():
            cost_input = (prompt_tokens / 1_000_000) * 0.50
            cost_output = (completion_tokens / 1_000_000) * 0.70
            
        total_tokens = prompt_tokens + completion_tokens
        total_cost = cost_input + cost_output
        
        log = UsageLog(
            agent_id=agent_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            model_name=model_name,
            cost=total_cost,
            latency=latency
        )
        db.add(log)
        db.commit()
    finally:
        db.close()


def get_usage_stats(limit: int = 100):
    """Get usage statistics"""
    db = SessionLocal()
    try:
        logs = db.query(UsageLog).order_by(UsageLog.timestamp.desc()).limit(limit).all()
        return [
            {
                "timestamp": l.timestamp,
                "agent_id": l.agent_id,
                "model": l.model_name,
                "total_tokens": l.total_tokens,
                "prompt_tokens": l.prompt_tokens,
                "completion_tokens": l.completion_tokens,
                "cost": l.cost,
                "latency": getattr(l, 'latency', 0.0)
            }
            for l in logs
        ]
    finally:
        db.close()


# Webhook Log Operations
def save_webhook_log(method: str, url: str, query_params: str = None, 
                     headers: str = None, body: str = None, source_ip: str = None):
    """Save incoming webhook to database"""
    db = SessionLocal()
    try:
        log = WebhookLog(
            method=method,
            url=url,
            query_params=query_params,
            headers=headers,
            body=body,
            source_ip=source_ip
        )
        db.add(log)
        db.commit()
        return log.id
    finally:
        db.close()


def get_webhook_logs(limit: int = 50, offset: int = 0):
    """Get webhook logs with pagination"""
    db = SessionLocal()
    try:
        total = db.query(WebhookLog).count()
        logs = db.query(WebhookLog).order_by(WebhookLog.received_at.desc()).offset(offset).limit(limit).all()
        return {
            "total": total,
            "logs": [
                {
                    "id": l.id,
                    "received_at": l.received_at,
                    "method": l.method,
                    "url": l.url,
                    "query_params": l.query_params,
                    "headers": l.headers,
                    "body": l.body,
                    "source_ip": l.source_ip
                }
                for l in logs
            ]
        }
    finally:
        db.close()


def clear_webhook_logs():
    """Clear all webhook logs"""
    db = SessionLocal()
    try:
        db.query(WebhookLog).delete()
        db.commit()
    finally:
        db.close()


# Message Operations
def save_message(role: str, content: str, agent_id: str = None):
    """Save a message to the database"""
    db = SessionLocal()
    try:
        message = Message(agent_id=agent_id, role=role, content=content)
        db.add(message)
        
        if agent_id:
            agent = db.query(Agent).filter(Agent.id == agent_id).first()
            if agent:
                agent.message_count = (agent.message_count or 0) + 1
        
        db.commit()
    finally:
        db.close()


def get_conversation_history(agent_id: str = None, limit: int = None) -> List[Dict]:
    """Get conversation history"""
    db = SessionLocal()
    try:
        query = db.query(Message).order_by(Message.timestamp.desc())
        if agent_id:
            query = query.filter(Message.agent_id == agent_id)
        if limit:
            query = query.limit(limit)
        
        messages = query.all()
        return [
            {"role": msg.role, "content": msg.content, 
             "timestamp": msg.timestamp.isoformat() if msg.timestamp else None}
            for msg in reversed(messages)
        ]
    finally:
        db.close()


def clear_history(agent_id: str = None):
    """Clear conversation history"""
    db = SessionLocal()
    try:
        query = db.query(Message)
        if agent_id:
            query = query.filter(Message.agent_id == agent_id)
        query.delete()
        db.commit()
    finally:
        db.close()

# Document Operations
def save_document_metadata(agent_id: str, filename: str, file_type: str = None,
                          file_size: int = None, content_preview: str = None,
                          chunk_count: int = 0, metadata: dict = None,
                          embedding_time: float = 0.0) -> int:
    """Save document metadata"""
    db = SessionLocal()
    try:
        doc = Document(
            agent_id=agent_id,
            filename=filename,
            file_type=file_type,
            file_size=file_size,
            content_preview=content_preview[:500] if content_preview else None,
            chunk_count=chunk_count,
            extra_data=metadata or {},
            embedding_time=embedding_time
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        return doc.id
    finally:
        db.close()


def get_agent_documents(agent_id: str) -> List[Dict]:
    """Get all documents for an agent"""
    db = SessionLocal()
    try:
        docs = db.query(Document).filter(Document.agent_id == agent_id).order_by(Document.uploaded_at.desc()).all()
        return [
            {
                "id": doc.id,
                "filename": doc.filename,
                "file_type": doc.file_type,
                "file_size": doc.file_size,
                "content_preview": doc.content_preview,
                "chunk_count": doc.chunk_count,
                "uploaded_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
                "metadata": doc.extra_data,
                "embedding_time": getattr(doc, 'embedding_time', 0.0)
            }
            for doc in docs
        ]
    finally:
        db.close()


def delete_document(document_id: int) -> bool:
    """Delete a document and update agent count"""
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == document_id).first()
        if doc:
            agent_id = doc.agent_id
            db.delete(doc)
            
            # Update agent document count
            if agent_id:
                agent = db.query(Agent).filter(Agent.id == agent_id).first()
                if agent and agent.document_count > 0:
                    agent.document_count = agent.document_count - 1
            
            db.commit()
            return True
        return False
    finally:
        db.close()


# Parent Chunk Operations
def save_parent_chunk(content: str, source_doc_id: int = None) -> int:
    """Save a parent chunk and return its ID"""
    db = SessionLocal()
    try:
        chunk = ParentChunk(content=content, source_doc_id=source_doc_id)
        db.add(chunk)
        db.commit()
        db.refresh(chunk)
        return chunk.id
    finally:
        db.close()


def batch_save_parent_chunks(chunks: list, source_doc_id: int = None) -> list:
    """
    Batch save multiple parent chunks in a single transaction.
    Returns list of (content_hash, id) tuples for mapping.
    
    Args:
        chunks: List of unique parent content strings
        source_doc_id: Optional document ID to link
    
    Returns:
        Dict mapping content -> id
    """
    db = SessionLocal()
    try:
        content_to_id = {}
        objects = []
        
        for content in chunks:
            obj = ParentChunk(content=content, source_doc_id=source_doc_id)
            objects.append(obj)
        
        db.bulk_save_objects(objects, return_defaults=True)
        db.commit()
        
        # Map content to IDs
        for obj in objects:
            content_to_id[obj.content] = obj.id
            
        print(f"✅ Batch saved {len(objects)} parent chunks")
        return content_to_id
        
    except Exception as e:
        print(f"⚠️ Batch save failed: {e}")
        db.rollback()
        return {}
    finally:
        db.close()


def get_parent_chunk(chunk_id: int) -> str:
    """Get content of a parent chunk"""
    db = SessionLocal()
    try:
        chunk = db.query(ParentChunk).filter(ParentChunk.id == chunk_id).first()
        return chunk.content if chunk else None
    finally:
        db.close()


# Initialize on import
try:
    init_db()
except Exception as e:
    print(f"[WARN] Database init warning: {e}")
