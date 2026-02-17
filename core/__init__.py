"""
OmniCortex Core Module
Modern RAG with semantic chunking, Groq/vLLM, LangGraph
"""

# Config
from .config import DATABASE_URL, LLM_MODEL

# Database
from .database import (
    save_message,
    get_conversation_history,
    clear_history,
    get_agent_documents,
    delete_document,
    save_document_metadata,
    log_usage,
    get_usage_stats
)



# Agents
from .agent_manager import (
    create_agent,
    get_agent,
    get_all_agents,
    update_agent,
    delete_agent,
    update_agent_metadata
)

# Vector Store
from .rag.vector_store import (
    create_vector_store,
    load_vector_store,
    search_documents,
    delete_vector_store,
    get_vector_count
)

# Chat
from .chat_service import process_question, process_documents

# LLM
from .llm import get_llm, invoke_chain, reset_chain

# Model Loader
# Prompts
from .prompts import (
    RAG_SYSTEM_PROMPT,
    TOOL_AGENT_PROMPT,
    get_agent_prompt,
    get_chat_prompt
)

# LangGraph
from .graph import AgentGraph, create_rag_agent, create_tool_agent

__all__ = [
    # Config
    'DATABASE_URL', 'LLM_MODEL',
    
    # Database
    'save_message', 'get_conversation_history', 'clear_history',
    'get_agent_documents', 'delete_document', 'save_document_metadata',
    'log_usage', 'get_usage_stats',
    
    # Agents
    'create_agent', 'get_agent', 'get_all_agents', 
    'update_agent', 'delete_agent', 'update_agent_metadata',
    
    # Vectors
    'create_vector_store', 'load_vector_store', 
    'search_documents', 'delete_vector_store', 'get_vector_count',
    
    # Chat
    'process_question', 'process_documents',
    
    # LLM
    'get_llm', 'invoke_chain', 'reset_chain',
    
    # Prompts
    'RAG_SYSTEM_PROMPT', 'TOOL_AGENT_PROMPT',
    'get_agent_prompt', 'get_chat_prompt',
    
    # LangGraph
    'AgentGraph', 'create_rag_agent', 'create_tool_agent'
]
