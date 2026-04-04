"""
Embedding model handling with caching and fallbacks.
"""
import logging
import os
import threading
from pathlib import Path

from langchain_huggingface import HuggingFaceEmbeddings
from ..config import EMBEDDING_DIM, EMBEDDING_MODEL


logger = logging.getLogger(__name__)
_EMBEDDINGS_INSTANCE = None
_EMBEDDINGS_LOCK = threading.Lock()


def _default_embedding_fallbacks() -> list[str]:
    try:
        dim = int(EMBEDDING_DIM or 0)
    except (ValueError, TypeError):
        logger.warning("Invalid EMBEDDING_DIM value; using default 1024")
        dim = 1024
    if dim >= 1024:
        return [
            "BAAI/bge-large-en-v1.5",
        ]
    if dim >= 768:
        return [
            "BAAI/bge-base-en-v1.5",
            "sentence-transformers/all-mpnet-base-v2",
        ]
    return [
        "sentence-transformers/all-MiniLM-L6-v2",
    ]


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

    for candidate in _default_embedding_fallbacks():
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    return candidates


def _local_model_hint(model_name: str) -> str:
    try:
        path = Path(model_name)
        if not path.exists():
            return ""
        cfg = path / "config.json"
        return f" local_path={path.resolve()} config_json={'yes' if cfg.exists() else 'no'}"
    except Exception:
        return ""


def _model_kwargs() -> dict:
    kwargs = {}
    token = (
        os.getenv("HF_TOKEN", "").strip()
        or os.getenv("HUGGING_FACE_HUB_TOKEN", "").strip()
    )
    if token:
        # sentence-transformers/transformers accept `token`; older stacks may
        # still look at env vars, but passing it explicitly makes startup less brittle.
        kwargs["token"] = token
    return kwargs


def _cache_folder() -> str | None:
    for key in ("HF_HOME", "HUGGINGFACE_HUB_CACHE", "TRANSFORMERS_CACHE"):
        value = os.getenv(key, "").strip()
        if value:
            return value
    return None


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
        model_kwargs = _model_kwargs()
        cache_folder = _cache_folder()

        for model_name in candidates:
            try:
                instance = HuggingFaceEmbeddings(
                    model_name=model_name,
                    model_kwargs=model_kwargs,
                    cache_folder=cache_folder,
                )
                _EMBEDDINGS_INSTANCE = instance
                if model_name != primary_model:
                    logger.warning(
                        "Embedding model fallback active: '%s' -> '%s' (dim=%s)",
                        primary_model,
                        model_name,
                        EMBEDDING_DIM,
                    )
                else:
                    logger.info("Embedding model loaded: %s (dim=%s)", model_name, EMBEDDING_DIM)
                return instance
            except Exception as exc:
                hint = _local_model_hint(model_name)
                errors.append(f"{model_name}: {exc}{hint}")

        # Don't cache the error — allow retry on next call for transient failures.
        raise RuntimeError(
            "Embeddings unavailable. Tried candidates: " + " | ".join(errors)
        )
