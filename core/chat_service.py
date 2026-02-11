"""
Chat Service - Orchestrates the RAG workflow
"""
from typing import List, Dict
from .rag.vector_store import create_vector_store
from .rag.retrieval import hybrid_search
from .llm import invoke_chain
from .cache import check_cache, save_to_cache
from .guardrails import validate_input, validate_output
from .processing.pii import mask_pii
from .database import save_message, save_document_metadata, save_parent_chunk
from .processing.chunking import split_text, parent_child_split
from .processing.document_loader import extract_text_from_files, validate_extraction, get_file_info
from .agent_manager import update_agent_metadata, get_agent
import os
import time

# ... (previous functions similar)

def format_history(messages: List[Dict], max_messages: int = 10) -> str:
    """Format conversation history for prompt with size limit"""
    if not messages:
        return "No previous conversation."
    
    recent = messages[-(max_messages * 2):]
    formatted = []
    total_chars = 0
    max_history_chars = 1000  # Limit history to 1000 chars
    
    for msg in recent:
        role = "User" if msg["role"] == "user" else "Assistant"
        content = msg['content']
        
        # Truncate long messages
        if len(content) > 200:
            content = content[:200] + "..."
        
        line = f"{role}: {content}"
        
        if total_chars + len(line) > max_history_chars:
            break
            
        formatted.append(line)
        total_chars += len(line)
    
    return "\n".join(formatted)


def format_context(docs) -> str:
    """Format retrieved documents into context string with size limit"""
    if not docs:
        return "No relevant documents found."
    
    context_parts = []
    total_chars = 0
    max_context_chars = 2500  # Reduced from 4000 to 2500 for better performance
    
    for i, doc in enumerate(docs, 1):
        if hasattr(doc, 'page_content'):
            content = doc.page_content
        elif isinstance(doc, dict) and "content" in doc:
            content = doc["content"]
        else:
            content = str(doc)
        
        # Truncate very long documents - reduced from 800 to 500
        if len(content) > 500:
            content = content[:500] + "..."
            
        doc_text = f"[Document {i}]: {content}"
        
        # Check if adding this would exceed limit
        if total_chars + len(doc_text) > max_context_chars:
            break
            
        context_parts.append(doc_text)
        total_chars += len(doc_text)
    
    return "\n\n".join(context_parts)


def process_question(question: str, agent_id: str = None, 
                    conversation_history: List[Dict] = None,
                    max_history: int = 5,
                    verbosity: str = "medium",
                    model_selection: str = None) -> str:
    """
    Process user question with RAG and verbosity control
    """
    # 0. Safety Checks
    is_valid, reason = validate_input(question)
    if not is_valid:
        return f"🔒 Request Blocked: {reason}"
        
    # 0.1 PII Masking (for logging/search, but maybe keep original for LLM if context needed? 
    # Usually we mask before sending to external LLM/DB)
    safe_question = mask_pii(question)
    
    # 0.2 Check Cache (use safe_question)
    cached = check_cache(safe_question, agent_id)
    if cached:
        save_message("user", safe_question, agent_id=agent_id)
        save_message("assistant", cached, agent_id=agent_id)
        return cached

    # 1. Hybrid Search (reduced to 2 documents for maximum performance)
    docs = hybrid_search(safe_question, agent_id=agent_id, top_k=2)
    
    # Format inputs
    context = format_context(docs)
    history = format_history(conversation_history or [], max_history)
    
    # Get agent name for metrics
    agent_name = "default"
    if agent_id:
        try:
            agent = get_agent(agent_id)
            if agent:
                agent_name = agent.get("name", "unknown")
        except:
            pass
    
    # Get response from chain
    answer = invoke_chain(question, context, history, agent_id=agent_id, agent_name=agent_name, verbosity=verbosity, model_key=model_selection)
    
    # 2. Output Guardrails
    is_valid_out, out_reason = validate_output(answer)
    if not is_valid_out:
        answer = f"🔒 Response Blocked: {out_reason}"
        # detailed logging here if needed
    
    # Save to Cache (only if valid)
    if is_valid_out:
        save_to_cache(safe_question, answer, agent_id)

    # Save to database (Postgres)
    save_message("user", safe_question, agent_id=agent_id)
    save_message("assistant", answer, agent_id=agent_id)
    
    # Log to ClickHouse (Analytics)
    try:
        from .clickhouse import log_chat_to_clickhouse
        log_chat_to_clickhouse(agent_id, "user", question)
        log_chat_to_clickhouse(agent_id, "assistant", answer)
    except Exception:
        pass
    
    return answer


def save_text_to_file(agent_id: str, filename: str, text: str):
    """Save extracted text to storage/agents/{agent_name}/filename.txt"""
    try:
        agent = get_agent(agent_id)
        if not agent:
            return
            
        agent_name = agent['name'].strip().replace(" ", "_").lower()
        # Create storage directory
        storage_dir = os.path.join("storage", "agents", agent_name)
        os.makedirs(storage_dir, exist_ok=True)
        
        # Save file
        safe_filename = "".join([c for c in filename if c.isalpha() or c.isdigit() or c in (' ', '.', '_')]).rstrip()
        file_path = os.path.join(storage_dir, f"{safe_filename}.txt")
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(text)
            
        print(f"✅ Saved file: {file_path}")
    except Exception as e:
        print(f"⚠️ Failed to save file: {e}")


def process_documents(files=None, text_input: str = None, 
                     agent_id: str = None) -> Dict:
    """
    Process and index documents
    """
    result = {"success": False, "warning": None, "error": None}
    
    raw_text = ""
    processed_files = []
    
    # Process files
    if files:
        # Extract individual files
        extracted_files, skipped = extract_text_from_files(files)
        
        # Validate overall result
        combined_text = "\n\n".join([t for _, t in extracted_files])
        validation = validate_extraction(combined_text, skipped)
        
        if validation["warning"]:
            result["warning"] = validation["warning"]
        
        if validation["error"] and not text_input:
            result["error"] = validation["error"]
            return result
        
        raw_text += combined_text
        
        # Save files and track info
        for filename, text in extracted_files:
            # Save to folder
            if agent_id:
                save_text_to_file(agent_id, filename, text)
            
            # Find file object for size info
            # Find file object for size info
            file_obj = next((f for f in files if getattr(f, "filename", getattr(f, "name", "")) == filename), None)
            if file_obj:
                info = get_file_info(file_obj)
                processed_files.append(info)
    
    # Add text input
    if text_input and text_input.strip():
        raw_text += "\n" + text_input
        if agent_id:
            save_text_to_file(agent_id, "pasted_text.txt", text_input)
    
    if not raw_text.strip():
        result["error"] = "No content to process"
        return result
    
    # Create chunks and vector store using Parent-Child Strategy
    print("🔹 Starting Parent-Child Chunking...")
    pairs = parent_child_split(raw_text)
    
    # Collect unique parents for batch insert
    unique_parents = list(set(parent for _, parent in pairs))
    
    # Batch save all parents at once (single DB round-trip)
    from .database import batch_save_parent_chunks
    parent_id_map = {}
    if agent_id and unique_parents:
        parent_id_map = batch_save_parent_chunks(unique_parents)
    
    # Build chunks with parent_id metadata
    chunks = []
    metadatas = []
    
    for child, parent in pairs:
        chunks.append(child)
        parent_id = parent_id_map.get(parent)
        if parent_id:
            metadatas.append({"parent_id": parent_id})
        else:
            metadatas.append({})

    t0 = time.time()
    create_vector_store(chunks, agent_id=agent_id, metadatas=metadatas)
    t1 = time.time()
    embedding_duration = t1 - t0
    
    # Save document metadata
    if agent_id:
        for info in processed_files:
            preview = raw_text[:500]
            save_document_metadata(
                agent_id=agent_id,
                filename=info["filename"],
                file_type=info["type"],
                file_size=info["size"],
                content_preview=preview,
                chunk_count=len(chunks) // max(len(processed_files), 1),
                embedding_time=embedding_duration
            )
        
        if text_input and text_input.strip():
            save_document_metadata(
                agent_id=agent_id,
                filename="[Pasted Text]",
                file_type="text",
                file_size=len(text_input.encode('utf-8')),
                content_preview=text_input[:500],
                chunk_count=len(chunks) if not files else 0,
                embedding_time=embedding_duration
            )
        
        # Update agent document count
        total = len(processed_files) + (1 if text_input and text_input.strip() else 0)
        update_agent_metadata(agent_id, document_count=total)
    
    result["success"] = True
    return result
