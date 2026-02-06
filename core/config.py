"""
OmniCortex Configuration - Simplified
"""
import os
from dotenv import load_dotenv

load_dotenv()

# =============================================================================
# DATABASE
# =============================================================================
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL not found in .env")

# =============================================================================
# LLM INFERENCE (Hybrid vLLM)
# =============================================================================
# Hybrid Model Configuration
MODEL_BACKENDS = {
    "Meta Llama 3.1": {
        "base_url": os.getenv("VLLM_BASE_URL", "http://localhost:8080/v1"),
        "model": os.getenv("VLLM_MODEL", "meta-llama/Meta-Llama-3.1-8B-Instruct"),
    },
    "Nemotron": {
        "base_url": os.getenv("NEMOTRON_BASE_URL", "http://localhost:8081/v1"),
        "model": os.getenv("NEMOTRON_MODEL", "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4"),
    }
}

# Voice Model (PersonaPlex for persona-based voice interactions)
PERSONAPLEX_MODEL = os.getenv("PERSONAPLEX_MODEL", "nvidia/personaplex-7b-v1")
PERSONAPLEX_URL = os.getenv("PERSONAPLEX_URL", "https://jj8s2oaqa396jo-8998.proxy.runpod.net")

# Defaults (Legacy Support)
VLLM_BASE_URL = MODEL_BACKENDS["Meta Llama 3.1"]["base_url"]
VLLM_MODEL = MODEL_BACKENDS["Meta Llama 3.1"]["model"]
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.6"))

# =============================================================================
# RAG SETTINGS
# =============================================================================
# Embeddings
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

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
WHATSAPP_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v21.0")

# =============================================================================
# MODEL ALIASES
# =============================================================================
LLM_MODEL = VLLM_MODEL  # Alias for backward compatibility
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "liquid")  # liquid, elevenlabs, piper, etc.

# =============================================================================
# VOICE ENGINE (LiquidAI)
# =============================================================================
VOICE_MODEL = os.getenv("VOICE_MODEL", "LiquidAI/LFM2.5-Audio-1.5B")
VOICE_MAX_INSTANCES = int(os.getenv("VOICE_MAX_INSTANCES", "8"))
