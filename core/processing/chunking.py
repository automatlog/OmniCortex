"""
Advanced Chunking Strategies
- Semantic chunking (embedding-based)
- Character chunking with overlap (fallback)
"""
from typing import List
from langchain_text_splitters import RecursiveCharacterTextSplitter
from ..config import CHUNK_SIZE, CHUNK_OVERLAP, USE_SEMANTIC_CHUNKING


def semantic_chunk(text: str, embeddings=None) -> List[str]:
    """
    Semantic chunking - splits at natural semantic boundaries
    Uses embeddings to detect topic changes
    """
    try:
        from langchain_experimental.text_splitter import SemanticChunker
        
        if embeddings is None:
            from ..rag.embeddings import get_embeddings
            embeddings = get_embeddings()
        
        splitter = SemanticChunker(
            embeddings,
            breakpoint_threshold_type="percentile",
            breakpoint_threshold_amount=95  # Higher = fewer splits
        )
        chunks = splitter.split_text(text)
        print(f"✅ Semantic chunking: {len(chunks)} chunks")
        return chunks
    except Exception as e:
        print(f"⚠️ Semantic chunking failed, using fallback: {e}")
        return character_chunk(text)


def character_chunk(text: str) -> List[str]:
    """
    Character-based chunking with 20% overlap (fallback)
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""]
    )
    chunks = splitter.split_text(text)
    print(f"✅ Character chunking: {len(chunks)} chunks ({CHUNK_OVERLAP/CHUNK_SIZE*100:.0f}% overlap)")
    return chunks


def split_text(text: str, use_semantic: bool = None) -> List[str]:
    """
    Smart text splitting - uses semantic if enabled, else character-based
    
    Args:
        text: Text to split
        use_semantic: Override config setting
    
    Returns:
        List of text chunks
    """
    if use_semantic is None:
        use_semantic = USE_SEMANTIC_CHUNKING
    
    if use_semantic:
        return semantic_chunk(text)
    else:
        return character_chunk(text)


def parent_child_split(text: str, parent_size=2000, child_size=400) -> List[tuple]:
    """
    Split text into Parent (large) and Child (small) chunks.
    Returns: List of (child_content, parent_content)
    """
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    # 1. Split into Parents
    parent_splitter = RecursiveCharacterTextSplitter(
        chunk_size=parent_size,
        chunk_overlap=int(parent_size * 0.1)
    )
    parent_chunks = parent_splitter.split_text(text)
    
    results = []
    
    # 2. Split each Parent into Children
    child_splitter = RecursiveCharacterTextSplitter(
        chunk_size=child_size,
        chunk_overlap=int(child_size * 0.2)
    )
    
    for parent in parent_chunks:
        children = child_splitter.split_text(parent)
        for child in children:
            results.append((child, parent))
            
    print(f"✅ Parent-Child split: {len(parent_chunks)} parents -> {len(results)} children")
    return results

