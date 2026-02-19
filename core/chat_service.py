"""
Chat Service - Orchestrates the RAG workflow
"""
import os
import time
from typing import Dict, List, Optional
from urllib.parse import unquote

from .agent_manager import get_agent, update_agent_metadata
from .cache import check_cache, save_to_cache
from .guardrails import validate_input, validate_output
from .llm import invoke_chain
from .processing.chunking import parent_child_split
from .processing.document_loader import extract_text_from_files, get_file_info, validate_extraction
from .processing.pii import mask_pii
from .rag.retrieval import hybrid_search
from .rag.vector_store import create_vector_store
from .database import Document, SessionLocal, save_message


def format_history(messages: List[Dict], max_messages: int = 10) -> str:
    """Format conversation history for prompt with size limit."""
    if not messages:
        return "No previous conversation."

    recent = messages[-(max_messages * 2) :]
    formatted: List[str] = []
    total_chars = 0
    max_history_chars = 1000

    for msg in recent:
        role = "User" if msg["role"] == "user" else "Assistant"
        content = msg["content"]
        if len(content) > 200:
            content = content[:200] + "..."

        line = f"{role}: {content}"
        if total_chars + len(line) > max_history_chars:
            break
        formatted.append(line)
        total_chars += len(line)

    return "\n".join(formatted)


def format_context(docs) -> str:
    """Format retrieved documents into context string with size limit."""
    if not docs:
        return "No relevant documents found."

    context_parts: List[str] = []
    total_chars = 0
    max_context_chars = 2500

    for i, doc in enumerate(docs, 1):
        if hasattr(doc, "page_content"):
            content = doc.page_content
        elif isinstance(doc, dict) and "content" in doc:
            content = doc["content"]
        else:
            content = str(doc)

        if len(content) > 500:
            content = content[:500] + "..."

        doc_text = f"[Document {i}]: {content}"
        if total_chars + len(doc_text) > max_context_chars:
            break

        context_parts.append(doc_text)
        total_chars += len(doc_text)

    return "\n\n".join(context_parts)


def process_question(
    question: str,
    agent_id: str = None,
    conversation_history: List[Dict] = None,
    max_history: int = 5,
    verbosity: str = "medium",
    model_selection: str = None,
    rerank: Optional[bool] = None,
) -> str:
    """Process user question with RAG and guardrails."""
    is_valid, reason = validate_input(question)
    if not is_valid:
        return f"Request Blocked: {reason}"

    safe_question = mask_pii(question)
    cached = check_cache(safe_question, agent_id)
    if cached:
        save_message("user", safe_question, agent_id=agent_id)
        save_message("assistant", cached, agent_id=agent_id)
        return cached

    docs = hybrid_search(safe_question, agent_id=agent_id, top_k=2, rerank=rerank)
    context = format_context(docs)
    history = format_history(conversation_history or [], max_history)

    agent_name = "default"
    if agent_id:
        try:
            agent = get_agent(agent_id)
            if agent:
                agent_name = agent.get("name", "unknown")
                
                # Inject Available Media
                media_sections = []
                
                # 1. Images
                image_urls = agent.get("image_urls") or []
                if image_urls:
                    image_lines = []
                    for u in image_urls:
                        fname = unquote(str(u).rstrip("/").rsplit("/", 1)[-1].split("?", 1)[0]).strip()
                        image_lines.append(f"- {fname} => {u}")
                    media_sections.append(
                        "Available Images (use exact filename in [image][...]):\n" + "\n".join(image_lines)
                    )
                
                # 2. Videos
                video_urls = agent.get("video_urls") or []
                if video_urls:
                    video_lines = []
                    for u in video_urls:
                        fname = unquote(str(u).rstrip("/").rsplit("/", 1)[-1].split("?", 1)[0]).strip()
                        video_lines.append(f"- {fname} => {u}")
                    media_sections.append(
                        "Available Videos (use exact filename in [video][...]):\n" + "\n".join(video_lines)
                    )
                
                # 3. Documents (Filenames)
                try:
                    from .database import get_agent_document_names
                    # Simple fetch, optimize if too many docs
                    # We might need to cache this or limit it
                    doc_names = get_agent_document_names(agent_id, limit=50)
                    if doc_names:
                        media_sections.append("Available Documents:\n" + "\n".join(doc_names))
                except Exception as e:
                    print(f"⚠️ Failed to inject docs into context: {e}")

                if media_sections:
                    context += "\n\n" + "\n\n".join(media_sections)

        except Exception:
            pass


    answer = invoke_chain(
        question,
        context,
        history,
        agent_id=agent_id,
        agent_name=agent_name,
        verbosity=verbosity,
        model_key=model_selection,
    )

    is_valid_out, out_reason = validate_output(answer)
    if not is_valid_out:
        answer = f"Response Blocked: {out_reason}"
    else:
        save_to_cache(safe_question, answer, agent_id)

    save_message("user", safe_question, agent_id=agent_id)
    save_message("assistant", answer, agent_id=agent_id)

    try:
        from .clickhouse import log_chat_to_clickhouse

        log_chat_to_clickhouse(agent_id, "user", question)
        log_chat_to_clickhouse(agent_id, "assistant", answer)
    except Exception:
        pass

    return answer


def save_text_to_file(agent_id: str, filename: str, text: str):
    """Save extracted text to storage/agents/{agent_name}/{filename}.txt."""
    try:
        agent = get_agent(agent_id)
        if not agent:
            return

        agent_name = agent["name"].strip().replace(" ", "_").lower()
        storage_dir = os.path.join("storage", "agents", agent_name)
        os.makedirs(storage_dir, exist_ok=True)

        safe_filename = "".join(
            [c for c in filename if c.isalpha() or c.isdigit() or c in (" ", ".", "_")]
        ).rstrip()
        file_path = os.path.join(storage_dir, f"{safe_filename}.txt")

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception as e:
        print(f"[WARN] Failed to save file: {e}")


def process_documents(files=None, text_input: str = None, agent_id: str = None) -> Dict:
    """Process and index documents, updating omni_documents.status transitions."""
    result = {"success": False, "warning": None, "error": None}
    raw_text = ""
    processed_files: List[Dict] = []

    if files:
        extracted_files, skipped = extract_text_from_files(files)
        combined_text = "\n\n".join([t for _, t in extracted_files])
        validation = validate_extraction(combined_text, skipped)

        if validation["warning"]:
            result["warning"] = validation["warning"]
        if validation["error"] and not text_input:
            result["error"] = validation["error"]
            return result

        raw_text += combined_text

        for filename, text in extracted_files:
            if agent_id:
                save_text_to_file(agent_id, filename, text)
            file_obj = next(
                (f for f in files if getattr(f, "filename", getattr(f, "name", "")) == filename),
                None,
            )
            if file_obj:
                processed_files.append(get_file_info(file_obj))

    if text_input and text_input.strip():
        raw_text += "\n" + text_input
        if agent_id:
            save_text_to_file(agent_id, "pasted_text.txt", text_input)

    if not raw_text.strip():
        result["error"] = "No content to process"
        return result

    pairs = parent_child_split(raw_text)
    unique_parents = list(set(parent for _, parent in pairs))
    from .database import batch_save_parent_chunks

    parent_id_map = {}
    if agent_id and unique_parents:
        parent_id_map = batch_save_parent_chunks(unique_parents)

    chunks = []
    metadatas = []
    for child, parent in pairs:
        chunks.append(child)
        parent_id = parent_id_map.get(parent)
        metadatas.append({"parent_id": parent_id} if parent_id else {})

    doc_ids: List[int] = []
    if agent_id:
        db = SessionLocal()
        try:
            for info in processed_files:
                doc = Document(
                    agent_id=agent_id,
                    filename=info["filename"],
                    file_type=info["type"],
                    file_size=info["size"],
                    content_preview=raw_text[:500],
                    chunk_count=0,
                    extra_data=info.get("metadata", {}),
                    status="indexing",
                )
                db.add(doc)
                db.commit()
                db.refresh(doc)
                doc_ids.append(doc.id)

            if text_input and text_input.strip():
                doc = Document(
                    agent_id=agent_id,
                    filename="[Pasted Text]",
                    file_type="text",
                    file_size=len(text_input.encode("utf-8")),
                    content_preview=text_input[:500],
                    chunk_count=0,
                    status="indexing",
                )
                db.add(doc)
                db.commit()
                db.refresh(doc)
                doc_ids.append(doc.id)
        except Exception as e:
            print(f"[WARN] Failed to pre-create document rows: {e}")
        finally:
            db.close()

    t0 = time.time()
    status = "ready"
    try:
        create_vector_store(chunks, agent_id=agent_id, metadatas=metadatas)
    except Exception as e:
        status = "error"
        result["error"] = str(e)
        print(f"[ERROR] Vector store ingestion failed: {e}")
    embedding_duration = time.time() - t0

    if agent_id and doc_ids:
        db = SessionLocal()
        try:
            for doc_id in doc_ids:
                doc = db.query(Document).filter(Document.id == doc_id).first()
                if not doc:
                    continue
                doc.status = status
                doc.embedding_time = embedding_duration
                doc.chunk_count = len(chunks) // max(len(doc_ids), 1)
            db.commit()
        finally:
            db.close()

        if status == "ready":
            update_agent_metadata(agent_id, document_count=len(doc_ids))

    result["success"] = status == "ready"
    return result
