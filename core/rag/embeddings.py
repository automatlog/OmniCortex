"""
Embedding model handling with caching and fallbacks.
"""
import logging
import os
import threading
from langchain_huggingface import HuggingFaceEmbeddings
from ..config import EMBEDDING_MODEL


logger = logging.getLogger(__name__)
_EMBEDDINGS_INSTANCE = None
_EMBEDDINGS_LOCK = threading.Lock()


def _embedding_candidates() -> list[str]:
    candidates: list[str] = []
    primary = str(EMBEDDING_MODEL or "").strip()
    if primary:
        candidates.append(primary)

    raw_fallbacks = str(
        os.getenv("EMBEDDING_MODEL_FALLBACKS", "")
    ).strip()
    if raw_fallbacks:
        for item in raw_fallbacks.split(","):
            candidate = item.strip()
            if candidate and candidate not in candidates:
                candidates.append(candidate)

    return candidates


def get_embeddings():
    """Get or create embeddings model (cached, thread-safe, with fallback list)."""
    global _EMBEDDINGS_INSTANCE
    if _EMBEDDINGS_INSTANCE is not None:
        return _EMBEDDINGS_INSTANCE

    with _EMBEDDINGS_LOCK:
        # Double-checked locking.
        if _EMBEDDINGS_INSTANCE is not None:
            return _EMBEDDINGS_INSTANCE

        # If fast-transfer is enabled but package is missing, force fallback to regular download.
        if os.getenv("HF_HUB_ENABLE_HF_TRANSFER", "").strip() == "1":
            try:
                import hf_transfer  # noqa: F401
            except Exception:
                os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"

        candidates = _embedding_candidates()
        errors: list[str] = []
        primary_model = str(EMBEDDING_MODEL or "").strip()

        for model_name in candidates:
            try:
                instance = HuggingFaceEmbeddings(model_name=model_name)
                _EMBEDDINGS_INSTANCE = instance
                if model_name != primary_model:
                    logger.warning(
                        "Embedding model fallback active: '%s' -> '%s'",
                        primary_model,
                        model_name,
                    )
                else:
                    logger.info("Embedding model loaded: %s", model_name)
                return instance
            except Exception as exc:
                errors.append(f"{model_name}: {exc}")

        # Don't cache the error — allow retry on next call for transient failures.
        raise RuntimeError(
            "Embeddings unavailable. Tried candidates: " + " | ".join(errors)
        )
