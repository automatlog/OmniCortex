"""
Voice Chat Service — voice-optimized question processing.

Compared to process_question():
  - SKIP validate_input() guardrails  (ASR noise = false positives)
  - KEEP mask_pii()
  - SKIP _rule_based_agent_reply()    (voice model handles greetings)
  - SKIP check_cache() / save_to_cache() (ASR noise = unreliable cache)
  - KEEP hybrid_search() + format_context() (RAG grounding is the point)
  - KEEP invoke_chain()
  - SKIP enforce_canonical_media_tags() + strip media tags
  - SKIP validate_output()            (don't block mid-speech)
  - SKIP media inventory injection    (not speakable)
  - KEEP save_message()
  - ClickHouse: channel_name="VOICE", channel_type="TRANSACTIONAL"
"""
import re
import time
import logging
from typing import Dict, List, Optional

from .agent_manager import get_agent
from .chat_service import format_context, format_history, estimate_tokens
from .llm import invoke_chain
from .processing.pii import mask_pii
from .rag.retrieval import hybrid_search
from .database import save_message

logger = logging.getLogger(__name__)

# Regex to strip media tags that are unspeakable
_MEDIA_TAG_RE = re.compile(
    r"\[(?:IMAGE|VIDEO|DOCUMENT|AUDIO|MEDIA)(?::|\|)(.*?)\]",
    re.IGNORECASE | re.DOTALL,
)


def _strip_media_tags(text: str) -> str:
    """Remove media tags like [IMAGE:...], [VIDEO|...], etc."""
    return _MEDIA_TAG_RE.sub("", text).strip()


def process_question_voice(
    question: str,
    agent_id: str = None,
    conversation_history: List[Dict] = None,
    max_history: int = 5,
    model_selection: str = None,
    request_id: str = None,
    session_id: str = None,
    user_id: str = None,
    transcript_confidence: float = 0.0,
) -> str:
    """
    Process a voice-transcribed question through RAG + LLM.

    Streamlined version of process_question() optimised for the voice
    pipeline: no input/output guardrails, no cache, no media inventory
    injection, and all media tags stripped from the response.
    """
    started_at = time.perf_counter()

    if not question or not question.strip():
        return ""

    safe_question = mask_pii(question)
    query_tokens = estimate_tokens(question)
    rag_query_tokens = estimate_tokens(safe_question)

    # RAG retrieval
    docs = hybrid_search(safe_question, agent_id=agent_id, top_k=2)
    context = format_context(docs)
    history = format_history(conversation_history or [], max_history)

    agent_name = "default"
    if agent_id:
        try:
            agent = get_agent(agent_id)
            if agent:
                agent_name = agent.get("name") or "default"
        except Exception as e:
            logger.warning("Voice agent lookup failed (agent_id=%s): %s", agent_id, e)

    # LLM invocation
    answer = invoke_chain(
        safe_question,
        context,
        history,
        agent_id=agent_id,
        agent_name=agent_name,
        verbosity="medium",
        model_key=model_selection,
        request_id=request_id,
        session_id=session_id,
        user_id=user_id,
        channel_name="VOICE",
        channel_type="TRANSACTIONAL",
        query_tokens=query_tokens,
        rag_query_tokens=rag_query_tokens,
    )

    # Strip media tags (unspeakable)
    answer = _strip_media_tags(answer)

    # Persist to conversation history
    save_message("user", safe_question, agent_id=agent_id)
    save_message("assistant", answer, agent_id=agent_id)

    # ClickHouse chat log
    safe_agent_id = str(agent_id).strip() if agent_id is not None else None
    safe_session_id = str(session_id).strip()[:128] if session_id else None
    safe_user_id = str(user_id).strip()[:128] if user_id else None
    try:
        from .clickhouse import log_chat_to_clickhouse

        log_chat_to_clickhouse(
            agent_id=safe_agent_id,
            user_message=safe_question,
            assistant_message=answer,
            request_id=request_id,
            session_id=safe_session_id,
            user_id=safe_user_id,
            status="success",
        )
    except Exception as e:
        logger.warning("Voice ClickHouse logging failed: %s", e)

    latency_ms = (time.perf_counter() - started_at) * 1000.0
    logger.info(
        "Voice Q&A completed in %.0f ms (agent=%s, confidence=%.2f)",
        latency_ms,
        agent_id,
        transcript_confidence,
    )

    return answer
