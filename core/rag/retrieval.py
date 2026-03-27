"""
Advanced Retrieval Module
- Hybrid Search (Vector + Keyword)
- Reciprocal Rank Fusion (RRF)
- Cross-Encoder Reranking
"""
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import List, Dict, Any, Optional
from sqlalchemy import text
from ..database import get_session, ParentChunk
from .vector_store import search_documents as vector_search_func
import os

# Lazy load reranker model to save startup time/memory if not used
_RERANKER_MODEL = None
_VECTOR_FAILURE_REASON = None

def get_reranker():
    global _RERANKER_MODEL
    if _RERANKER_MODEL is None:
        model_name = os.getenv("RERANKER_MODEL_NAME", "BAAI/bge-reranker-large")
        print(f"🔹 Loading Reranker: {model_name}...")
        # Lazy import prevents import-time dependency crashes when reranker is disabled.
        from sentence_transformers import CrossEncoder
        _RERANKER_MODEL = CrossEncoder(model_name)
    return _RERANKER_MODEL


def keyword_search(query: str, agent_id: str = None, k: int = 10) -> List[Dict]:
    """
    Perform keyword search on ParentChunks using Postgres Full-Text Search (tsvector)
    Much faster than ILIKE for large datasets.
    """
    db = get_session()
    try:
        # Use plainto_tsquery for safer query parsing (handles special chars)
        # to_tsvector creates searchable tokens from content
        sql = """
        SELECT p.id, p.content, d.agent_id,
               ts_rank(to_tsvector('english', p.content), plainto_tsquery('english', :query)) as rank
        FROM omni_parent_chunks p
        LEFT JOIN omni_documents d ON p.source_doc_id = d.id
        WHERE to_tsvector('english', p.content) @@ plainto_tsquery('english', :query)
        """
        params = {"query": query}

        if agent_id:
            sql += " AND (d.agent_id = :agent_id OR d.agent_id IS NULL)"
            params["agent_id"] = agent_id
            
        sql += " ORDER BY rank DESC"
        sql += " LIMIT :limit_k"
        params["limit_k"] = k
        
        results = db.execute(text(sql), params).fetchall()
        
        return [
            {"content": r.content, "metadata": {"id": r.id, "source": "keyword", "rank": r.rank}}
            for r in results
        ]
    except Exception as e:
        print(f"⚠️ Keyword search failed: {e}")
        return []
    finally:
        db.close()


def reciprocal_rank_fusion(results: Dict[str, List[Any]], k=60):
    """
    Fuse results from multiple lists using RRF
    results: {"vector": [...], "keyword": [...]}
    """
    fused_scores = {}
    
    for source, docs in results.items():
        for rank, doc in enumerate(docs):
            # Use content as key for deduplication (simple approach)
            doc_content = doc.get("page_content") or doc.get("content")
            if not doc_content:
                continue
                
            if doc_content not in fused_scores:
                fused_scores[doc_content] = {"doc": doc, "score": 0.0}
            
            fused_scores[doc_content]["score"] += 1.0 / (k + rank + 1)
            
    # Sort by Score
    reranked = sorted(fused_scores.values(), key=lambda x: x["score"], reverse=True)
    return [item["doc"] for item in reranked]


def rerank_documents(query: str, docs: List[Any], top_n: int = 4) -> List[Any]:
    """
    Rerank documents using Cross-Encoder
    """
    if not docs:
        return []
        
    try:
        reranker = get_reranker()
        
        # Prepare pairs [Query, Doc Text]
        doc_texts = [d.get("page_content") or d.get("content") for d in docs]
        pairs = [[query, text] for text in doc_texts]
        
        scores = reranker.predict(pairs)
        
        # Attach scores and sort
        scored_docs = []
        for i, doc in enumerate(docs):
            doc_copy = doc.copy() if isinstance(doc, dict) else doc
            # If object, simple monkey patch or wrapper?
            # It returns Langchain Documents usually
            scored_docs.append((doc, scores[i]))
            
        # Sort desc
        scored_docs.sort(key=lambda x: x[1], reverse=True)
        
        print(f"✅ Reranked {len(docs)} documents")
        return [d[0] for d in scored_docs[:top_n]]
        
    except Exception as e:
        print(f"⚠️ Reranking failed: {e}")
        return docs[:top_n]


def hybrid_search(query: str, agent_id: str = None, top_k: int = 5, rerank: Optional[bool] = None) -> List[Any]:
    """
    Main entry point: Hybrid Search (Vector + Keyword) -> RRF -> Rerank
    Vector and keyword searches run in parallel via ThreadPoolExecutor.
    """
    use_reranker = (os.getenv("USE_RERANKER", "false").lower() == "true") if rerank is None else rerank

    print(f"🔍 Hybrid Search: '{query}'")

    # 1. Parallel retrieval — both searches are I/O-bound DB/model calls.
    global _VECTOR_FAILURE_REASON
    with ThreadPoolExecutor(max_workers=2) as _pool:
        _fut_vector = _pool.submit(vector_search_func, query, agent_id, top_k * 2)
        _fut_keyword = _pool.submit(keyword_search, query, agent_id, top_k * 2)

        try:
            vector_docs = _fut_vector.result(timeout=15)
        except FutureTimeoutError:
            print("[WARN] Vector search timed out")
            vector_docs = []
        except Exception as e:
            reason = str(e)
            if reason != _VECTOR_FAILURE_REASON:
                print(f"[WARN] Vector search failed: {reason}")
                _VECTOR_FAILURE_REASON = reason
            vector_docs = []

        try:
            keyword_docs = _fut_keyword.result(timeout=15)
        except Exception as e:
            print(f"[WARN] Keyword search failed: {e}")
            keyword_docs = []

    print(f"   Found: {len(vector_docs)} vector, {len(keyword_docs)} keyword candidates")
    
    # 2. RRF Fusion
    # Convert keyword dicts to objects compatible if needed, or normalize
    # For now, let's normalize vector docs to dicts or vice versa?
    # Vector search returns objects with .page_content.
    
    # Normalize Vector Docs
    norm_vector = []
    for d in vector_docs:
        norm_vector.append({
            "content": d.page_content,
            "metadata": d.metadata,
            "source": "vector"
        })
        
    all_docs = reciprocal_rank_fusion({"vector": norm_vector, "keyword": keyword_docs})
    
    # 3. Reranking (only if enabled)
    if use_reranker:
        print("🔄 Reranking enabled")
        final_docs = rerank_documents(query, all_docs, top_n=top_k)
    else:
        print("⚡ Reranking disabled - using RRF results")
        final_docs = all_docs[:top_k]
    
    return final_docs
