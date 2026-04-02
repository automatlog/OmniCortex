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

VLLM2_BASE_URL = _first_non_empty("VLLM2_BASE_URL", default="http://localhost:8082/v1")
VLLM2_MODEL = _first_non_empty(
    "VLLM2_MODEL",
    default="Qwen/Qwen2.5-7B-Instruct",
)
VLLM2_API_KEY = _first_non_empty("VLLM2_API_KEY", "VLLM1_API_KEY", default="not-needed")

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
    "Qwen 2.5 7B": {
        "base_url": VLLM2_BASE_URL,
        "model": VLLM2_MODEL,
        "api_key": VLLM2_API_KEY,
    },
}

# Default LLM backend for voice reasoning (LFM/cascade/personaplex modes)
# Defaults to vLLM1 alias to keep voice reasoning on the primary backend.
VOICE_LLM_BACKEND = os.getenv("VOICE_LLM_BACKEND", "Meta Llama 3.1")

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
LFM_SERVER_URL = os.getenv("LFM_SERVER_URL", "").strip()  # e.g. http://localhost:8099

# =============================================================================
# VOICE PIPELINE (Multi-Mode)
# =============================================================================
VOICE_DEFAULT_MODE = os.getenv("VOICE_DEFAULT_MODE", "personaplex")
VOICE_ASR_MODEL = os.getenv("VOICE_ASR_MODEL", "base.en")
VOICE_ASR_DEVICE = os.getenv("VOICE_ASR_DEVICE", "cuda")
VOICE_VOCODER_DEVICE = os.getenv("VOICE_VOCODER_DEVICE", "cuda")
VOICE_DRIP_FEED_CHARS = int(os.getenv("VOICE_DRIP_FEED_CHARS", "20"))
VOICE_DRIP_FEED_INTERVAL_MS = int(os.getenv("VOICE_DRIP_FEED_INTERVAL_MS", "80"))
VOICE_VAD_SILENCE_MS = int(os.getenv("VOICE_VAD_SILENCE_MS", "600"))
VOICE_VAD_ENERGY_THRESHOLD = float(os.getenv("VOICE_VAD_ENERGY_THRESHOLD", "0.01"))
VOICE_REASONER_QUEUE_SIZE = int(os.getenv("VOICE_REASONER_QUEUE_SIZE", "200"))
VOICE_PERSONAPLEX_FALLBACK = os.getenv("VOICE_PERSONAPLEX_FALLBACK", "true").lower() == "true"
VOICE_POST_SILENCE_DELAY_MS = int(os.getenv("VOICE_POST_SILENCE_DELAY_MS", "500"))
VOICE_BACKCHANNEL_PAUSE_MS = int(os.getenv("VOICE_BACKCHANNEL_PAUSE_MS", "300"))
VOICE_BACKCHANNEL_COOLDOWN_S = float(os.getenv("VOICE_BACKCHANNEL_COOLDOWN_S", "4.0"))
VOICE_BACKCHANNEL_MIN_SPEECH_S = float(os.getenv("VOICE_BACKCHANNEL_MIN_SPEECH_S", "2.0"))

# =============================================================================
# MULTI-AGENT ROUTING
# =============================================================================
VOICE_MAX_TRANSFERS_PER_SESSION = int(os.getenv("VOICE_MAX_TRANSFERS_PER_SESSION", "3"))
VOICE_TRANSFER_COOLDOWN_S = float(os.getenv("VOICE_TRANSFER_COOLDOWN_S", "30"))
VOICE_SENTIMENT_ANGRY_THRESHOLD = float(os.getenv("VOICE_SENTIMENT_ANGRY_THRESHOLD", "0.7"))

# =============================================================================
# PERSONAPLEX / RUNPOD CONNECTION
# =============================================================================
PERSONAPLEX_API_KEY = os.getenv("PERSONAPLEX_API_KEY", "").strip()
PERSONAPLEX_AUTH_HEADER = os.getenv("PERSONAPLEX_AUTH_HEADER", "x-api-key").strip()
PERSONAPLEX_SSL_VERIFY = os.getenv("PERSONAPLEX_SSL_VERIFY", "true").strip().lower() == "true"
PERSONAPLEX_CONNECT_TIMEOUT = float(os.getenv("PERSONAPLEX_CONNECT_TIMEOUT", "15"))
PERSONAPLEX_RECONNECT_ATTEMPTS = int(os.getenv("PERSONAPLEX_RECONNECT_ATTEMPTS", "3"))
PERSONAPLEX_RECONNECT_DELAY = float(os.getenv("PERSONAPLEX_RECONNECT_DELAY", "2"))
PERSONAPLEX_HEARTBEAT = float(os.getenv("PERSONAPLEX_HEARTBEAT", "20"))
