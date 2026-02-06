"""
🔧 FIXED INGESTION PIPELINE - Agent-Safe Document Ingestion
Solves NO_DOCUMENTS issue by binding documents to agents explicitly
"""
from typing import List
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_postgres import PGVector
from .embeddings import get_embeddings
from ..config import DATABASE_URL


# ✅ TPM-SAFE CHUNKING CONFIG (validated for llama-3.3-70b-versatile)
CHUNKING_CONFIG = {
    "chunk_size": 700,           # Safe under TPM limits
    "chunk_overlap": 120,        # Preserves context (~17% overlap)
    "max_chunks_per_query": 4    # Limits context window
}


def ingest_agent_document(
    agent_id: str,
    agent_name: str,
    raw_text: str,
    source: str = "pdf"
) -> int:
    """
    ✅ FIXED: Ingest documents with explicit agent binding
    
    Args:
        agent_id: Unique agent identifier
        agent_name: Human-readable agent name
        raw_text: Raw document text
        source: Document source type (pdf, txt, etc.)
    
    Returns:
        Number of chunks created
    
    Why this fixes NO_DOCUMENTS:
    - Every chunk has agent_name in metadata
    - Retriever can filter safely
    - No silent mismatch between ingestion and retrieval
    """
    # Create splitter with TPM-safe config
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNKING_CONFIG["chunk_size"],
        chunk_overlap=CHUNKING_CONFIG["chunk_overlap"],
        separators=["\n\n", "\n", ".", " ", ""]
    )
    
    # Split text into chunks
    chunks = splitter.split_text(raw_text)
    
    # Create documents with agent metadata
    docs = [
        Document(
            page_content=chunk,
            metadata={
                "agent_id": agent_id,
                "agent_name": agent_name,
                "source": source,
                "domain": agent_name.lower().replace(" ", "_"),
                "chunk_index": i
            }
        )
        for i, chunk in enumerate(chunks)
    ]
    
    # Get embeddings and collection name
    embeddings = get_embeddings()
    collection = f"omni_agent_{agent_id}"
    
    # Add to vector store
    PGVector.from_documents(
        documents=docs,
        embedding=embeddings,
        collection_name=collection,
        connection=DATABASE_URL,
        pre_delete_collection=False
    )
    
    print(f"✅ Ingested {len(docs)} chunks for agent '{agent_name}' (ID: {agent_id})")
    print(f"   Chunk size: {CHUNKING_CONFIG['chunk_size']}, Overlap: {CHUNKING_CONFIG['chunk_overlap']}")
    
    return len(docs)


def get_agent_retriever(vectorstore, agent_id: str, agent_name: str, k: int = 4):
    """
    ✅ CRITICAL: Agent-aware retriever with filtering
    
    Args:
        vectorstore: PGVector instance
        agent_id: Agent ID to filter by
        agent_name: Agent name to filter by
        k: Number of documents to retrieve
    
    Returns:
        Retriever that only returns documents for this agent
    
    Why this works:
    - Agents only see their documents
    - No cross-contamination
    - Predictable retrieval
    """
    return vectorstore.as_retriever(
        search_kwargs={
            "k": min(k, CHUNKING_CONFIG["max_chunks_per_query"]),
            "filter": {
                "agent_id": agent_id,
                "agent_name": agent_name
            }
        }
    )


def validate_agent_documents(agent_id: str, agent_name: str) -> dict:
    """
    Validate that agent has documents in vector store
    
    Returns:
        dict with status and count
    """
    try:
        embeddings = get_embeddings()
        collection = f"omni_agent_{agent_id}"
        
        store = PGVector(
            embeddings=embeddings,
            collection_name=collection,
            connection=DATABASE_URL
        )
        
        # Try to retrieve with filter
        retriever = get_agent_retriever(store, agent_id, agent_name, k=1)
        docs = retriever.invoke("test query")  # Use invoke instead of get_relevant_documents
        
        return {
            "status": "OK" if docs else "NO_DOCUMENTS",
            "document_count": len(docs),
            "agent_id": agent_id,
            "agent_name": agent_name
        }
    except Exception as e:
        return {
            "status": "ERROR",
            "error": str(e),
            "agent_id": agent_id,
            "agent_name": agent_name
        }


# ✅ EXAMPLE USAGE
"""
# Ingest documents for an agent
from core.ingestion_fixed import ingest_agent_document

pdf_text = "Your extracted PDF text here..."
chunk_count = ingest_agent_document(
    agent_id="abc-123",
    agent_name="Pizza Store",
    raw_text=pdf_text,
    source="pdf"
)

# Validate ingestion
from core.ingestion_fixed import validate_agent_documents
result = validate_agent_documents("abc-123", "Pizza Store")
print(result)  # Should show status: OK
"""
