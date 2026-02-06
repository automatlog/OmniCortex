"""
WhatsApp Conversation History Manager
Persistent conversation storage for WhatsApp users.
"""
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from threading import Lock

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.sql import func

from .database import Base, SessionLocal, engine


# ============== DATABASE MODEL ==============

class WhatsAppSession(Base):
    """WhatsApp conversation session"""
    __tablename__ = "omni_whatsapp_sessions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    phone_number = Column(String, unique=True, nullable=False, index=True)
    agent_id = Column(String, nullable=True)
    last_active = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    

class WhatsAppMessage(Base):
    """WhatsApp conversation message"""
    __tablename__ = "omni_whatsapp_messages"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    phone_number = Column(String, nullable=False, index=True)
    role = Column(String, nullable=False)  # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())


# Create tables
try:
    Base.metadata.create_all(bind=engine)
except Exception as e:
    print(f"[WARN] WhatsApp history tables: {e}")


# ============== HISTORY MANAGER ==============

@dataclass
class ConversationTurn:
    """Single conversation turn"""
    role: str
    content: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


class WhatsAppHistoryManager:
    """
    Manages persistent conversation history for WhatsApp users.
    
    Features:
    - Per-phone-number conversation storage
    - Automatic session management
    - Memory limiting (max turns per conversation)
    - Session timeout handling
    """
    
    def __init__(
        self,
        max_history: int = 10,
        session_timeout_hours: int = 24
    ):
        self.max_history = max_history
        self.session_timeout = timedelta(hours=session_timeout_hours)
        self._cache: Dict[str, List[ConversationTurn]] = {}
        self._lock = Lock()
    
    def get_or_create_session(self, phone_number: str, agent_id: str = None) -> int:
        """Get or create a session for a phone number"""
        session = SessionLocal()
        try:
            wa_session = session.query(WhatsAppSession).filter_by(
                phone_number=phone_number
            ).first()
            
            if wa_session:
                # Check if session expired
                if wa_session.last_active < datetime.utcnow() - self.session_timeout:
                    # Clear old messages
                    self._clear_messages(phone_number)
                    with self._lock:
                        self._cache.pop(phone_number, None)
                
                # Update session
                wa_session.last_active = datetime.utcnow()
                if agent_id:
                    wa_session.agent_id = agent_id
                session.commit()
                return wa_session.id
            else:
                # Create new session
                wa_session = WhatsAppSession(
                    phone_number=phone_number,
                    agent_id=agent_id
                )
                session.add(wa_session)
                session.commit()
                return wa_session.id
        finally:
            session.close()
    
    def add_message(self, phone_number: str, role: str, content: str):
        """Add a message to conversation history"""
        session = SessionLocal()
        try:
            msg = WhatsAppMessage(
                phone_number=phone_number,
                role=role,
                content=content
            )
            session.add(msg)
            session.commit()
            
            # Update cache
            with self._lock:
                if phone_number not in self._cache:
                    self._cache[phone_number] = []
                self._cache[phone_number].append(ConversationTurn(role, content))
                
                # Limit cache size
                if len(self._cache[phone_number]) > self.max_history * 2:
                    self._cache[phone_number] = self._cache[phone_number][-self.max_history:]
        finally:
            session.close()
    
    def get_history(
        self, 
        phone_number: str, 
        limit: int = None
    ) -> List[Tuple[str, str]]:
        """
        Get conversation history for a phone number.
        
        Returns:
            List of (role, content) tuples
        """
        limit = limit or self.max_history
        
        # Check cache first
        with self._lock:
            if phone_number in self._cache:
                cached = self._cache[phone_number][-limit:]
                return [(t.role, t.content) for t in cached]
        
        # Load from database
        session = SessionLocal()
        try:
            messages = session.query(WhatsAppMessage).filter_by(
                phone_number=phone_number
            ).order_by(
                WhatsAppMessage.timestamp.desc()
            ).limit(limit).all()
            
            # Reverse to get chronological order
            messages = list(reversed(messages))
            
            # Update cache
            with self._lock:
                self._cache[phone_number] = [
                    ConversationTurn(m.role, m.content, m.timestamp)
                    for m in messages
                ]
            
            return [(m.role, m.content) for m in messages]
        finally:
            session.close()
    
    def get_history_for_llm(self, phone_number: str, limit: int = None) -> List[dict]:
        """
        Get history formatted for LLM consumption.
        
        Returns:
            List of {"role": ..., "content": ...} dicts
        """
        history = self.get_history(phone_number, limit)
        return [{"role": role, "content": content} for role, content in history]
    
    def _clear_messages(self, phone_number: str):
        """Clear all messages for a phone number"""
        session = SessionLocal()
        try:
            session.query(WhatsAppMessage).filter_by(
                phone_number=phone_number
            ).delete()
            session.commit()
        finally:
            session.close()
    
    def clear_history(self, phone_number: str):
        """Clear conversation history for a phone number"""
        self._clear_messages(phone_number)
        with self._lock:
            self._cache.pop(phone_number, None)
    
    def get_agent_for_phone(self, phone_number: str) -> Optional[str]:
        """Get the assigned agent ID for a phone number"""
        session = SessionLocal()
        try:
            wa_session = session.query(WhatsAppSession).filter_by(
                phone_number=phone_number
            ).first()
            return wa_session.agent_id if wa_session else None
        finally:
            session.close()
    
    def set_agent_for_phone(self, phone_number: str, agent_id: str):
        """Set the agent for a phone number"""
        session = SessionLocal()
        try:
            wa_session = session.query(WhatsAppSession).filter_by(
                phone_number=phone_number
            ).first()
            if wa_session:
                wa_session.agent_id = agent_id
                session.commit()
            else:
                self.get_or_create_session(phone_number, agent_id)
        finally:
            session.close()


# Singleton instance
_history_manager: Optional[WhatsAppHistoryManager] = None


def get_whatsapp_history() -> WhatsAppHistoryManager:
    """Get or create WhatsApp history manager singleton"""
    global _history_manager
    if _history_manager is None:
        _history_manager = WhatsAppHistoryManager(
            max_history=int(os.getenv("MAX_HISTORY_LIMIT", "20")),
            session_timeout_hours=24
        )
    return _history_manager


# Missing import
import os
