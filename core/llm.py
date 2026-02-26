"""
LLM Integration - vLLM/OpenAI-compatible client with monitoring hooks.
"""

from __future__ import annotations

import os
import time
from functools import lru_cache

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from .config import MODEL_BACKENDS, VLLM_BASE_URL as DEFAULT_BASE_URL, VLLM_MODEL as DEFAULT_MODEL
from .database import log_usage
from .monitoring import CACHE_HITS, CACHE_MISSES, ConfigLoader, LLM_LATENCY, TOKEN_USAGE

# Load config
CONFIG = ConfigLoader.load_model_config()
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", CONFIG.get("llm", {}).get("temperature", 0.6)))


def get_llm(model_key: str = None):
    """Get LLM instance (supports OpenAI-compatible providers, vLLM, Groq, etc.)."""
    if model_key and model_key in MODEL_BACKENDS:
        base_url = MODEL_BACKENDS[model_key]["base_url"]
        model_name = MODEL_BACKENDS[model_key]["model"]
        api_key = MODEL_BACKENDS[model_key].get("api_key", os.getenv("VLLM_API_KEY", "not-needed"))
    else:
        base_url = DEFAULT_BASE_URL
        model_name = DEFAULT_MODEL
        api_key = os.getenv("VLLM_API_KEY", "not-needed")

    return ChatOpenAI(
        base_url=base_url,
        api_key=api_key,
        model=model_name,
        temperature=LLM_TEMPERATURE,
        max_tokens=CONFIG.get("llm", {}).get("max_tokens", 2048),
        timeout=180.0,
        max_retries=2,
    )


PROMPT_TEMPLATE = """You are a helpful AI assistant.

Response Rules:
1. Answer naturally in plain text when no media is needed.
2. Use tags only when relevant content is available in context.
3. Never invent filenames, URLs, coordinates, labels, or options.
4. Put each media/control tag on its own line for reliable parsing.

Allowed Tag Formats:
- Image: `[image][filename.jpg]`
- Video: `[video][filename.mp4]`
- Document: `[document][filename.pdf]`
- Link: `[link][url][text]`
- Location: `[location][lat,long][name][address]`
- Buttons: `[buttons][Title][Option1|Option2|Option3]`

When to use tags:
- Use image/video/document tags only if the filename exists under:
  - Available Images
  - Available Videos
  - Available Documents
- Use link tags for external references when a clickable link helps.
- Use location tags only when location details are explicitly available.
- Use buttons tags only when clear short options improve the reply.

Context Usage:
Always check the available context sections before using tags.

Previous conversation:
{conversation_history}

Context:
{context}

Question: {question}

Answer:"""


@lru_cache(maxsize=4)
def get_qa_chain(model_key: str = None):
    """Get QA chain (cached)."""
    llm = get_llm(model_key)
    prompt = ChatPromptTemplate.from_template(PROMPT_TEMPLATE)
    return prompt | llm


def retry_with_backoff(func, retries=2, initial_delay=2.0):
    """Simple retry with exponential backoff."""
    for i in range(retries):
        try:
            return func()
        except Exception as exc:
            if i == retries - 1:
                raise exc
            wait = initial_delay * (2**i)
            print(f"LLM error: {exc}. Retrying in {wait}s... ({i + 1}/{retries})")
            time.sleep(wait)


def invoke_chain(
    question: str,
    context: str,
    conversation_history: str,
    agent_id: str = None,
    agent_name: str = "default",
    verbosity: str = "medium",
    model_key: str = None,
    request_id: str = None,
    session_id: str = None,
    user_id: str = None,
    channel_name: str = "web",
    channel_type: str = "UTILITY",
    question_tokens: int = 0,
    rag_query_tokens: int = 0,
) -> str:
    """Invoke the QA chain with monitoring and analytics logging."""
    start_time = time.time()

    try:
        chain = get_qa_chain(model_key)

        if context:
            CACHE_HITS.labels(agent_id=str(agent_id)).inc()
        else:
            CACHE_MISSES.labels(agent_id=str(agent_id)).inc()

        response_msg = retry_with_backoff(
            lambda: chain.invoke(
                {
                    "question": question,
                    "context": context,
                    "conversation_history": conversation_history,
                }
            ),
            retries=2,
        )

        latency_sec = time.time() - start_time
        LLM_LATENCY.labels(agent_id=str(agent_id), agent_name=agent_name).observe(latency_sec)
        answer = response_msg.content

        try:
            usage = response_msg.response_metadata.get("token_usage", {})
            p_tokens = usage.get("prompt_tokens", 0)
            c_tokens = usage.get("completion_tokens", 0)

            meta_model = response_msg.response_metadata.get("model_name", None)
            if not meta_model:
                if model_key and model_key in MODEL_BACKENDS:
                    meta_model = MODEL_BACKENDS[model_key]["model"]
                else:
                    meta_model = DEFAULT_MODEL

            if p_tokens or c_tokens:
                # Postgres usage log
                log_usage(
                    agent_id,
                    p_tokens,
                    c_tokens,
                    meta_model,
                    latency=latency_sec,
                    question_tokens=question_tokens,
                    rag_query_tokens=rag_query_tokens,
                )

                # ClickHouse usage log
                try:
                    from .clickhouse import log_usage_to_clickhouse

                    cost_est = ((p_tokens / 1_000_000) * 0.50) + ((c_tokens / 1_000_000) * 0.70)
                    log_usage_to_clickhouse(
                        agent_id=str(agent_id) if agent_id else None,
                        model=meta_model,
                        question_tokens=question_tokens,
                        rag_query_tokens=rag_query_tokens,
                        prompt_tokens=p_tokens,
                        completion_tokens=c_tokens,
                        latency_ms=latency_sec * 1000.0,
                        cost=cost_est,
                        request_id=request_id,
                        session_id=session_id,
                        user_id=user_id,
                        channel_name=channel_name,
                        channel_type=channel_type,
                        status="success",
                    )
                except Exception:
                    pass

                TOKEN_USAGE.labels(agent_id=str(agent_id), agent_name=agent_name, token_type="prompt").inc(p_tokens)
                TOKEN_USAGE.labels(agent_id=str(agent_id), agent_name=agent_name, token_type="completion").inc(c_tokens)
        except Exception as exc:
            print(f"Metrics logging failed: {exc}")

        return answer

    except Exception as exc:
        error_msg = str(exc)
        print(f"LLM invocation failed: {error_msg}")
        try:
            from .clickhouse import log_usage_to_clickhouse

            model_name = DEFAULT_MODEL
            if model_key and model_key in MODEL_BACKENDS:
                model_name = MODEL_BACKENDS[model_key]["model"]

            log_usage_to_clickhouse(
                agent_id=str(agent_id) if agent_id else None,
                model=model_name,
                question_tokens=question_tokens,
                rag_query_tokens=rag_query_tokens,
                prompt_tokens=0,
                completion_tokens=0,
                latency_ms=(time.time() - start_time) * 1000.0,
                cost=0.0,
                request_id=request_id,
                session_id=session_id,
                user_id=user_id,
                channel_name=channel_name,
                channel_type=channel_type,
                status="error",
                error=error_msg,
            )
        except Exception:
            pass

        if "Connection" in error_msg or "timeout" in error_msg.lower():
            resolved_model = DEFAULT_MODEL
            resolved_backend = DEFAULT_BASE_URL
            if model_key and model_key in MODEL_BACKENDS:
                resolved_model = MODEL_BACKENDS[model_key]["model"]
                resolved_backend = MODEL_BACKENDS[model_key]["base_url"]
            raise RuntimeError(
                f"Cannot connect to LLM backend. Ensure backend is running at '{resolved_backend}' and model '{resolved_model}' is loaded. Error: {error_msg}"
            )
        if "memory" in error_msg.lower():
            raise RuntimeError(f"Out of memory. Try a smaller model. Error: {error_msg}")
        raise RuntimeError(f"LLM invocation failed: {error_msg}")


def reset_chain():
    """Reset QA chain cache."""
    get_qa_chain.cache_clear()
