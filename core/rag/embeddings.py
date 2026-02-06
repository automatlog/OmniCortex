"""
Embedding model handling with caching
"""
from langchain_huggingface import HuggingFaceEmbeddings
from ..config import EMBEDDING_MODEL
import streamlit as st


@st.cache_resource(show_spinner=False)
def get_embeddings():
    """Get or create embeddings model (cached)"""
    return HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
