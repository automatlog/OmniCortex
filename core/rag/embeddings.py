"""
Embedding model handling with caching
"""
import os
from functools import lru_cache
from langchain_huggingface import HuggingFaceEmbeddings
from ..config import EMBEDDING_MODEL


@lru_cache(maxsize=1)
def get_embeddings():
    """Get or create embeddings model (cached)"""
    # If fast-transfer is enabled but package is missing, force fallback to regular download.
    if os.getenv("HF_HUB_ENABLE_HF_TRANSFER", "").strip() == "1":
        try:
            import hf_transfer  # noqa: F401
        except Exception:
            os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"
    return HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
