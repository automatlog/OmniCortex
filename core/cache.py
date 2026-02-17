"""
Semantic cache module.
Uses Postgres pgvector to cache and retrieve LLM responses.
"""
from typing import Optional

from sqlalchemy import text

from .database import SemanticCache, get_session
from .rag.embeddings import get_embeddings


# Cache configuration
CACHE_THRESHOLD = 0.92
CACHE_TTL = 3600 * 24  # 24 hours


def check_cache(question: str, agent_id: str = None) -> Optional[str]:
    """
    Check if a similar question has been answered recently.
    Returns the cached answer or None.
    """
    try:
        embeddings = get_embeddings()
        q_vec = embeddings.embed_query(question)

        db = get_session()
        sql = """
        SELECT answer, 1 - (embedding <=> :q_vec) as similarity
        FROM omni_semantic_cache
        WHERE 1 - (embedding <=> :q_vec) > :threshold
          AND created_at > NOW() - make_interval(secs => :ttl_seconds)
        """
        params = {
            "q_vec": str(q_vec),
            "threshold": CACHE_THRESHOLD,
            "ttl_seconds": CACHE_TTL,
        }

        if agent_id:
            sql += " AND (agent_id = :agent_id OR agent_id IS NULL)"
            params["agent_id"] = agent_id

        sql += " ORDER BY similarity DESC LIMIT 1"
        result = db.execute(text(sql), params).fetchone()

        if result:
            print(f"[CACHE] Hit. Similarity: {result.similarity:.3f}")
            return result.answer
        return None
    except Exception as e:
        print(f"[WARN] Cache check failed: {e}")
        return None
    finally:
        if "db" in locals():
            db.close()


def save_to_cache(question: str, answer: str, agent_id: str = None):
    """Save a question-answer pair to the cache."""
    try:
        embeddings = get_embeddings()
        q_vec = embeddings.embed_query(question)

        db = get_session()
        cache_entry = SemanticCache(
            question=question,
            answer=answer,
            embedding=q_vec,
            agent_id=agent_id,
        )
        db.add(cache_entry)
        db.commit()
    except Exception as e:
        print(f"[WARN] Failed to save to cache: {e}")
    finally:
        if "db" in locals():
            db.close()
