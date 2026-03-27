"""
Monitoring and Configuration Loader
Handles Prometheus metrics and YAML configuration loading.
"""
import os
import time
import yaml
import logging.config
from typing import Dict, Any
from prometheus_client import Counter, Histogram, Gauge

# =============================================================================
# PROMETHEUS METRICS
# =============================================================================

# Counters
REQUEST_COUNT = Counter(
    'omnicortex_requests_total',
    'Total number of requests',
    ['method', 'endpoint', 'status']
)

CHAT_REQUESTS = Counter(
    'omnicortex_chat_requests_total',
    'Total chat requests',
    ['agent_id']
)

TOKEN_USAGE = Counter(
    'omnicortex_agent_tokens_total',
    'Total tokens used per agent',
    ['agent_id', 'agent_name', 'token_type']  # token_type: prompt, completion
)

RAG_CONTEXT_HIT = Counter(
    'omnicortex_rag_context_hits_total',
    'LLM invocations where RAG context was available',
    ['agent_id']
)

RAG_CONTEXT_MISS = Counter(
    'omnicortex_rag_context_misses_total',
    'LLM invocations where no RAG context was available',
    ['agent_id']
)

# Deprecated compatibility counters for existing dashboards/alerts.
RAG_CACHE_HITS_DEPRECATED = Counter(
    'omnicortex_rag_cache_hits_total',
    'DEPRECATED: use omnicortex_rag_context_hits_total',
    ['agent_id']
)

RAG_CACHE_MISSES_DEPRECATED = Counter(
    'omnicortex_rag_cache_misses_total',
    'DEPRECATED: use omnicortex_rag_context_misses_total',
    ['agent_id']
)

# Latency
REQUEST_LATENCY = Histogram(
    'omnicortex_request_latency_seconds',
    'Request latency in seconds',
    ['method', 'endpoint']
)

LLM_LATENCY = Histogram(
    'omnicortex_agent_latency_seconds',
    'LLM response latency per agent',
    ['agent_id', 'agent_name'],
    buckets=[0.5, 1, 2, 5, 10, 30]
)

# System
ACTIVE_AGENTS = Gauge(
    'omnicortex_active_agents_total',
    'Number of active agents'
)


class PrometheusMiddleware:
    """Simple middleware to time requests"""
    @staticmethod
    def time_request(method: str, endpoint: str):
        return REQUEST_LATENCY.labels(method=method, endpoint=endpoint).time()


# =============================================================================
# CONFIG LOADER
# =============================================================================

class ConfigLoader:
    _model_config = None
    _logging_configured = False

    @staticmethod
    def load_model_config() -> Dict[str, Any]:
        if ConfigLoader._model_config is not None:
            return ConfigLoader._model_config
        
        path = os.path.join(os.path.dirname(__file__), "..", "config", "model_config.yaml")
        try:
            with open(path, "r") as f:
                ConfigLoader._model_config = yaml.safe_load(f)
            return ConfigLoader._model_config
        except Exception as e:
            print(f"⚠️ Failed to load model_config.yaml: {e}")
            return {}

    @staticmethod
    def setup_logging():
        if ConfigLoader._logging_configured:
            return
        
        path = os.path.join(os.path.dirname(__file__), "..", "config", "logging_config.yaml")
        try:
            with open(path, "r") as f:
                config = yaml.safe_load(f)
                logging.config.dictConfig(config)
                ConfigLoader._logging_configured = True
                logging.info("Logging configured from YAML")
        except Exception as e:
            print(f"⚠️ Failed to load logging_config.yaml: {e}")

# Initialize logging on import
ConfigLoader.setup_logging()
