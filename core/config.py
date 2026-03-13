"""
OmniCortex Configuration - Simplified
"""
import os
from dotenv import load_dotenv

load_dotenv()


def _first_non_empty(*keys: str, default: str = "") -> str:
    """Return the first non-empty environment value across candidate keys."""
    for key in keys:
        value = os.getenv(key)
        if value is not None and str(value).strip() != "":
            return value
    return default

# =============================================================================
# DATABASE
# =============================================================================
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL not found in .env")

# =============================================================================
# LLM INFERENCE (Hybrid vLLM)
# =============================================================================
# Hybrid Model Configuration (primary + secondary vLLM backends)
VLLM1_BASE_URL = _first_non_empty("VLLM1_BASE_URL", "VLLM_BASE_URL", default="http://localhost:8080/v1")
VLLM1_MODEL = _first_non_empty(
    "VLLM1_MODEL",
    "VLLM_MODEL",
    default="meta-llama/Llama-3.1-8B-Instruct",
)
VLLM1_API_KEY = _first_non_empty("VLLM1_API_KEY", "VLLM_API_KEY", default="not-needed")

VLLM2_BASE_URL = _first_non_empty("VLLM2_BASE_URL", "LLAMA_BASE_URL", default="http://localhost:8081/v1")
VLLM2_MODEL = _first_non_empty(
    "VLLM2_MODEL",
    "LLAMA_MODEL",
    default="meta-llama/Llama-4-Maverick-17B-128E-Instruct",
)
VLLM2_API_KEY = _first_non_empty("VLLM2_API_KEY", "LLAMA_API_KEY", "VLLM1_API_KEY", default="not-needed")

MODEL_BACKENDS = {
    "default": {
        "base_url": VLLM1_BASE_URL,
        "model": VLLM1_MODEL,
        "api_key": VLLM1_API_KEY,
    },
    "Meta Llama 3.1": {
        "base_url": VLLM1_BASE_URL,
        "model": VLLM1_MODEL,
        "api_key": VLLM1_API_KEY,
    },
    "Llama 4 Maverick": {
        "base_url": VLLM2_BASE_URL,
        "model": VLLM2_MODEL,
        "api_key": VLLM2_API_KEY,
    },
}

# Voice Model (Moshi/PersonaPlex — runs locally)
PERSONAPLEX_MODEL = os.getenv("PERSONAPLEX_MODEL", "nvidia/personaplex-7b-v1")
PERSONAPLEX_URL = os.getenv("PERSONAPLEX_URL", "http://localhost:8998")

# Defaults (from primary backend)
VLLM_BASE_URL = VLLM1_BASE_URL  # backward-compatible alias
VLLM_MODEL = VLLM1_MODEL  # backward-compatible alias
VLLM_API_KEY = VLLM1_API_KEY  # backward-compatible alias
LLAMA_BASE_URL = VLLM2_BASE_URL  # backward-compatible alias
LLAMA_MODEL = VLLM2_MODEL  # backward-compatible alias
LLAMA_API_KEY = VLLM2_API_KEY  # backward-compatible alias
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.6"))

# =============================================================================
# RAG SETTINGS
# =============================================================================
# Embeddings
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-large-en-v1.5")

def _infer_embedding_dim(model_name: str) -> int:
    name = (model_name or "").lower()
    if "bge-large-en-v1.5" in name:
        return 1024
    if "bge-base" in name:
        return 768
    if "bge-small" in name or "all-minilm-l6-v2" in name:
        return 384
    return 1024

EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", str(_infer_embedding_dim(EMBEDDING_MODEL))))

# Chunking
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "700"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "120"))
USE_SEMANTIC_CHUNKING = os.getenv("USE_SEMANTIC_CHUNKING", "true").lower() == "true"

# Retrieval
TOP_K_RESULTS = int(os.getenv("TOP_K_RESULTS", "4"))

# =============================================================================
# MEMORY
# =============================================================================
DEFAULT_MAX_HISTORY = int(os.getenv("DEFAULT_MAX_HISTORY", "5"))
MAX_HISTORY_LIMIT = int(os.getenv("MAX_HISTORY_LIMIT", "20"))

# =============================================================================
# STORAGE
# =============================================================================
STORAGE_PATH = os.getenv("STORAGE_PATH", "storage")

# =============================================================================
# WHATSAPP
# =============================================================================
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")
WHATSAPP_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v24.0")
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "omnicortex_token")

# =============================================================================
# MODEL ALIASES
# =============================================================================
LLM_MODEL = VLLM_MODEL  # Alias for backward compatibility
# =============================================================================
# VOICE ENGINE (Moshi/PersonaPlex Only)
# =============================================================================
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "moshi")  # Only moshi supported
MOSHI_ENABLED = os.getenv("MOSHI_ENABLED", "true").lower() == "true"

# =============================================================================
# VOICE ENGINE (LiquidAI)
# =============================================================================
VOICE_MODEL = os.getenv("VOICE_MODEL", "LiquidAI/LFM2.5-Audio-1.5B")
VOICE_MAX_INSTANCES = int(os.getenv("VOICE_MAX_INSTANCES", "8"))
