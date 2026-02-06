"""
Semantic Cache Module
Uses Postgres pgvector to cache and retrieve LLM responses.
"""
from typing import Optional
from sqlalchemy import text
from .database import get_session, SemanticCache
from .rag.embeddings import get_embeddings
import numpy as np

# Cache Configuration
CACHE_THRESHOLD = 0.92  # High similarity required
CACHE_TTL = 3600 * 24   # 24 Hours (Not implemented in DB clean yet, but logical TTL)

def check_cache(question: str, agent_id: str = None) -> Optional[str]:
    """
    Check if a similar question has been answered recently.
    Returns the cached answer or None.
    """
    try:
        embeddings = get_embeddings()
        q_vec = embeddings.embed_query(question)
        
        db = get_session()
        
        # Search for similar questions
        # Operator <-> is Euclidean distance, <=> is Cosine distance, <#> is Negative Inner Product
        # For normalized embeddings, cosine distance <=> is 1 - cosine_similarity.
        # So we want distance < (1 - threshold). e.g. < 0.08
        
        threshold_distance = 1 - CACHE_THRESHOLD
        
        # Query with distance filter
        # Note: pgvector < 0.5.0 uses <-> for everything, check version if issues arise. 
        # Using cosine distance operator <=>
        
        sql = """
        SELECT answer, 1 - (embedding <=> :q_vec) as similarity
        FROM omni_semantic_cache
        WHERE 1 - (embedding <=> :q_vec) > :threshold
        """
        params = {
            "q_vec": str(q_vec), # pgvector expects string representation sometimes, or list
            "threshold": CACHE_THRESHOLD
        }
        
        if agent_id:
            sql += " AND (agent_id = :agent_id OR agent_id IS NULL)"
            params["agent_id"] = agent_id
            
        sql += " ORDER BY similarity DESC LIMIT 1"
        
        # Execute
        result = db.execute(text(sql), params).fetchone()
        
        if result:
            print(f"⚡ Cache Hit! Similarity: {result.similarity:.3f}")
            # Update hit count? (Optional, adds write latency)
            return result.answer
            
        return None
        
    except Exception as e:
        print(f"⚠️ Cache check failed: {e}")
        return None
    finally:
        if 'db' in locals():
            db.close()


def save_to_cache(question: str, answer: str, agent_id: str = None):
    """
    Save a question-answer pair to the cache.
    """
    try:
        embeddings = get_embeddings()
        q_vec = embeddings.embed_query(question)
        
        db = get_session()
        cache_entry = SemanticCache(
            question=question,
            answer=answer,
            embedding=q_vec,
            agent_id=agent_id
        )
        db.add(cache_entry)
        db.commit()
    except Exception as e:
        print(f"⚠️ Failed to save to cache: {e}")
    finally:
        if 'db' in locals():
            db.close()
