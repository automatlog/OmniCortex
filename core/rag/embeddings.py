"""
Embedding model handling with caching
"""
from functools import lru_cache
from langchain_huggingface import HuggingFaceEmbeddings
from ..config import EMBEDDING_MODEL


@lru_cache(maxsize=1)
def get_embeddings():
    """Get or create embeddings model (cached)"""
    return HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
