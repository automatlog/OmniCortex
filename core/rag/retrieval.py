"""
Advanced Retrieval Module
- Hybrid Search (Vector + Keyword)
- Reciprocal Rank Fusion (RRF)
- Cross-Encoder Reranking
"""

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
import threading
import time
from typing import Any, Dict, List, Optional
import os

from sqlalchemy import text

from ..database import get_session
from .vector_store import search_documents as vector_search_func

# Lazy load reranker model to save startup time/memory if not used.
_RERANKER_MODEL = None
_RERANKER_LOADED_NAME: Optional[str] = None

_VECTOR_FAILURE_LOCK = threading.Lock()
_LAST_VECTOR_FAILURE_AT: Optional[float] = None
_VECTOR_FAILURE_THROTTLE_SECONDS = max(
    1.0,
    float(os.getenv("VECTOR_FAILURE_LOG_THROTTLE_SECONDS", "60")),
)


def get_reranker(model_name: str = None):
    global _RERANKER_MODEL, _RERANKER_LOADED_NAME
    resolved_name = model_name or os.getenv("RERANKER_MODEL_NAME", "BAAI/bge-reranker-large")
    
    # First check (without lock)
    if _RERANKER_MODEL is not None:
        if model_name and model_name != _RERANKER_LOADED_NAME:
            print(
                f"[WARN] Reranker model mismatch: requested={model_name}, "
                f"loaded={_RERANKER_LOADED_NAME}; using loaded model"
            )
        return _RERANKER_MODEL
    
    # Acquire lock for initialization
    with _VECTOR_FAILURE_LOCK:
        # Second check (with lock) to ensure another thread didn't beat us
        if _RERANKER_MODEL is not None:
            if model_name and model_name != _RERANKER_LOADED_NAME:
                print(
                    f"[WARN] Reranker model mismatch: requested={model_name}, "
                    f"loaded={_RERANKER_LOADED_NAME}; using loaded model"
                )
            return _RERANKER_MODEL
        
        # Load the model while holding the lock
        print(f"[retrieval] loading reranker: {resolved_name}")
        from sentence_transformers import CrossEncoder

        _RERANKER_MODEL = CrossEncoder(resolved_name)
        _RERANKER_LOADED_NAME = resolved_name
    
    return _RERANKER_MODEL


def keyword_search(query: str, agent_id: str = None, k: int = 10) -> List[Dict[str, Any]]:
    """
    Perform keyword search on ParentChunks using Postgres Full-Text Search (tsvector).
    """
    db = get_session()
    try:
        sql = """
        SELECT p.id, p.content, d.agent_id,
               ts_rank(to_tsvector('english', p.content), plainto_tsquery('english', :query)) as rank
        FROM omni_parent_chunks p
        LEFT JOIN omni_documents d ON p.source_doc_id = d.id
        WHERE to_tsvector('english', p.content) @@ plainto_tsquery('english', :query)
        """
        params: Dict[str, Any] = {"query": query}

        if agent_id:
            sql += " AND (d.agent_id = :agent_id OR d.agent_id IS NULL)"
            params["agent_id"] = agent_id

        sql += " ORDER BY rank DESC"
        sql += " LIMIT :limit_k"
        params["limit_k"] = k

        results = db.execute(text(sql), params).fetchall()
        return [
            {"content": row.content, "metadata": {"id": row.id, "source": "keyword", "rank": row.rank}}
            for row in results
        ]
    except Exception as e:
        print(f"[WARN] Keyword search failed: {e}")
        return []
    finally:
        db.close()


def reciprocal_rank_fusion(results: Dict[str, List[Any]], k: int = 60) -> List[Any]:
    """
    Fuse results from multiple lists using RRF.
    results: {"vector": [...], "keyword": [...]}
    """
    fused_scores: Dict[str, Dict[str, Any]] = {}

    for _, docs in results.items():
        for rank, doc in enumerate(docs):
            doc_content = doc.get("page_content") or doc.get("content")
            if not doc_content:
                continue
            if doc_content not in fused_scores:
                fused_scores[doc_content] = {"doc": doc, "score": 0.0}
            fused_scores[doc_content]["score"] += 1.0 / (k + rank + 1)

    reranked = sorted(fused_scores.values(), key=lambda item: item["score"], reverse=True)
    return [item["doc"] for item in reranked]


def rerank_documents(
    query: str,
    docs: List[Any],
    top_n: int = 4,
    reranker_model: str = None,
) -> List[Any]:
    """
    Rerank documents using Cross-Encoder.
    """
    if not docs:
        return []

    try:
        reranker = get_reranker(model_name=reranker_model)
        doc_texts = [doc.get("page_content") or doc.get("content") for doc in docs]
        pairs = [[query, text] for text in doc_texts]
        scores = reranker.predict(pairs)

        scored_docs = [(doc, scores[i]) for i, doc in enumerate(docs)]
        scored_docs.sort(key=lambda item: item[1], reverse=True)
        print(f"[retrieval] reranked {len(docs)} documents")
        return [item[0] for item in scored_docs[:top_n]]
    except Exception as e:
        print(f"[WARN] Reranking failed: {e}")
        return docs[:top_n]


def _resolve_vector_docs(query: str, agent_id: Optional[str], limit_k: int) -> List[Any]:
    global _LAST_VECTOR_FAILURE_AT
    try:
        docs = vector_search_func(query, agent_id, limit_k)
        with _VECTOR_FAILURE_LOCK:
            _LAST_VECTOR_FAILURE_AT = None
        return docs
    except Exception as e:
        now = time.monotonic()
        should_log = False
        with _VECTOR_FAILURE_LOCK:
            if (
                _LAST_VECTOR_FAILURE_AT is None
                or (now - _LAST_VECTOR_FAILURE_AT) >= _VECTOR_FAILURE_THROTTLE_SECONDS
            ):
                _LAST_VECTOR_FAILURE_AT = now
                should_log = True
        if should_log:
            print(f"[WARN] Vector search failed: {e}")
        return []


def hybrid_search(
    query: str,
    agent_id: str = None,
    top_k: int = 5,
    use_hybrid: Optional[bool] = None,
    rerank: Optional[bool] = None,
    reranker_model: Optional[str] = None,
) -> List[Any]:
    """
    Main retrieval entry point.

    - use_hybrid=True: Vector + keyword in parallel, fused by RRF.
    - use_hybrid=False: Vector-only retrieval, with keyword fallback if vector is empty.
    """
    use_hybrid_search = (
        os.getenv("USE_HYBRID_SEARCH", "true").lower() == "true"
        if use_hybrid is None
        else bool(use_hybrid)
    )
    use_reranker = (
        os.getenv("USE_RERANKER", "false").lower() == "true"
        if rerank is None
        else bool(rerank)
    )

    mode_label = "hybrid" if use_hybrid_search else "vector-only"
    print(f"[retrieval] {mode_label} query: {query!r}")

    vector_docs: List[Any] = []
    keyword_docs: List[Dict[str, Any]] = []

    if use_hybrid_search:
        with ThreadPoolExecutor(max_workers=2) as pool:
            fut_vector = pool.submit(_resolve_vector_docs, query, agent_id, top_k * 2)
            fut_keyword = pool.submit(keyword_search, query, agent_id, top_k * 2)

            try:
                vector_docs = fut_vector.result(timeout=15)
            except FutureTimeoutError:
                print("[WARN] Vector search timed out")
                vector_docs = []
            except Exception as e:
                print(f"[WARN] Vector search failed: {e}")
                vector_docs = []

            try:
                keyword_docs = fut_keyword.result(timeout=15)
            except Exception as e:
                print(f"[WARN] Keyword search failed: {e}")
                keyword_docs = []
    else:
        vector_docs = _resolve_vector_docs(query, agent_id, top_k * 2)
        if not vector_docs:
            keyword_docs = keyword_search(query, agent_id, top_k * 2)
            if keyword_docs:
                print("[retrieval] vector-empty fallback to keyword search")

    print(f"[retrieval] candidates vector={len(vector_docs)} keyword={len(keyword_docs)}")

    norm_vector = [
        {
            "content": doc.page_content,
            "metadata": doc.metadata,
            "source": "vector",
        }
        for doc in vector_docs
    ]

    if use_hybrid_search:
        all_docs = reciprocal_rank_fusion({"vector": norm_vector, "keyword": keyword_docs})
    else:
        all_docs = norm_vector if norm_vector else keyword_docs

    if use_reranker:
        print("[retrieval] reranker enabled")
        return rerank_documents(query, all_docs, top_n=top_k, reranker_model=reranker_model)

    print("[retrieval] reranker disabled")
    return all_docs[:top_k]

