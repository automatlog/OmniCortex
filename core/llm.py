"""
LLM Integration - vLLM with Adaptive Retry & Prometheus Monitoring
"""
import time
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from .monitoring import ConfigLoader, TOKEN_USAGE, LLM_LATENCY, CACHE_HITS, CACHE_MISSES

# Load config
CONFIG = ConfigLoader.load_model_config()

# Import MODEL_BACKENDS
from .config import MODEL_BACKENDS, VLLM_BASE_URL as DEFAULT_BASE_URL, VLLM_MODEL as DEFAULT_MODEL

# Fallback to defaults if config fails
import os
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", CONFIG.get("llm", {}).get("temperature", 0.6)))


def get_llm(model_key: str = None):
    """Get LLM instance (supports Groq, vLLM, Ollama, etc.)"""
    # Determine config based on key
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
        timeout=180.0,  # Increase timeout to 180 seconds (3 minutes) for Ollama
        max_retries=2   # Keep retries at 2 for faster failure detection
    )


PROMPT_TEMPLATE = """You are a helpful assistant.

Previous conversation: 
{conversation_history}

Context:
{context}

Question: {question}

Answer:"""


from functools import lru_cache
from .database import log_usage


@lru_cache(maxsize=4)
def get_qa_chain(model_key: str = None):
    """Get QA chain (cached)"""
    llm = get_llm(model_key)
    prompt = ChatPromptTemplate.from_template(PROMPT_TEMPLATE)
    chain = prompt | llm
    return chain


def retry_with_backoff(func, retries=2, initial_delay=2.0):
    """Simple retry with exponential backoff - reduced retries for faster failure"""
    import time
    for i in range(retries):
        try:
            return func()
        except Exception as e:
            if i == retries - 1:  # Last attempt
                raise e
            
            # Exponential backoff: 2s, 4s
            wait = initial_delay * (2 ** i)
            print(f"⚠️ LLM Error: {e}. Retrying in {wait}s... ({i+1}/{retries})")
            time.sleep(wait)


def invoke_chain(question: str, context: str, conversation_history: str, agent_id: str = None, agent_name: str = "default", verbosity: str = "medium", model_key: str = None) -> str:
    """Invoke the QA chain with monitoring"""
    start_time = time.time()
    
    try:
        chain = get_qa_chain(model_key)
        
        # Track cache hits vs misses
        if context:
            CACHE_HITS.labels(agent_id=str(agent_id)).inc()
        else:
            CACHE_MISSES.labels(agent_id=str(agent_id)).inc()

        # Execute with retry (reduced to 2 retries)
        response_msg = retry_with_backoff(
            lambda: chain.invoke({
                "question": question,
                "context": context,
                "conversation_history": conversation_history
            }),
            retries=2
        )
        
        latency = time.time() - start_time
        LLM_LATENCY.labels(agent_id=str(agent_id), agent_name=agent_name).observe(latency)
        
        answer = response_msg.content
        
        # Log usage & Metrics
        try:
            usage = response_msg.response_metadata.get('token_usage', {})
            p_tokens = usage.get('prompt_tokens', 0)
            c_tokens = usage.get('completion_tokens', 0)
            
            # Use model from metadata or fallback to key/default
            meta_model = response_msg.response_metadata.get('model_name', None)
            if not meta_model:
                 if model_key and model_key in MODEL_BACKENDS:
                     meta_model = MODEL_BACKENDS[model_key]["model"]
                 else:
                     meta_model = DEFAULT_MODEL
            
            if p_tokens or c_tokens:
                # DB Log (Postgres)
                log_usage(agent_id, p_tokens, c_tokens, meta_model, latency=latency)

                # ClickHouse Log (Analytics)
                try:
                    from .clickhouse import log_usage_to_clickhouse
                    cost_est = ((p_tokens / 1_000_000) * 0.50) + ((c_tokens / 1_000_000) * 0.70)
                    log_usage_to_clickhouse(
                        agent_id=str(agent_id), 
                        model=meta_model, 
                        prompt_tokens=p_tokens, 
                        completion_tokens=c_tokens, 
                        latency=latency,
                        cost=cost_est
                    )
                except Exception:
                    pass
                
                # Prometheus Metrics
                TOKEN_USAGE.labels(agent_id=str(agent_id), agent_name=agent_name, token_type="prompt").inc(p_tokens)
                TOKEN_USAGE.labels(agent_id=str(agent_id), agent_name=agent_name, token_type="completion").inc(c_tokens)
        except Exception as e:
            print(f"⚠️ Metrics logging failed: {e}")
        
        return answer
        
    except Exception as e:
        error_msg = str(e)
        print(f"❌ LLM invocation failed: {error_msg}")
        
        # Provide helpful error messages
        if "Connection" in error_msg or "timeout" in error_msg.lower():
            raise RuntimeError(f"Cannot connect to Ollama. Please ensure Ollama is running on port 11434 and the model 'llama3.2:3b' is loaded. Error: {error_msg}")
        elif "memory" in error_msg.lower():
            raise RuntimeError(f"Out of memory. Try freeing up RAM or using a smaller model. Error: {error_msg}")
        else:
            raise RuntimeError(f"LLM invocation failed: {error_msg}")


def reset_chain():
    """Reset the chain cache"""
    get_qa_chain.cache_clear()
