"""
Vector Store Operations with pgvector
"""
from typing import List
from langchain_postgres import PGVector
from .embeddings import get_embeddings
from ..config import DATABASE_URL


def get_collection_name(agent_id: str = None) -> str:
    """Get collection name for agent"""
    if agent_id:
        return f"omni_agent_{agent_id}"
    return "omni_default"


def create_vector_store(text_chunks: List[str], agent_id: str = None, metadatas: List[dict] = None):
    """Create vector store from text chunks"""
    embeddings = get_embeddings()
    collection = get_collection_name(agent_id)
    
    PGVector.from_texts(
        texts=text_chunks,
        embedding=embeddings,
        collection_name=collection,
        connection=DATABASE_URL,
        metadatas=metadatas,
        pre_delete_collection=False
    )
    
    print(f"✅ Vector store created: {collection} ({len(text_chunks)} chunks)")


def load_vector_store(agent_id: str = None):
    """Load existing vector store"""
    embeddings = get_embeddings()
    collection = get_collection_name(agent_id)
    
    try:
        store = PGVector(
            embeddings=embeddings,
            collection_name=collection,
            connection=DATABASE_URL
        )
        # Test if it has data
        store.similarity_search("test", k=1)
        return store
    except Exception as e:
        raise FileNotFoundError(
            f"Vector store not found for agent. Upload documents first."
        )


def search_documents(query: str, agent_id: str = None, k: int = 4) -> List:
    """Search for similar documents"""
    store = load_vector_store(agent_id)
    return store.similarity_search(query, k=k)


def delete_vector_store(agent_id: str) -> bool:
    """Delete vector store for an agent"""
    try:
        embeddings = get_embeddings()
        collection = get_collection_name(agent_id)
        store = PGVector(
            embeddings=embeddings,
            collection_name=collection,
            connection=DATABASE_URL
        )
        store.delete_collection()
        print(f"✅ Deleted vector store: {collection}")
        return True
    except Exception as e:
        print(f"⚠️ Delete failed: {e}")
        return False


def get_vector_count(agent_id: str = None) -> int:
    """Get number of vectors in store"""
    try:
        from sqlalchemy import text, create_engine
        collection = get_collection_name(agent_id)
        engine = create_engine(DATABASE_URL)
        
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT COUNT(*) FROM langchain_pg_embedding WHERE collection_name = :c"),
                {"c": collection}
            )
            return result.scalar() or 0
    except:
        return 0
