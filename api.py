"""
OmniCortex FastAPI Backend
REST API for chat, agents, and documents
"""
import time
import uuid
import json
import hmac
import hashlib
import asyncio
import datetime
import re
import ssl
from typing import Optional, List, Dict, Any, Union
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response, JSONResponse
import logging
import os
from pathlib import Path

# Setup WhatsApp Logger
log_dir = Path("storage/logs")
log_dir.mkdir(parents=True, exist_ok=True)
wa_logger = logging.getLogger("whatsapp")
wa_logger.setLevel(logging.INFO)
wa_handler = logging.FileHandler(log_dir / "whatsapp.log")
wa_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
wa_logger.addHandler(wa_handler)

# Setup Query Trace Logger (query + response + latency)
query_logger = logging.getLogger("query_trace")
query_logger.setLevel(logging.INFO)
query_handler = logging.FileHandler(log_dir / "query_trace.log")
query_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
query_logger.addHandler(query_handler)

# Import core modules
from core import (
    get_all_agents,
    get_agent,
    create_agent,
    update_agent,
    update_agent_metadata,
    delete_agent,
    get_agent_documents,
    delete_document,
    get_conversation_history,
    clear_history,
    process_question,
    process_documents,
    reset_chain,
)
from core.database import Channel, Tool, Session as DBSession, SessionLocal, ApiKey # Phase 2 & 3 & 4 support
# core.graph.create_rag_agent removed — not used by any route
from core.processing.scraper import process_urls
from core.config import MODEL_BACKENDS
from core.agent_config import sync_agent_config

# Import metrics from core.monitoring
from core.monitoring import (
    REQUEST_COUNT,
    REQUEST_LATENCY,
    CHAT_REQUESTS,
)
from core.manager.connection_manager import ConnectionManager
from core.auth import get_api_key, verify_bearer_token
from fastapi import Depends

# Initialize Connection Manager
manager = ConnectionManager()

# ============== APP SETUP ==============
from core.database import init_db

# Initialize Database
init_db()


# ============== STARTUP VALIDATION ==============
# Using modern lifespan context manager (replaces deprecated @app.on_event)
async def validate_dependencies():
    """
    Validate required dependencies on startup.
    Exit if critical dependencies are unavailable.
    """
    import sys
    import requests

    strict_startup = os.getenv("STRICT_STARTUP_VALIDATION", "false").lower() == "true"

    print("\n" + "=" * 60)
    print("  OmniCortex Backend - Startup Validation")
    print("=" * 60)

    all_ok = True

    # Check Database
    print("\n[1/2] Checking PostgreSQL...")
    try:
        from core.database import SessionLocal
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
        from sqlalchemy import text as sa_text

        def check_db():
            db = SessionLocal()
            try:
                db.execute(sa_text("SELECT 1"))
                return True
            finally:
                db.close()

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(check_db)
            try:
                future.result(timeout=10)
                print("  PostgreSQL connected")
            except FutureTimeoutError:
                print("  PostgreSQL connection timeout (10s)")
                all_ok = False
            except Exception as e:
                print(f"  PostgreSQL connection failed: {e}")
                all_ok = False
    except Exception as e:
        print(f"  PostgreSQL connection failed: {e}")
        all_ok = False

    # Check LLM backend (vLLM/OpenAI-compatible endpoint)
    default_backend = MODEL_BACKENDS.get("default", {})
    expected_model = default_backend.get("model", "meta-llama/Llama-3.1-8B-Instruct")
    vllm_base_url = default_backend.get("base_url", "http://localhost:8080/v1")

    print(f"\n[2/2] Checking vLLM at {vllm_base_url}...")
    try:
        base = vllm_base_url.rstrip("/")
        health_url = base.replace("/v1", "") + "/health"
        models_url = f"{base}/models"

        # Prefer /health for local vLLM and fall back to OpenAI-compatible /v1/models.
        response = requests.get(health_url, timeout=10)
        if response.status_code == 200:
            print(f"  vLLM running with {expected_model}")
        else:
            response = requests.get(models_url, timeout=10)
            if response.status_code == 200:
                print(f"  vLLM/OpenAI endpoint reachable with model target {expected_model}")
            else:
                print(f"  vLLM returned status {response.status_code}")
                all_ok = False
    except Exception as e:
        print(f"  vLLM connection failed: {e}")
        all_ok = False

    print("\n" + "=" * 60)
    if all_ok:
        print("  All dependencies validated")
        print("  Backend ready on http://localhost:8000")
        print("  API docs: http://localhost:8000/docs")
    else:
        print("  Dependency validation failed")
        if strict_startup:
            print("  STRICT_STARTUP_VALIDATION=true, backend will exit")
            print("=" * 60 + "\n")
            raise RuntimeError("Dependency validation failed")
        print("  Continuing startup in non-strict mode")

    print("=" * 60 + "\n")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Modern lifespan handler (replaces deprecated on_event)"""
    await validate_dependencies()
    yield


app = FastAPI(
    title="OmniCortex API",
    description="Modern RAG Chatbot API with LangGraph, Prometheus metrics",
    version="1.0.0",
    lifespan=lifespan
)

# CORS Configuration - reads from CORS_ORIGINS env var for production flexibility
_default_origins = "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001"
_cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", _default_origins).split(",") if o.strip()]
_default_origin_regex = r"^https://.*\.proxy\.runpod\.net$|^https://.*\.trycloudflare\.com$"
_cors_origin_regex = (os.getenv("CORS_ORIGIN_REGEX", _default_origin_regex) or "").strip()
_cors_origin_pattern = re.compile(_cors_origin_regex) if _cors_origin_regex else None

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=_cors_origin_regex or None,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,  # Cache preflight requests for 1 hour
)

# Track startup time for uptime calculation
STARTUP_TIME = datetime.datetime.now()

# Health check cache
_health_cache = {"result": None, "timestamp": 0}


# ============== MODELS ==============
class QueryRequest(BaseModel):
    question: Optional[str] = None
    query: Optional[str] = None
    id: Optional[str] = None
    user_id: Optional[str] = "anonymous" # For session tracking
    session_id: Optional[str] = None # Resume existing session
    max_history: int = 5
    channel_name: Optional[str] = "TEXT"  # TEXT | VOICE
    channel_type: Optional[str] = "UTILITY"  # TEXT: UTILITY|MARKETING|AUTHENTICATION, VOICE: PROMOTIONAL|TRANSACTIONAL
    mock_mode: bool = False  # True = bypass LLM for load testing


class QueryResponse(BaseModel):
    answer: str
    id: Optional[str] = None
    session_id: Optional[str] = None
    request_id: Optional[str] = None


class AgentDocumentText(BaseModel):
    filename: str
    text: str

class ScrapedContent(BaseModel):
    url: Optional[str] = None
    text: str

class ConversationStarterItem(BaseModel):
    icon: Optional[str] = None
    label: Optional[str] = None
    prompt: Optional[str] = None

class LegacyDocumentRef(BaseModel):
    url: str
    type: Optional[str] = None

class LegacyDocumentData(BaseModel):
    image_urls: Optional[List[str]] = None
    video_urls: Optional[List[str]] = None
    documents_text: Optional[List[LegacyDocumentRef]] = None

class AgentCreate(BaseModel):
    # Current schema
    agent_name: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = ""
    system_prompt: Optional[str] = None
    role_type: Optional[str] = None
    industry: Optional[str] = None
    urls: Optional[List[str]] = None
    conversation_starters: Optional[List[Union[str, ConversationStarterItem]]] = None
    image_urls: Optional[List[str]] = None
    video_urls: Optional[List[str]] = None
    documents_text: Optional[List[AgentDocumentText]] = None
    scraped_data: Optional[List[ScrapedContent]] = None
    file_paths: Optional[List[str]] = None  # Backward-compatible local files path list

    # Legacy/postman compatibility schema
    id: Union[int, str]
    agentname: Optional[str] = None
    agent_type: Optional[str] = None
    subagent_type: Optional[str] = None
    model_selection: Optional[str] = None
    website_data: Optional[List[str]] = None
    document_data: Optional[LegacyDocumentData] = None
    logic: Optional[Union[str, Dict[str, Any]]] = None
    instruction: Optional[str] = None
    conversation_end: Optional[List[Union[str, ConversationStarterItem]]] = None

class StatusResponse(BaseModel):
    status: str
    id: Optional[str] = None
    document_id: Optional[int] = None

class AgentResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    system_prompt: Optional[str]
    
    role_type: Optional[str]
    industry: Optional[str]
    urls: Optional[List[str]]
    conversation_starters: Optional[List[str]]
    image_urls: Optional[List[str]]
    video_urls: Optional[List[str]]
    scraped_data: Optional[List[Dict[str, str]]]
    logic: Optional[Union[str, Dict[str, Any]]] = None
    conversation_end: Optional[List[Dict[str, str]]] = None
    agent_type: Optional[str] = None
    subagent_type: Optional[str] = None
    model_selection: Optional[str] = None
    
    document_count: int
    message_count: int
    webhook_url: Optional[str] = None

class AgentListItem(BaseModel):
    id: str
    agent_type: Optional[str] = None
    agent_name: str

class AgentCreateResponse(BaseModel):
    status: str
    id: str
    agent_name: str


class AgentSystemPromptResponse(BaseModel):
    agent_id: str
    system_prompt: str
    source: Optional[str] = None

class AgentUpdate(BaseModel):
    name: Optional[str] = None
    agent_name: Optional[str] = None
    agentname: Optional[str] = None
    id: Optional[Union[int, str]] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    role_type: Optional[str] = None
    industry: Optional[str] = None
    urls: Optional[List[str]] = None
    website_data: Optional[List[str]] = None
    document_data: Optional[LegacyDocumentData] = None
    conversation_starters: Optional[List[Union[str, ConversationStarterItem]]] = None
    image_urls: Optional[List[str]] = None
    video_urls: Optional[List[str]] = None
    documents_text: Optional[List[AgentDocumentText]] = None
    file_paths: Optional[List[str]] = None
    scraped_data: Optional[List[ScrapedContent]] = None
    logic: Optional[Union[str, Dict[str, Any]]] = None
    instruction: Optional[str] = None
    conversation_end: Optional[List[Union[str, ConversationStarterItem]]] = None
    agent_type: Optional[str] = None
    subagent_type: Optional[str] = None
    model_selection: Optional[str] = None
    restart_after_update: bool = False

# ============== MESSAGING MODELS (PHASE 2) ==============
class ChannelCreate(BaseModel):
    name: str
    type: str # whatsapp, voice
    provider: str # meta, twilio
    config: Optional[Dict] = {}
    agent_id: Optional[str] = None

class ChannelResponse(BaseModel):
    id: str
    name: str
    type: str
    provider: Optional[str]
    config: Optional[Dict]
    agent_id: Optional[str]
    created_at: Optional[str]

class ToolCreate(BaseModel):
    name: str
    type: str # flow, button_reply, webhook, schedule
    content: Dict
    agent_id: str

class ToolResponse(BaseModel):
    id: str
    name: str
    type: str
    content: Dict
    agent_id: str
    created_at: Optional[str]


class ToolDispatchRequest(BaseModel):
    to_number: str
    dry_run: bool = True


class VoiceProfileUpdate(BaseModel):
    api_key: Optional[str] = None
    selected_agent_id: Optional[str] = None
    context_query: Optional[str] = None
    voice_prompt: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None


class VoiceProfileResponse(BaseModel):
    status: str
    profile: Dict[str, Any]


class VertoCheckResponse(BaseModel):
    status: str
    url: str
    ssl_verify: bool
    timeout_sec: float
    detail: Optional[str] = None


# ============== MIDDLEWARE ==============
@app.middleware("http")
async def cors_error_logging_middleware(request, call_next):
    """Log CORS-related errors and issues"""
    origin = request.headers.get("origin")
    method = request.method
    
    # Log CORS preflight requests
    if method == "OPTIONS":
        logging.info(f"CORS Preflight: {origin} -> {request.url.path}")
    
    # Log requests with Origin header
    if origin:
        origin_allowed = origin in _cors_origins or (
            _cors_origin_pattern is not None and _cors_origin_pattern.match(origin) is not None
        )
        if not origin_allowed:
            logging.warning(f"CORS Blocked: Origin '{origin}' not in allowlist for {request.url.path}")
    
    response = await call_next(request)
    
    # Log CORS errors (missing headers in response)
    if origin and response.status_code >= 400:
        cors_header = response.headers.get("access-control-allow-origin")
        if not cors_header:
            logging.error(f"CORS Error: Missing CORS headers in response for {origin} -> {request.url.path} (status: {response.status_code})")
    
    return response


@app.middleware("http")
async def metrics_middleware(request, call_next):
    """Track request metrics"""
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time
    
    REQUEST_COUNT.labels(
        method=request.method,
        endpoint=request.url.path,
        status=response.status_code
    ).inc()
    
    REQUEST_LATENCY.labels(
        method=request.method,
        endpoint=request.url.path
    ).observe(duration)
    
    return response


# ============== ENDPOINTS ==============

@app.get("/")
async def root():
    """Basic health check endpoint"""
    return {"status": "ok", "service": "OmniCortex API", "version": "1.0.0"}


@app.get("/health")
async def health_check():
    """
    Comprehensive health check endpoint
    Returns service status, database connectivity, and LLM availability
    Results cached for 5 seconds to avoid overwhelming dependencies
    """
    import datetime
    import json
    
    # Check cache (5 second TTL)
    current_time = time.time()
    if _health_cache["result"] and (current_time - _health_cache["timestamp"]) < 5:
        cached_result = _health_cache["result"]
        status_code = 200 if cached_result["status"] == "healthy" else 503
        return Response(
            content=json.dumps(cached_result),
            media_type="application/json",
            status_code=status_code
        )
    
    from core.config import MOSHI_ENABLED, PERSONAPLEX_URL

    health_status = {
        "status": "healthy",
        "version": "1.0.0",
        "timestamp": datetime.datetime.now().isoformat(),
        "services": {
            "database": {"status": "down", "latency_ms": 0},
            "llm": {"status": "down", "latency_ms": 0, "model_loaded": False},
            "moshi": {
                "status": "disabled" if not MOSHI_ENABLED else "down",
                "latency_ms": 0,
                "url": PERSONAPLEX_URL,
            },
        },
        "uptime_seconds": int((datetime.datetime.now() - STARTUP_TIME).total_seconds())
    }
    
    # Check Database
    try:
        from core.database import SessionLocal
        from sqlalchemy import text as sa_text
        db_start = time.time()
        db = SessionLocal()
        try:
            db.execute(sa_text("SELECT 1"))
            db_latency = int((time.time() - db_start) * 1000)
            health_status["services"]["database"] = {
                "status": "up",
                "latency_ms": db_latency
            }
        finally:
            db.close()
    except Exception as e:
        logging.error(f"Database health check failed: {e}")
        health_status["status"] = "unhealthy"
        health_status["services"]["database"]["error"] = str(e)
    
    # Check LLM backend (vLLM/OpenAI-compatible endpoint)
    try:
        import requests
        default_backend = MODEL_BACKENDS.get("default", {})
        vllm_base_url = default_backend.get("base_url", "http://localhost:8080/v1")
        expected_model = default_backend.get("model", "meta-llama/Llama-3.1-8B-Instruct")

        llm_start = time.time()
        base = vllm_base_url.rstrip("/")
        health_url = base.replace("/v1", "") + "/health"
        models_url = f"{base}/models"

        response = requests.get(health_url, timeout=2)
        llm_latency = int((time.time() - llm_start) * 1000)
        status = "up" if response.status_code == 200 else "degraded"

        if response.status_code != 200:
            response = requests.get(models_url, timeout=2)
            status = "up" if response.status_code == 200 else "degraded"

        health_status["services"]["llm"] = {
            "status": status,
            "backend": "vllm",
            "latency_ms": llm_latency,
            "model": expected_model
        }
        if status != "up":
            health_status["status"] = "degraded"
    except Exception as e:
        logging.error(f"LLM health check failed: {e}")
        health_status["status"] = "unhealthy"
        health_status["services"]["llm"] = {"status": "down", "error": str(e)}

    # Check Moshi voice backend (optional service in this stack)
    if MOSHI_ENABLED:
        try:
            import requests

            moshi_start = time.time()
            moshi_response = requests.get(PERSONAPLEX_URL, timeout=2)
            moshi_latency = int((time.time() - moshi_start) * 1000)
            # Treat reachable HTTP service as "up" even for non-2xx endpoint responses.
            moshi_status = "up" if moshi_response.status_code < 500 else "degraded"
            health_status["services"]["moshi"] = {
                "status": moshi_status,
                "latency_ms": moshi_latency,
                "url": PERSONAPLEX_URL,
                "http_status": moshi_response.status_code,
            }
        except Exception as e:
            health_status["services"]["moshi"] = {
                "status": "down",
                "latency_ms": 0,
                "url": PERSONAPLEX_URL,
                "error": str(e),
            }

    # Cache result
    _health_cache["result"] = health_status
    _health_cache["timestamp"] = current_time
    
    # Return appropriate status code
    status_code = 200 if health_status["status"] == "healthy" else 503
    
    return Response(
        content=json.dumps(health_status),
        media_type="application/json",
        status_code=status_code
    )


@app.options("/{full_path:path}")
async def options_handler(full_path: str):
    """Handle CORS preflight requests"""
    return {"status": "ok"}


@app.get("/metrics")
async def metrics(api_key: ApiKey = Depends(get_api_key)):
    """Expose Prometheus metrics"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/stats/dashboard")
async def dashboard_stats(api_key: ApiKey = Depends(get_api_key)):
    """Get aggregated metrics for dashboard graphs"""
    from core.database import SessionLocal, Agent, Document, Session, UsageLog
    from sqlalchemy import func, desc
    
    db = SessionLocal()
    try:
        # 1. Counts
        total_agents = db.query(Agent).count()
        total_documents = db.query(Document).count()
        total_sessions = db.query(Session).count()
        
        # 2. Document Status
        doc_status = db.query(
            Document.status, func.count(Document.id)
        ).group_by(Document.status).all()
        doc_stats = {status: count for status, count in doc_status}
        
        # 3. Usage Stats (Last 24h or total)
        # For simplicity, we return total cost and tokens
        total_cost = db.query(func.sum(UsageLog.cost)).scalar() or 0.0
        total_tokens = db.query(func.sum(UsageLog.total_tokens)).scalar() or 0
        
        # 4. Recent Activity (Sessions)
        recent_sessions = db.query(Session).order_by(desc(Session.start_time)).limit(5).all()
        activity_log = [
            {
                "id": s.id,
                "user": s.user_id,
                "agent_id": s.agent_id,
                "start": s.start_time.isoformat(),
                "duration": s.duration,
                "status": s.status
            }
            for s in recent_sessions
        ]
        
        return {
            "counts": {
                "agents": total_agents,
                "documents": total_documents,
                "sessions": total_sessions
            },
            "documents": {
                "total": total_documents,
                "by_status": doc_stats
            },
            "usage": {
                "total_cost": round(total_cost, 4),
                "total_tokens": total_tokens
            },
            "recent_activity": activity_log
        }
    finally:
        db.close()

@app.get("/documents/{document_id}/chunks")
async def get_document_chunks_api(document_id: int, api_key: ApiKey = Depends(get_api_key)):
    """Get chunks for a specific document (Parent Chunks)"""
    # Note: We currently store parent chunks in 'omni_parent_chunks' linked by source_doc_id
    from core.database import ParentChunk, SessionLocal
    db = SessionLocal()
    try:
         chunks = db.query(ParentChunk).filter(ParentChunk.source_doc_id == document_id).all()
         return [
             {"id": c.id, "content": c.content[:200] + "..." if len(c.content) > 200 else c.content} 
             for c in chunks
         ]
    finally:
        db.close()


@app.get("/stats/agents")
async def agent_stats(api_key: ApiKey = Depends(get_api_key)):
    """Get comprehensive stats for all agents including tokens and latency"""
    from core.database import get_usage_stats, SessionLocal
    from core.database import Agent, UsageLog
    from sqlalchemy import func
    
    db = SessionLocal()
    try:
        # Get all agents with aggregated stats
        agents = get_all_agents()
        
        stats = []
        for agent in agents:
            agent_id = agent['id']
            
            # Get usage stats for this agent
            usage = db.query(
                func.sum(UsageLog.query_tokens).label('total_query'),
                func.sum(UsageLog.rag_query_tokens).label('total_rag_query'),
                func.sum(UsageLog.prompt_tokens).label('total_prompt'),
                func.sum(UsageLog.completion_tokens).label('total_completion'),
                func.sum(UsageLog.total_tokens).label('total_tokens'),
                func.sum(UsageLog.cost).label('total_cost'),
                func.avg(UsageLog.latency).label('avg_latency'),
                func.max(UsageLog.latency).label('max_latency'),
                func.count(UsageLog.id).label('request_count')
            ).filter(UsageLog.agent_id == agent_id).first()
            
            stats.append({
                "agent_id": agent_id,
                "agent_name": agent['name'],
                "document_count": agent.get('document_count', 0),
                "message_count": agent.get('message_count', 0),
                "total_query_tokens": usage.total_query or 0,
                "total_rag_query_tokens": usage.total_rag_query or 0,
                "total_prompt_tokens": usage.total_prompt or 0,
                "total_completion_tokens": usage.total_completion or 0,
                "total_tokens": usage.total_tokens or 0,
                "total_cost_usd": round(usage.total_cost or 0, 6),
                "avg_latency_seconds": round(usage.avg_latency or 0, 3),
                "max_latency_seconds": round(usage.max_latency or 0, 3),
                "total_requests": usage.request_count or 0
            })
        
        return {
            "agents": stats,
            "total_agents": len(agents)
        }
    finally:
        db.close()


# --- Chat ---
@app.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest, api_key: ApiKey = Depends(get_api_key)):
    """Chat with an agent using RAG."""
    request_id = str(uuid.uuid4())
    started = time.perf_counter()
    agent_id = _normalize_uuid(request.id, "id", required=True)
    # Enforce that only the owning API key can use this agent.
    agent = _require_agent_access(agent_id, api_key)
    legacy_auth_user_id = _legacy_user_id_from_api_key(api_key)

    resolved_question = _resolve_query_text(request)
    if not resolved_question:
        raise HTTPException(status_code=400, detail="question (or query) is required")

    resolved_model_selection = _normalize_model_selection(agent.get("model_selection"))
    normalized_channel_name = _normalize_channel_name(request.channel_name)
    normalized_channel_type = _normalize_channel_type(request.channel_type, normalized_channel_name)
    product_id = _product_id_from_channel_name(normalized_channel_name)
    question_preview = resolved_question[:500].replace("\n", " ").strip()
    request_user_id = str(request.user_id or "").strip()
    agent_user_id = str(agent.get("user_id") or "").strip()
    request_user_id_clean = (
        request_user_id if request_user_id and request_user_id.lower() != "anonymous" else None
    )
    effective_user_id = request_user_id
    if not effective_user_id or effective_user_id.lower() == "anonymous":
        effective_user_id = agent_user_id or legacy_auth_user_id or "anonymous"
    analytics_user_id = agent_user_id or legacy_auth_user_id or request_user_id_clean

    # Privacy/Logging config
    PRIVACY_PSEUDONYMIZE = os.getenv("LOG_PSEUDONYMIZE", "true").lower() == "true"
    PRIVACY_REDACT = os.getenv("LOG_REDACT_QUESTION", "true").lower() == "true"

    import hashlib, re
    _PSEUDONYMIZE_SECRET = os.getenv("PSEUDONYMIZE_SECRET", "default_secret")

    def pseudonymize_user_id(user_id):
        if not PRIVACY_PSEUDONYMIZE or not user_id:
            return user_id
        # Stable HMAC hash, truncate for log
        h = hmac.new(_PSEUDONYMIZE_SECRET.encode(), str(user_id).encode(), hashlib.sha256)
        return h.hexdigest()[:12]

    def redact_question_preview(q):
        if not PRIVACY_REDACT or not q:
            return q
        # Redact emails, phone numbers, credit cards
        q = re.sub(r"[\w\.-]+@[\w\.-]+", "[REDACTED_EMAIL]", q)
        q = re.sub(r"\b\d{10,16}\b", "[REDACTED_NUMBER]", q)
        q = re.sub(r"\b(?:\d{3}[-.\s]?){2}\d{4}\b", "[REDACTED_PHONE]", q)
        # Optionally redact long free-text
        if len(q) > 100:
            return "[REDACTED_LONG_TEXT]"
        return q

    query_logger.info(json.dumps({
        "event": "query_in",
        "request_id": request_id,
        "id": agent_id,
        "session_id": request.session_id,
        "user_id": pseudonymize_user_id(effective_user_id),
        "model_selection": resolved_model_selection,
        "model_selection_source": "agent_config" if resolved_model_selection else "default_backend",
        "channel_name": normalized_channel_name,
        "channel_type": normalized_channel_type,
        "product_id": product_id,
        "mock_mode": request.mock_mode,
        "question_preview": redact_question_preview(question_preview),
    }, ensure_ascii=False))

    try:
        # Track metrics
        CHAT_REQUESTS.labels(agent_id=agent_id).inc()
        
        # Session Tracking
        session_id = request.session_id
        db = None
        try:
            if not session_id:
                # Auto-session policy: one generated session per agent+user+channel per day.
                if agent_id:
                    from sqlalchemy import func as sa_func

                    db = SessionLocal()
                    user_key = effective_user_id or "anonymous"
                    channel_key = (normalized_channel_name or "TEXT").lower()
                    today = datetime.datetime.now().date()

                    existing_session = (
                        db.query(DBSession)
                        .filter(
                            DBSession.agent_id == agent_id,
                            DBSession.user_id == user_key,
                            DBSession.channel_type == channel_key,
                            sa_func.date(DBSession.start_time) == today,
                        )
                        .order_by(DBSession.start_time.desc())
                        .first()
                    )

                    if existing_session:
                        session_id = existing_session.id
                    else:
                        session_id = str(uuid.uuid4())
                        new_sess = DBSession(
                            id=session_id,
                            agent_id=agent_id,
                            user_id=user_key,
                            status="active",
                            channel_type=channel_key,
                        )
                        db.add(new_sess)
                        db.commit()
                else:
                    # No agent id to anchor persistence, return ephemeral generated session id.
                    session_id = str(uuid.uuid4())
            
            # Update existing session duration/end_time is usually done on completion or heartbeat
            # For now, we just ensure it exists
        except Exception as e:
            logging.warning(f"Session tracking error: {e}")
            print(f"⚠️ Session tracking error: {e}")
        finally:
            if db is not None:
                db.close()
            
        
        # Mock Mode: Skip LLM for load testing (tests DB + vector store only)
        if request.mock_mode:
            # Simulate minimal processing
            await asyncio.sleep(0.1)  # Simulate network latency
            response = QueryResponse(
                answer="[MOCK] Load test response - LLM bypassed",
                id=agent_id,
                session_id=session_id,
                request_id=request_id,
            )
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            query_logger.info(json.dumps({
                "event": "query_out",
                "request_id": request_id,
                "status": 200,
                "latency_ms": latency_ms,
                "answer_preview": response.answer[:500].replace("\n", " ").strip(),
                "answer_chars": len(response.answer or ""),
            }, ensure_ascii=False))
            return response
        
        # Get conversation history
        history = []
        if agent_id:
            history = get_conversation_history(
                agent_id=agent_id,
                limit=request.max_history * 2
            )
        
        # Process question
        answer = process_question(
            question=resolved_question,
            agent_id=agent_id,
            conversation_history=history,
            max_history=request.max_history,
            model_selection=resolved_model_selection,
            request_id=request_id,
            session_id=session_id,
            user_id=analytics_user_id,
            channel_name=normalized_channel_name,
            channel_type=normalized_channel_type,
        )
        
        # Replace [image][filename] and other tags with actual URLs/Markdown for frontend
        from core.response_parser import process_rich_response_for_frontend
        answer = process_rich_response_for_frontend(answer, agent_id=agent_id)
        
        response = QueryResponse(
            answer=answer,
            id=agent_id,
            session_id=session_id,
            request_id=request_id,
        )
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        query_logger.info(json.dumps({
            "event": "query_out",
            "request_id": request_id,
            "status": 200,
            "latency_ms": latency_ms,
            "answer_preview": (answer or "")[:500].replace("\n", " ").strip(),
            "answer_chars": len(answer or ""),
        }, ensure_ascii=False))
        return response
    
    except FileNotFoundError:
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        try:
            from core.clickhouse import log_usage_to_clickhouse

            log_usage_to_clickhouse(
                agent_id=agent_id,
                model=resolved_model_selection or MODEL_BACKENDS.get("default", {}).get("model", "unknown"),
                prompt_tokens=0,
                completion_tokens=0,
                latency_ms=latency_ms,
                cost=0.0,
                request_id=request_id,
                session_id=locals().get("session_id"),
                user_id=analytics_user_id,
                channel_name=normalized_channel_name,
                channel_type=normalized_channel_type,
                product_id=product_id,
                status="error",
                error="Upload documents first",
            )
        except Exception:
            pass
        query_logger.error(json.dumps({
            "event": "query_error",
            "request_id": request_id,
            "status": 400,
            "latency_ms": latency_ms,
            "error": "Upload documents first",
        }, ensure_ascii=False))
        raise HTTPException(status_code=400, detail="Upload documents first")
    except Exception as e:
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        try:
            from core.clickhouse import log_usage_to_clickhouse

            log_usage_to_clickhouse(
                agent_id=agent_id,
                model=resolved_model_selection or MODEL_BACKENDS.get("default", {}).get("model", "unknown"),
                prompt_tokens=0,
                completion_tokens=0,
                latency_ms=latency_ms,
                cost=0.0,
                request_id=request_id,
                session_id=locals().get("session_id"),
                user_id=analytics_user_id,
                channel_name=normalized_channel_name,
                channel_type=normalized_channel_type,
                product_id=product_id,
                status="error",
                error=str(e),
            )
        except Exception:
            pass
        query_logger.error(json.dumps({
            "event": "query_error",
            "request_id": request_id,
            "status": 500,
            "latency_ms": latency_ms,
            "error": str(e),
        }, ensure_ascii=False))
        raise HTTPException(status_code=500, detail=str(e))



@app.websocket("/ws/chat/{agent_id}")
async def websocket_endpoint(websocket: WebSocket, agent_id: str):
    """
    WebSocket endpoint for real-time chat.
    Connects to the agent's channel.
    Supports JSON protocol: {"content": "message"}
    """
    await manager.connect(websocket, agent_id)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                payload = json.loads(data)
                question = payload.get("content")
            except json.JSONDecodeError:
                question = data # Fallback to raw text

            if question:
                # 1. Send "Thinking" status
                await manager.send_personal_message(json.dumps({"type": "status", "status": "thinking"}), websocket)
                
                # 2. Process with actual RAG pipeline (run in thread to avoid blocking)
                try:
                    history = get_conversation_history(agent_id=agent_id, limit=10)
                    resolved_model_selection = _resolve_model_selection_for_agent(agent_id)
                    answer = await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: process_question(
                            question=question,
                            agent_id=agent_id,
                            conversation_history=history,
                            model_selection=resolved_model_selection,
                            request_id=str(uuid.uuid4()),
                            user_id="websocket",
                            channel_name="websocket",
                        )
                    )
                except Exception as e:
                    answer = f"Error: {str(e)}"
                
                # 3. Send Answer
                await manager.send_personal_message(json.dumps({"type": "message", "content": answer}), websocket)
                
                # 4. Send "Idle" status
                await manager.send_personal_message(json.dumps({"type": "status", "status": "idle"}), websocket)

    except WebSocketDisconnect:
        manager.disconnect(websocket, agent_id)


# --- Agents ---
ROLE_TYPES = {"personal", "business", "knowledge"}
PERSONAL_ROLES = {
    "Personal Assistant",
    "Learning Companion",
    "Creative Helper",
    "Health Wellness Companion",
    "PersonalAssistant",
    "LearningCompanion",
    "CreativeHelper",
    "HealthWellness",
    "TaskManagement",
    "ResearchAssistant",
    "CustomerSupport",
    "SalesOutbound",
    "AppointmentScheduling",
    "LeadQualification",
    "OrderProcessing",
    "TechnicalSupport",
    "BillingInquiries",
    "ProductInformation",
    "SurveyFeedback",
    "EmergencyResponse",
    "ReservationBooking",
    "ComplianceVerification",
}
BUSINESS_INDUSTRIES = {
    "Retail Commerce Assistant",
    "Healthcare Assistant",
    "Finance Banking Assistant",
    "Real Estate Sales Assistant",
    "Education Enrollment Assistant",
    "Hospitality Concierge",
    "Automotive Service Assistant",
    "Professional Services Consultant",
    "Tech Support Assistant",
    "Public Services Assistant (Government)",
    "Food Service Assistant",
    "Manufacturing Support Assistant",
    "Fitness Wellness Assistant",
    "Legal Services Coordinator",
    "Non-Profit Outreach Assistant",
    "Entertainment Services Assistant",
    "RetailEcommerce",
    "HealthcareMedical",
    "FinanceBanking",
    "RealEstate",
    "EducationTraining",
    "HospitalityTravel",
    "Automotive",
    "ProfessionalServices",
    "TechnologySoftware",
    "GovernmentPublic",
    "FoodBeverage",
    "Manufacturing",
    "FitnessWellness",
    "LegalServices",
    "NonProfit",
    "MediaEntertainment",
}
MAX_URLS = 25
MAX_CONVERSATION_STARTERS = 25
MAX_MEDIA_URLS = 25
CHANNEL_NAMES = {"TEXT", "VOICE"}
TEXT_CHANNEL_TYPES = {"UTILITY", "MARKETING", "AUTHENTICATION"}
VOICE_CHANNEL_TYPES = {"PROMOTIONAL", "TRANSACTIONAL"}
CHANNEL_TYPES = TEXT_CHANNEL_TYPES | VOICE_CHANNEL_TYPES
CHANNEL_PRODUCT_IDS = {
    "TEXT": 6,   # WhatsApp product
    "VOICE": 2,  # Voice product
}

AGENT_TYPE_ALIASES = {
    "blankagent": "BlankAgent",
    "blank": "BlankAgent",
    "personalassistant": "PersonalAssistant",
    "personal": "PersonalAssistant",
    "businessagent": "BusinessAgent",
    "business": "BusinessAgent",
}

BUSINESS_SUBAGENT_CANONICAL = {
    "retailecommerce": "RetailEcommerce",
    "healthcaremedical": "HealthcareMedical",
    "financebanking": "FinanceBanking",
    "realestate": "RealEstate",
    "educationtraining": "EducationTraining",
    "hospitalitytravel": "HospitalityTravel",
    "automotive": "Automotive",
    "professionalservices": "ProfessionalServices",
    "technologysoftware": "TechnologySoftware",
    "governmentpublic": "GovernmentPublic",
    "foodbeverage": "FoodBeverage",
    "manufacturing": "Manufacturing",
    "fitnesswellness": "FitnessWellness",
    "legalservices": "LegalServices",
    "nonprofit": "NonProfit",
    "mediaentertainment": "MediaEntertainment",
}

PERSONAL_ROLE_CANONICAL = {
    "personalassistant": "PersonalAssistant",
    "learningcompanion": "LearningCompanion",
    "creativehelper": "CreativeHelper",
    "healthwellness": "HealthWellness",
    "taskmanagement": "TaskManagement",
    "researchassistant": "ResearchAssistant",
    "customersupport": "CustomerSupport",
    "salesoutbound": "SalesOutbound",
    "appointmentscheduling": "AppointmentScheduling",
    "leadqualification": "LeadQualification",
    "orderprocessing": "OrderProcessing",
    "technicalsupport": "TechnicalSupport",
    "billinginquiries": "BillingInquiries",
    "productinformation": "ProductInformation",
    "surveyfeedback": "SurveyFeedback",
    "emergencyresponse": "EmergencyResponse",
    "reservationbooking": "ReservationBooking",
    "complianceverification": "ComplianceVerification",
}

BUSINESS_PROMPT_BY_SUBAGENT = {
    "retailecommerce": "prompts/business/01-business-retail-ecommerce.json",
    "healthcaremedical": "prompts/business/02-business-healthcare-medical.json",
    "financebanking": "prompts/business/03-business-finance-banking.json",
    "realestate": "prompts/business/04-business-real-estate.json",
    "educationtraining": "prompts/business/05-business-education-training.json",
    "hospitalitytravel": "prompts/business/06-business-hospitality-travel.json",
    "automotive": "prompts/business/07-business-automotive.json",
    "professionalservices": "prompts/business/08-business-professional-services.json",
    "technologysoftware": "prompts/business/09-business-technology-software.json",
    "governmentpublic": "prompts/business/10-business-government-public.json",
    "foodbeverage": "prompts/business/11-business-food-beverage.json",
    "manufacturing": "prompts/business/12-business-manufacturing.json",
    "fitnesswellness": "prompts/business/13-business-fitness-wellness.json",
    "legalservices": "prompts/business/14-business-legal-services.json",
    "nonprofit": "prompts/business/15-business-non-profit.json",
    "mediaentertainment": "prompts/business/16-business-media-entertainment.json",
}

PERSONAL_PROMPT_BY_ROLE = {
    "personalassistant": "prompts/personal/01-personal-personal-assistant.json",
    "learningcompanion": "prompts/personal/02-personal-learning-companion.json",
    "creativehelper": "prompts/personal/03-personal-creative-helper.json",
    "healthwellness": "prompts/personal/04-personal-health-wellness.json",
    "taskmanagement": "prompts/personal/05-personal-task-management.json",
    "researchassistant": "prompts/personal/06-personal-research-assistant.json",
    # Current prompt library fallback mappings
    "customersupport": "prompts/personal/05-personal-task-management.json",
    "salesoutbound": "prompts/personal/05-personal-task-management.json",
    "appointmentscheduling": "prompts/personal/05-personal-task-management.json",
    "leadqualification": "prompts/personal/05-personal-task-management.json",
    "orderprocessing": "prompts/personal/05-personal-task-management.json",
    "technicalsupport": "prompts/personal/06-personal-research-assistant.json",
    "billinginquiries": "prompts/personal/05-personal-task-management.json",
    "productinformation": "prompts/personal/06-personal-research-assistant.json",
    "surveyfeedback": "prompts/personal/05-personal-task-management.json",
    "emergencyresponse": "prompts/personal/01-personal-personal-assistant.json",
    "reservationbooking": "prompts/personal/05-personal-task-management.json",
    "complianceverification": "prompts/personal/06-personal-research-assistant.json",
}

MODEL_SELECTION_ALIASES = {
    "Meta Llama-3.1-8B-Instruct": "Meta Llama 3.1",
    "Meta-Llama-3.1-8B-Instruct": "Meta Llama 3.1",
    "meta-llama/Meta-Llama-3.1-8B-Instruct": "Meta Llama 3.1",
    "Meta Llama-4-Maverick-17B-128E-Instruct": "Llama 4 Maverick",
    "Llama-4-Maverick-17B-128E-Instruct": "Llama 4 Maverick",
    "meta-llama/Llama-4-Maverick-17B-128E-Instruct": "Llama 4 Maverick",
}


def _model_to_dict(item):
    if item is None:
        return None
    if hasattr(item, "model_dump"):
        return item.model_dump()
    return item.dict()


def _normalize_channel_name(value: Optional[str]) -> str:
    text = str(value or "").strip()
    if not text:
        return "TEXT"
    upper = text.upper()
    if upper in CHANNEL_NAMES:
        return upper
    return "VOICE" if text.lower() == "voice" else "TEXT"


def _normalize_channel_type(value: Optional[str], channel_name: Optional[str] = None) -> str:
    normalized_channel_name = _normalize_channel_name(channel_name)
    default_type = "TRANSACTIONAL" if normalized_channel_name == "VOICE" else "UTILITY"

    text = str(value or "").strip()
    if not text:
        return default_type

    upper = text.upper()

    if normalized_channel_name == "VOICE":
        if upper in VOICE_CHANNEL_TYPES:
            return upper
        if upper == "MARKETING":
            return "PROMOTIONAL"
        if upper in {"UTILITY", "AUTHENTICATION"}:
            return "TRANSACTIONAL"
        if text in {"1", "3"}:
            return "TRANSACTIONAL"
        if text == "2":
            return "PROMOTIONAL"
    else:
        if upper in TEXT_CHANNEL_TYPES:
            return upper
        if upper == "PROMOTIONAL":
            return "MARKETING"
        if upper == "TRANSACTIONAL":
            return "UTILITY"
        if text == "1":
            return "UTILITY"
        if text == "2":
            return "MARKETING"
        if text == "3":
            return "AUTHENTICATION"

    return default_type


def _product_id_from_channel_name(value: Optional[str]) -> int:
    normalized = _normalize_channel_name(value)
    return int(CHANNEL_PRODUCT_IDS.get(normalized, CHANNEL_PRODUCT_IDS["TEXT"]))


def _normalize_model_selection(value: Optional[str]) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    if text in MODEL_BACKENDS:
        return text
    if text in MODEL_SELECTION_ALIASES:
        return MODEL_SELECTION_ALIASES[text]

    lowered = text.lower()
    for key in MODEL_BACKENDS.keys():
        if lowered == str(key).lower():
            return key
    for alias, canonical in MODEL_SELECTION_ALIASES.items():
        if lowered == alias.lower():
            return canonical
    return None


def _normalize_model_selection_strict(value: Optional[str]) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None

    normalized = _normalize_model_selection(text)
    if normalized is None:
        allowed = ", ".join(sorted(MODEL_BACKENDS.keys()))
        raise HTTPException(
            status_code=400,
            detail=f"Invalid model_selection '{text}'. Allowed values: {allowed}",
        )
    return normalized


def _resolve_query_text(request_payload: QueryRequest) -> str:
    return str((request_payload.question or request_payload.query or "")).strip()


def _normalize_uuid(value: Optional[str], field_name: str, *, required: bool = False) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        if required:
            raise HTTPException(status_code=400, detail=f"{field_name} is required")
        return None
    try:
        return str(uuid.UUID(text))
    except Exception:
        raise HTTPException(status_code=400, detail=f"{field_name} must be a valid UUID")


def _resolve_model_selection_for_agent(id: Optional[str]) -> Optional[str]:
    if not id:
        return None
    agent = get_agent(id)
    if not agent:
        return None
    return _normalize_model_selection(agent.get("model_selection"))


def _token_owner_id_from_api_key(api_key: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(api_key, dict):
        return None
    token = str(api_key.get("token") or "").strip()
    if not token:
        return None
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"apikey:{digest}"


def _legacy_user_id_from_api_key(api_key: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(api_key, dict):
        return None

    direct = str(api_key.get("x_user_id") or "").strip()
    if direct:
        return direct

    profile = api_key.get("profile")
    if isinstance(profile, dict):
        for key in ("x_user_id", "user_id", "id", "sub", "uid"):
            value = str(profile.get(key) or "").strip()
            if value:
                return value
    return None


def _auth_identity_candidates(api_key: Optional[Dict[str, Any]]) -> set[str]:
    candidates: set[str] = set()

    token_owner = _token_owner_id_from_api_key(api_key)
    if token_owner:
        candidates.add(token_owner)

    legacy_user_id = _legacy_user_id_from_api_key(api_key)
    if legacy_user_id:
        candidates.add(legacy_user_id)
        candidates.add(f"user:{legacy_user_id}")

    return candidates


def _auth_user_id_from_api_key(api_key: Optional[Dict[str, Any]]) -> Optional[str]:
    # Ownership identity is API key based.
    return _token_owner_id_from_api_key(api_key) or _legacy_user_id_from_api_key(api_key)


def _require_auth_user_id(api_key: Optional[Dict[str, Any]]) -> str:
    user_id = _auth_user_id_from_api_key(api_key)
    if not user_id:
        raise HTTPException(
            status_code=403,
            detail="Unable to use this agent. It was not created by this user.",
        )
    return user_id


def _agent_owner_user_id(agent: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(agent, dict):
        return None
    owner = str(agent.get("user_id") or "").strip()
    return owner or None


def _agent_owner_token_id(agent: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(agent, dict):
        return None
    metadata = agent.get("metadata")
    if not isinstance(metadata, dict):
        return None
    token_id = str(metadata.get("owner_token_id") or "").strip()
    return token_id or None


def _can_access_agent(agent: Optional[Dict[str, Any]], api_key: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(agent, dict):
        return False

    token_owner = _token_owner_id_from_api_key(api_key)
    owner_token = _agent_owner_token_id(agent)
    if owner_token:
        return bool(token_owner and owner_token == token_owner)

    owner_user_id = _agent_owner_user_id(agent)
    candidates = _auth_identity_candidates(api_key)
    return bool(owner_user_id and owner_user_id in candidates)


def _require_agent_access(agent_id: str, api_key: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    agent = get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    _require_auth_user_id(api_key)
    if not _can_access_agent(agent, api_key):
        raise HTTPException(
            status_code=403,
            detail="Unable to use this agent. It was not created by this user.",
        )
    return agent


VOICE_PROFILE_CHANNEL_PREFIX = "omnicortex_voice_profile"
DEFAULT_FREESWITCH_VERTO_WS_URL = "wss://172.22.0.2:7443"


def _voice_profile_channel_name(api_key: Optional[Dict[str, Any]]) -> str:
    owner_id = _require_auth_user_id(api_key)
    return f"{VOICE_PROFILE_CHANNEL_PREFIX}::{owner_id}"


def _sanitize_voice_profile_payload(payload: Dict[str, Any], *, keep_existing_api_key: Optional[str] = None) -> Dict[str, Any]:
    raw_api_key = str(payload.get("api_key") or "").strip()
    selected_agent_id = _normalize_uuid(payload.get("selected_agent_id"), "selected_agent_id", required=False)
    context_query = str(payload.get("context_query") or "").strip()
    voice_prompt = str(payload.get("voice_prompt") or "").strip() or "NATF0.pt"
    extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}

    if len(context_query) > 1000:
        context_query = context_query[:1000].strip()
    if len(voice_prompt) > 120:
        voice_prompt = voice_prompt[:120].strip()

    # Empty string means "keep existing" to avoid accidental token deletion from partial saves.
    final_api_key = raw_api_key if raw_api_key else (keep_existing_api_key or "")

    return {
        "api_key": final_api_key,
        "selected_agent_id": selected_agent_id,
        "context_query": context_query,
        "voice_prompt": voice_prompt,
        "extra": extra,
    }


def _public_voice_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    clean = dict(profile or {})
    token = str(clean.get("api_key") or "")
    clean["has_api_key"] = bool(token)
    clean["api_key_preview"] = (token[:6] + "..." + token[-4:]) if len(token) > 10 else ("***" if token else "")
    return clean


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_verto_ws_url(override: Optional[str] = None) -> str:
    url = str(override or "").strip()
    if not url:
        url = str(os.getenv("FREESWITCH_VERTO_WS_URL") or "").strip()
    if not url:
        url = DEFAULT_FREESWITCH_VERTO_WS_URL
    if not (url.startswith("ws://") or url.startswith("wss://")):
        raise HTTPException(status_code=400, detail="FREESWITCH_VERTO_WS_URL must start with ws:// or wss://")
    return url


def _verto_ssl_context(url: str) -> tuple[Optional[ssl.SSLContext], bool]:
    ssl_verify = _env_bool("FREESWITCH_VERTO_SSL_VERIFY", default=False)
    if not url.startswith("wss://"):
        return None, ssl_verify
    if ssl_verify:
        return None, True
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx, False


def _get_document_agent_id(document_id: int) -> Optional[str]:
    from core.database import Document, SessionLocal

    db = SessionLocal()
    try:
        row = db.query(Document.agent_id).filter(Document.id == document_id).first()
        return row[0] if row and row[0] else None
    finally:
        db.close()


def _merge_unique_str_lists(*values: Optional[List[str]]) -> Optional[List[str]]:
    merged: List[str] = []
    seen = set()
    for bucket in values:
        if not bucket:
            continue
        for value in bucket:
            text = str(value).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            merged.append(text)
    return merged or None


def _selector_key(value: Optional[str]) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"[^a-z0-9]+", "", text)


def _normalize_agent_type(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return AGENT_TYPE_ALIASES.get(_selector_key(text), text)


def _normalize_subagent_type(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none"}:
        return None
    return BUSINESS_SUBAGENT_CANONICAL.get(_selector_key(text), text)


def _normalize_role_type(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    key = _selector_key(text)
    if key in PERSONAL_ROLE_CANONICAL:
        return PERSONAL_ROLE_CANONICAL[key]
    if key in BUSINESS_SUBAGENT_CANONICAL:
        return BUSINESS_SUBAGENT_CANONICAL[key]
    return text


def _auto_prompt_source(agent_type: Optional[str], subagent_type: Optional[str], role_type: Optional[str]) -> Optional[str]:
    for candidate in (subagent_type, role_type):
        key = _selector_key(candidate)
        if key in BUSINESS_PROMPT_BY_SUBAGENT:
            return BUSINESS_PROMPT_BY_SUBAGENT[key]
        if key in PERSONAL_PROMPT_BY_ROLE:
            return PERSONAL_PROMPT_BY_ROLE[key]

    agent_key = _selector_key(agent_type)
    if agent_key in {"personalassistant", "personal"}:
        return PERSONAL_PROMPT_BY_ROLE["personalassistant"]
    if agent_key in {"businessagent", "business"}:
        return BUSINESS_PROMPT_BY_SUBAGENT["retailecommerce"]
    return None


def _extract_prompt_text(items: Optional[List[Union[str, ConversationStarterItem]]]) -> Optional[List[str]]:
    if not items:
        return None
    prompts: List[str] = []
    for item in items:
        if isinstance(item, str):
            text = item.strip()
            if text:
                prompts.append(text)
            continue
        row = _model_to_dict(item) or {}
        prompt = (row.get("prompt") or "").strip()
        if prompt:
            prompts.append(prompt)
    return prompts or None


def _extract_conversation_items(items: Optional[List[Union[str, ConversationStarterItem]]]) -> Optional[List[Dict[str, str]]]:
    if not items:
        return None

    cleaned_items: List[Dict[str, str]] = []
    for item in items:
        if isinstance(item, str):
            text = item.strip()
            if text:
                cleaned_items.append({"prompt": text})
            continue
        row = _model_to_dict(item) or {}
        cleaned: Dict[str, str] = {}
        for key in ("icon", "label", "prompt"):
            value = row.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                cleaned[key] = text
        if cleaned:
            cleaned_items.append(cleaned)

    return cleaned_items or None


def _resolve_system_prompt(value: Optional[str]) -> Optional[str]:
    if not value:
        return value
    candidate = Path(value)
    if not candidate.is_file():
        return value
    try:
        content = candidate.read_text(encoding="utf-8").strip()
        return content or value
    except Exception as e:
        logging.warning(f"Failed reading system_prompt file '{value}': {e}")
        return value


def _looks_like_prompt_path(value: Optional[str]) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    if not text or "\n" in text or "\r" in text:
        return False
    suffix = Path(text).suffix.lower()
    if suffix not in {".json", ".txt", ".md", ".yaml", ".yml", ".prompt"}:
        return False
    return ("/" in text) or ("\\" in text) or len(text) <= 120


def _extract_system_prompt_source(value: Optional[str]) -> Optional[str]:
    if not _looks_like_prompt_path(value):
        return None
    return str(value).strip()


def _system_prompt_filename(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    return Path(text).name


def _compact_text(value: Optional[str], max_chars: int = 220) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def _system_prompt_for_response(agent: Dict[str, Any]) -> Optional[str]:
    source = agent.get("system_prompt_source")
    if source:
        return _system_prompt_filename(source)
    raw = agent.get("system_prompt")
    if _looks_like_prompt_path(raw):
        return _system_prompt_filename(raw)
    return _compact_text(raw)


def _system_prompt_for_integration(agent: Dict[str, Any]) -> str:
    """Return full prompt text for integrations (do not compact to filename/preview)."""
    raw = str(agent.get("system_prompt") or "").strip()
    if raw and _looks_like_prompt_path(raw):
        raw = str(_resolve_system_prompt(raw) or "").strip()
    if raw:
        return raw

    source = str(agent.get("system_prompt_source") or "").strip()
    if source:
        resolved = str(_resolve_system_prompt(source) or "").strip()
        if resolved and not _looks_like_prompt_path(resolved):
            return resolved
    return ""


def _normalize_agent_create_payload(agent_request: AgentCreate) -> Dict[str, Any]:
    name = ((agent_request.name or agent_request.agent_name or agent_request.agentname) or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name (or agent_name/agentname) is required")

    incoming_id = agent_request.id
    if incoming_id is None:
        raise HTTPException(status_code=400, detail="id is required")
    incoming_id = str(incoming_id).strip()
    if not incoming_id:
        raise HTTPException(status_code=400, detail="id is required")

    document_data = agent_request.document_data
    legacy_doc_urls = []
    if document_data and document_data.documents_text:
        legacy_doc_urls = [doc.url for doc in document_data.documents_text if doc.url]

    urls = _merge_unique_str_lists(agent_request.urls, agent_request.website_data, legacy_doc_urls)
    image_urls = _merge_unique_str_lists(
        agent_request.image_urls,
        document_data.image_urls if document_data else None,
    )
    video_urls = _merge_unique_str_lists(
        agent_request.video_urls,
        document_data.video_urls if document_data else None,
    )

    conversation_starters = _extract_prompt_text(agent_request.conversation_starters)
    conversation_end = _extract_conversation_items(agent_request.conversation_end)
    normalized_agent_type = _normalize_agent_type(agent_request.agent_type)
    normalized_subagent_type = _normalize_subagent_type(agent_request.subagent_type)
    normalized_role_type = _normalize_role_type(agent_request.role_type)
    normalized_industry = None
    if agent_request.industry is not None:
        industry_text = str(agent_request.industry).strip()
        normalized_industry = _normalize_subagent_type(industry_text) if industry_text else None
    if not normalized_industry and _selector_key(normalized_agent_type) in {"businessagent", "business"}:
        normalized_industry = normalized_subagent_type

    system_prompt_source = _extract_system_prompt_source(agent_request.system_prompt)
    system_prompt = _resolve_system_prompt(agent_request.system_prompt)
    if not agent_request.system_prompt:
        auto_source = _auto_prompt_source(
            normalized_agent_type,
            normalized_subagent_type,
            normalized_role_type,
        )
        if auto_source:
            system_prompt_source = auto_source
            system_prompt = _resolve_system_prompt(auto_source)
    description = (
        (agent_request.description or "").strip()
        or (agent_request.instruction or "").strip()
    )

    scraped_data = [_model_to_dict(row) for row in agent_request.scraped_data] if agent_request.scraped_data else None

    return {
        "id": incoming_id,
        "name": name,
        "description": description,
        "system_prompt": system_prompt,
        "system_prompt_source": system_prompt_source,
        "urls": urls,
        "image_urls": image_urls,
        "video_urls": video_urls,
        "conversation_starters": conversation_starters,
        "scraped_data": scraped_data,
        "logic": agent_request.logic,
        "conversation_end": conversation_end,
        "agent_type": normalized_agent_type,
        "subagent_type": normalized_subagent_type,
        "role_type": normalized_role_type,
        "industry": normalized_industry,
        "model_selection": _normalize_model_selection_strict(agent_request.model_selection),
    }


def _normalize_agent_update_payload(agent_request: AgentUpdate) -> Dict[str, Any]:
    document_data = agent_request.document_data
    legacy_doc_urls = []
    if document_data and document_data.documents_text:
        legacy_doc_urls = [doc.url for doc in document_data.documents_text if doc.url]

    urls_provided = any([
        agent_request.urls is not None,
        agent_request.website_data is not None,
        bool(legacy_doc_urls),
    ])
    image_urls_provided = any([
        agent_request.image_urls is not None,
        bool(document_data and document_data.image_urls is not None),
    ])
    video_urls_provided = any([
        agent_request.video_urls is not None,
        bool(document_data and document_data.video_urls is not None),
    ])

    urls_merged = _merge_unique_str_lists(
        agent_request.urls,
        agent_request.website_data,
        legacy_doc_urls,
    ) if urls_provided else None
    urls = urls_merged if urls_merged is not None else ([] if urls_provided else None)

    image_urls_merged = _merge_unique_str_lists(
        agent_request.image_urls,
        document_data.image_urls if document_data else None,
    ) if image_urls_provided else None
    image_urls = image_urls_merged if image_urls_merged is not None else ([] if image_urls_provided else None)

    video_urls_merged = _merge_unique_str_lists(
        agent_request.video_urls,
        document_data.video_urls if document_data else None,
    ) if video_urls_provided else None
    video_urls = video_urls_merged if video_urls_merged is not None else ([] if video_urls_provided else None)

    conversation_starters_merged = (
        _extract_prompt_text(agent_request.conversation_starters)
        if agent_request.conversation_starters is not None else None
    )
    conversation_starters = (
        conversation_starters_merged
        if conversation_starters_merged is not None
        else ([] if agent_request.conversation_starters is not None else None)
    )

    conversation_end_merged = (
        _extract_conversation_items(agent_request.conversation_end)
        if agent_request.conversation_end is not None else None
    )
    conversation_end = (
        conversation_end_merged
        if conversation_end_merged is not None
        else ([] if agent_request.conversation_end is not None else None)
    )

    name = None
    if agent_request.name is not None or agent_request.agent_name is not None or agent_request.agentname is not None:
        name = str((agent_request.name or agent_request.agent_name or agent_request.agentname or "")).strip() or None

    description = None
    if agent_request.description is not None:
        description = agent_request.description
    elif agent_request.instruction is not None:
        description = agent_request.instruction

    normalized_agent_type = (
        _normalize_agent_type(agent_request.agent_type)
        if agent_request.agent_type is not None
        else None
    )
    normalized_subagent_type = (
        _normalize_subagent_type(agent_request.subagent_type)
        if agent_request.subagent_type is not None
        else None
    )
    normalized_role_type = (
        _normalize_role_type(agent_request.role_type)
        if agent_request.role_type is not None
        else None
    )
    normalized_industry = None
    if agent_request.industry is not None:
        industry_text = str(agent_request.industry).strip()
        normalized_industry = _normalize_subagent_type(industry_text) if industry_text else None
    if (
        normalized_industry is None
        and normalized_subagent_type is not None
        and _selector_key(normalized_agent_type) in {"businessagent", "business"}
    ):
        normalized_industry = normalized_subagent_type

    system_prompt = (
        _resolve_system_prompt(agent_request.system_prompt)
        if agent_request.system_prompt is not None else None
    )
    system_prompt_source = (
        _extract_system_prompt_source(agent_request.system_prompt)
        if agent_request.system_prompt is not None else None
    )
    if agent_request.system_prompt is None and any(
        value is not None
        for value in (normalized_agent_type, normalized_subagent_type, normalized_role_type)
    ):
        auto_source = _auto_prompt_source(
            normalized_agent_type,
            normalized_subagent_type,
            normalized_role_type,
        )
        if auto_source:
            system_prompt_source = auto_source
            system_prompt = _resolve_system_prompt(auto_source)
    scraped_data = (
        [_model_to_dict(row) for row in agent_request.scraped_data]
        if agent_request.scraped_data is not None else None
    )

    return {
        "name": name,
        "description": description,
        "system_prompt": system_prompt,
        "system_prompt_source": system_prompt_source,
        "urls": urls,
        "image_urls": image_urls,
        "video_urls": video_urls,
        "conversation_starters": conversation_starters,
        "scraped_data": scraped_data,
        "logic": agent_request.logic,
        "conversation_end": conversation_end,
        "agent_type": normalized_agent_type,
        "subagent_type": normalized_subagent_type,
        "role_type": normalized_role_type,
        "industry": normalized_industry,
        "model_selection": _normalize_model_selection_strict(agent_request.model_selection),
    }


def _normalize_role_and_industry(
    role_type: Optional[str],
    industry: Optional[str],
    *,
    agent_type: Optional[str] = None,
    subagent_type: Optional[str] = None,
) -> tuple:
    normalized_subagent = _normalize_subagent_type(subagent_type) if subagent_type is not None else None
    normalized_industry = None
    if industry is not None:
        industry_text = str(industry).strip()
        normalized_industry = _normalize_subagent_type(industry_text) if industry_text else None

    normalized_role = _normalize_role_type(role_type) if role_type is not None else None
    agent_key = _selector_key(agent_type)

    # Backward compatibility for legacy category role_type values.
    role_key = _selector_key(normalized_role)
    if role_key in {"personal"}:
        normalized_role = "PersonalAssistant"
        role_key = _selector_key(normalized_role)
    elif role_key in {"business"}:
        normalized_role = normalized_subagent or normalized_industry or "BusinessAgent"
        role_key = _selector_key(normalized_role)
    elif role_key in {"knowledge"}:
        normalized_role = "knowledge"
        role_key = _selector_key(normalized_role)

    # If role_type is omitted, infer a sensible default from agent_type/subagent_type.
    if normalized_role is None:
        if agent_key in {"personalassistant", "personal"}:
            normalized_role = "PersonalAssistant"
        elif agent_key in {"businessagent", "business"} and normalized_subagent:
            normalized_role = normalized_subagent

    # For business-style requests, keep industry aligned with subagent_type.
    if normalized_industry is None:
        business_role = _selector_key(normalized_role) in BUSINESS_SUBAGENT_CANONICAL
        business_agent = agent_key in {"businessagent", "business"}
        if business_role or business_agent:
            normalized_industry = normalized_subagent

    return normalized_role, normalized_industry


def _validate_list_limits(agent_payload=None, *, urls=None, conversation_starters=None, image_urls=None, video_urls=None):
    resolved_urls = urls
    resolved_conversation = conversation_starters
    resolved_images = image_urls
    resolved_videos = video_urls

    if agent_payload is not None:
        resolved_urls = resolved_urls if resolved_urls is not None else (
            getattr(agent_payload, "urls", None) or getattr(agent_payload, "website_data", None)
        )
        resolved_conversation = resolved_conversation if resolved_conversation is not None else getattr(agent_payload, "conversation_starters", None)
        resolved_images = resolved_images if resolved_images is not None else getattr(agent_payload, "image_urls", None)
        resolved_videos = resolved_videos if resolved_videos is not None else getattr(agent_payload, "video_urls", None)
        document_data = getattr(agent_payload, "document_data", None)
        if document_data:
            if resolved_images is None:
                resolved_images = getattr(document_data, "image_urls", None)
            if resolved_videos is None:
                resolved_videos = getattr(document_data, "video_urls", None)

    if resolved_urls and len(resolved_urls) > MAX_URLS:
        raise HTTPException(status_code=400, detail=f"urls limit exceeded ({MAX_URLS})")
    if resolved_conversation and len(resolved_conversation) > MAX_CONVERSATION_STARTERS:
        raise HTTPException(
            status_code=400,
            detail=f"conversation_starters limit exceeded ({MAX_CONVERSATION_STARTERS})",
        )
    if resolved_images and len(resolved_images) > MAX_MEDIA_URLS:
        raise HTTPException(status_code=400, detail=f"image_urls limit exceeded ({MAX_MEDIA_URLS})")
    if resolved_videos and len(resolved_videos) > MAX_MEDIA_URLS:
        raise HTTPException(status_code=400, detail=f"video_urls limit exceeded ({MAX_MEDIA_URLS})")


def _resolve_agent_profile_kind(agent_type: Optional[str], role_type: Optional[str]) -> Optional[str]:
    """Return one of: blank | personal | business | None."""
    agent_key = _selector_key(agent_type)
    if agent_key in {"blankagent", "blank"}:
        return "blank"
    if agent_key in {"personalassistant", "personal"}:
        return "personal"
    if agent_key in {"businessagent", "business"}:
        return "business"

    role_key = _selector_key(role_type)
    if role_key in PERSONAL_ROLE_CANONICAL:
        return "personal"
    if role_key in BUSINESS_SUBAGENT_CANONICAL:
        return "business"
    return None


def _has_minimum_knowledge_source(
    *,
    urls: Optional[List[str]],
    file_paths: Optional[List[str]],
    documents_text: Optional[List[AgentDocumentText]],
    scraped_data: Optional[List[ScrapedContent]],
) -> bool:
    if urls:
        return True
    if file_paths:
        return any(str(path).strip() for path in file_paths)
    if documents_text:
        return any((str(doc.text or "").strip() or str(doc.filename or "").strip()) for doc in documents_text)
    if scraped_data:
        return any(str(row.text or "").strip() for row in scraped_data)
    return False


def _validate_create_agent_requirements(
    *,
    agent_type: Optional[str],
    role_type: Optional[str],
    system_prompt: Optional[str],
    urls: Optional[List[str]],
    file_paths: Optional[List[str]],
    documents_text: Optional[List[AgentDocumentText]],
    scraped_data: Optional[List[ScrapedContent]],
) -> None:
    profile_kind = _resolve_agent_profile_kind(agent_type, role_type)
    if profile_kind not in {"blank", "personal", "business"}:
        return

    has_knowledge = _has_minimum_knowledge_source(
        urls=urls,
        file_paths=file_paths,
        documents_text=documents_text,
        scraped_data=scraped_data,
    )
    if not has_knowledge:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{profile_kind.title()} agent requires at least one knowledge source: "
                "a website URL or a document input."
            ),
        )

    if profile_kind in {"personal", "business"}:
        if not str(system_prompt or "").strip():
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{profile_kind.title()} agent requires a non-empty system_prompt."
                ),
            )


def _ingest_documents_text(documents_text: Optional[List[AgentDocumentText]], agent_id: str):
    if not documents_text:
        return None

    blocks = []
    for idx, doc in enumerate(documents_text, start=1):
        filename = (doc.filename or f"document_{idx}.txt").strip()
        text = (doc.text or "").strip()
        if not text:
            continue
        blocks.append(f"[Document: {filename}]\n{text}")

    if blocks:
        return process_documents(text_input="\n\n".join(blocks), agent_id=agent_id)
    return None


def _ingest_scraped_data(scraped_data: Optional[List[ScrapedContent]], agent_id: str):
    if not scraped_data:
        return None

    blocks = []
    for idx, row in enumerate(scraped_data, start=1):
        source_url = (row.url or f"scraped_source_{idx}").strip()
        text = (row.text or "").strip()
        if not text:
            continue
        blocks.append(f"Source URL: {source_url}\n\n{text}")

    if blocks:
        return process_documents(text_input="\n\n".join(blocks), agent_id=agent_id)
    return None


def generate_agent_webhook_url(agent_name: str, agent_id: str) -> Optional[str]:
    """Return configured outbound webhook URL for agent lifecycle events."""
    webhook_url = (os.getenv("AGENT_READY_WEBHOOK_URL") or "").strip()
    return webhook_url or None


def _emit_agent_ready_webhook(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Send outbound webhook for agent creation lifecycle."""
    webhook_url = (os.getenv("AGENT_READY_WEBHOOK_URL") or "").strip()
    if not webhook_url:
        return {"sent": False, "reason": "AGENT_READY_WEBHOOK_URL not configured"}

    try:
        import requests

        response = requests.post(webhook_url, json=payload, timeout=8)
        return {"sent": response.status_code < 400, "status_code": response.status_code}
    except Exception as exc:
        return {"sent": False, "error": str(exc)}


def agent_to_response(agent: dict, base_url: str = None) -> AgentResponse:
    """Convert agent dict to response with webhook_url"""
    webhook_path = generate_agent_webhook_url(agent['name'], agent['id'])
    full_url = webhook_path
    return AgentResponse(
        id=agent['id'],
        name=agent['name'],
        description=agent.get('description'),
        system_prompt=_system_prompt_for_response(agent),
        role_type=agent.get('role_type'),
        industry=agent.get('industry'),
        urls=agent.get('urls'),
        conversation_starters=agent.get('conversation_starters'),
        image_urls=agent.get('image_urls'),
        video_urls=agent.get('video_urls'),
        scraped_data=agent.get('scraped_data'),
        logic=agent.get('logic'),
        conversation_end=agent.get('conversation_end'),
        agent_type=agent.get('agent_type'),
        subagent_type=agent.get('subagent_type'),
        model_selection=agent.get('model_selection'),
        document_count=agent.get('document_count', 0),
        message_count=agent.get('message_count', 0),
        webhook_url=full_url
    )


@app.get("/agents", response_model=List[AgentListItem])
async def list_agents(api_key: ApiKey = Depends(get_api_key)):
    """List all agents (minimal fields)."""
    _require_auth_user_id(api_key)
    agents = [
        a for a in get_all_agents()
        if _can_access_agent(a, api_key)
    ]

    return [
        AgentListItem(
            id=a["id"],
            agent_type=(a.get("agent_type") or a.get("role_type")),
            agent_name=a["name"],
        )
        for a in agents
    ]


@app.get("/agents/{agent_id}", response_model=AgentResponse)
async def get_agent_detail(agent_id: str, request: Request, api_key: ApiKey = Depends(get_api_key)):
    """Get agent details with webhook URL"""
    agent = _require_agent_access(agent_id, api_key)
    base_url = str(request.base_url).rstrip("/")
    return agent_to_response(agent, base_url)


@app.get("/agents/{agent_id}/system-prompt", response_model=AgentSystemPromptResponse)
async def get_agent_system_prompt(agent_id: str, api_key: ApiKey = Depends(get_api_key)):
    """Return full resolved system prompt text for integrations (PersonaPlex/voice)."""
    agent = _require_agent_access(agent_id, api_key)
    full_prompt = _system_prompt_for_integration(agent).strip()
    if not full_prompt:
        full_prompt = "You are a helpful assistant."
    source = str(agent.get("system_prompt_source") or "").strip() or None
    return AgentSystemPromptResponse(
        agent_id=agent_id,
        system_prompt=full_prompt,
        source=source,
    )


@app.post("/agents", response_model=AgentCreateResponse)
async def create_new_agent(agent_request: AgentCreate, request: Request, background_tasks: BackgroundTasks, api_key: ApiKey = Depends(get_api_key)):
    """Create a new agent (optionally from local files)"""
    try:
        vector_chunks_total = 0
        parent_chunks_total = 0

        def _accumulate_ingest_metrics(result: Optional[Dict[str, Any]]) -> None:
            nonlocal vector_chunks_total, parent_chunks_total
            if not result:
                return
            vector_chunks_total += int(result.get("vector_chunks") or 0)
            parent_chunks_total += int(result.get("parent_chunks") or 0)

        owner_token_id = _token_owner_id_from_api_key(api_key)
        if not owner_token_id:
            _require_auth_user_id(api_key)
            raise HTTPException(
                status_code=403,
                detail="Unable to use this agent. It was not created by this user.",
            )
        request_header_user_id = str(request.headers.get("x-user-id") or "").strip()
        creator_user_id = request_header_user_id or _legacy_user_id_from_api_key(api_key)

        normalized = _normalize_agent_create_payload(agent_request)
        _validate_list_limits(
            urls=normalized["urls"],
            conversation_starters=normalized["conversation_starters"],
            image_urls=normalized["image_urls"],
            video_urls=normalized["video_urls"],
        )
        role_type, industry = _normalize_role_and_industry(
            normalized["role_type"],
            normalized["industry"],
            agent_type=normalized["agent_type"],
            subagent_type=normalized["subagent_type"],
        )
        _validate_create_agent_requirements(
            agent_type=normalized["agent_type"],
            role_type=role_type,
            system_prompt=agent_request.system_prompt,
            urls=normalized["urls"],
            file_paths=agent_request.file_paths,
            documents_text=agent_request.documents_text,
            scraped_data=agent_request.scraped_data,
        )
        normalized_id = _normalize_uuid(normalized["id"], "id", required=True)

        created_id = create_agent(
            id=normalized_id,
            name=normalized["name"],
            description=normalized["description"],
            system_prompt=normalized["system_prompt"],
            system_prompt_source=normalized["system_prompt_source"],
            role_type=role_type,
            industry=industry,
            urls=normalized["urls"],
            conversation_starters=normalized["conversation_starters"],
            image_urls=normalized["image_urls"],
            video_urls=normalized["video_urls"],
            scraped_data=normalized["scraped_data"],
            logic=normalized["logic"],
            conversation_end=normalized["conversation_end"],
            agent_type=normalized["agent_type"],
            subagent_type=normalized["subagent_type"],
            model_selection=normalized["model_selection"],
            user_id=creator_user_id,
            owner_token_id=owner_token_id,
        )
        
        # Handle Local File Paths (for bulk creation/scripting)
        if agent_request.file_paths:
            file_objs = []
            try:
                for path in agent_request.file_paths:
                    if os.path.exists(path):
                        f = open(path, "rb")
                        # Emulate UploadFile behavior if needed, but 'read()' is sufficient for loader
                        # We might need to manually set .name for document_loader to infer extension
                        if not hasattr(f, 'name'): 
                             # 'name' is usually present on file objects opened with open()
                             pass
                        file_objs.append(f)
                    else:
                        print(f"⚠️ Warning: File not found {path}")
                
                if file_objs:
                    _accumulate_ingest_metrics(
                        process_documents(files=file_objs, agent_id=created_id)
                    )
            except Exception as doc_err:
                print(f"❌ Failed to process initial documents: {doc_err}")
                # Don't fail the request, just log it? Or maybe fail? 
                # Better to warn since agent is created.
            finally:
                for f in file_objs:
                    try:
                        f.close()
                    except:
                        pass

        # Handle direct extracted text payloads (document words/text)
        if agent_request.documents_text:
            _accumulate_ingest_metrics(_ingest_documents_text(agent_request.documents_text, created_id))

        # Handle pre-scraped web content payload
        if agent_request.scraped_data:
            _accumulate_ingest_metrics(_ingest_scraped_data(agent_request.scraped_data, created_id))
        
        # Trigger URL Scraping in Background
        if normalized["urls"]:
            background_tasks.add_task(process_urls, normalized["urls"], created_id)

        # Agent lifecycle analytics row in ClickHouse.
        try:
            from core.clickhouse import log_agent_event_to_clickhouse

            log_agent_event_to_clickhouse(
                agent_id=created_id,
                status="Active",
                agent_name=normalized["name"],
                user_id=creator_user_id,
                created_at=datetime.datetime.utcnow(),
                deleted_at=None,
                model_selection=normalized["model_selection"],
                role_type=role_type,
                subagent_type=industry,
                vector_store=f"omni_agent_{created_id}",
                vector_chunks=vector_chunks_total,
                parent_chunks=parent_chunks_total,
                payload={
                    "agent_type": normalized["agent_type"],
                    "subagent_type": normalized["subagent_type"],
                },
            )
        except Exception:
            pass

        # Optional outbound lifecycle webhook for successful agent creation.
        try:
            webhook_payload = {
                "event": "agent.ready",
                "status": "Agent Ready",
                "agent_id": created_id,
                "agent_name": normalized["name"],
                "vector_store": f"omni_agent_{created_id}",
                "vector_chunks": vector_chunks_total,
                "parent_chunks": parent_chunks_total,
                "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            }
            _emit_agent_ready_webhook(webhook_payload)
        except Exception:
            pass

        agent = get_agent(created_id)
        if not agent:
            raise HTTPException(status_code=500, detail="Failed to load created agent")
        try:
            sync_agent_config(
                created_id,
                event_type="create",
                event_payload=normalized,
            )
        except Exception as cfg_exc:
            logging.warning(f"Agent config sync failed on create for {created_id}: {cfg_exc}")
        return AgentCreateResponse(
            status="created",
            id=agent["id"],
            agent_name=agent["name"],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.put("/agents/{agent_id}", response_model=AgentResponse)
async def update_agent_endpoint(
    agent_id: str,
    agent_request: AgentUpdate,
    request: Request,
    background_tasks: BackgroundTasks,
    api_key: ApiKey = Depends(get_api_key),
):
    """Update an existing agent, including config and optional data ingestion."""
    current = _require_agent_access(agent_id, api_key)
    vector_chunks_total = 0
    parent_chunks_total = 0

    def _accumulate_ingest_metrics(result: Optional[Dict[str, Any]]) -> None:
        nonlocal vector_chunks_total, parent_chunks_total
        if not result:
            return
        vector_chunks_total += int(result.get("vector_chunks") or 0)
        parent_chunks_total += int(result.get("parent_chunks") or 0)

    _require_auth_user_id(api_key)
    audit_user_id = _agent_owner_user_id(current)

    normalized = _normalize_agent_update_payload(agent_request)
    _validate_list_limits(
        urls=normalized["urls"],
        conversation_starters=normalized["conversation_starters"],
        image_urls=normalized["image_urls"],
        video_urls=normalized["video_urls"],
    )

    effective_agent_type = (
        normalized["agent_type"]
        if normalized["agent_type"] is not None
        else current.get("agent_type")
    )
    effective_subagent_type = (
        normalized["subagent_type"]
        if normalized["subagent_type"] is not None
        else current.get("subagent_type")
    )
    role_type, industry = _normalize_role_and_industry(
        normalized["role_type"],
        normalized["industry"],
        agent_type=effective_agent_type,
        subagent_type=effective_subagent_type,
    )
    industry_update = None
    if normalized["industry"] is not None:
        industry_update = industry
    elif (
        normalized["subagent_type"] is not None
        and _selector_key(effective_agent_type) in {"businessagent", "business"}
    ):
        industry_update = industry

    success = update_agent(
        agent_id=agent_id,
        name=normalized["name"],
        description=normalized["description"],
        system_prompt=normalized["system_prompt"],
        system_prompt_source=normalized["system_prompt_source"],
        role_type=role_type if normalized["role_type"] is not None else None,
        industry=industry_update,
        urls=normalized["urls"],
        conversation_starters=normalized["conversation_starters"],
        image_urls=normalized["image_urls"],
        video_urls=normalized["video_urls"],
        scraped_data=normalized["scraped_data"],
        logic=normalized["logic"],
        conversation_end=normalized["conversation_end"],
        agent_type=normalized["agent_type"],
        subagent_type=normalized["subagent_type"],
        model_selection=normalized["model_selection"],
        user_id=None,
    )
    if not success:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Optional local-file ingestion (legacy compatibility)
    if agent_request.file_paths:
        file_objs = []
        try:
            for path in agent_request.file_paths:
                if os.path.exists(path):
                    file_objs.append(open(path, "rb"))
                else:
                    logging.warning(f"File path not found during agent update: {path}")
            if file_objs:
                _accumulate_ingest_metrics(process_documents(files=file_objs, agent_id=agent_id))
        finally:
            for f in file_objs:
                try:
                    f.close()
                except Exception:
                    pass

    # Optional direct text ingestion payload
    if agent_request.documents_text:
        _accumulate_ingest_metrics(_ingest_documents_text(agent_request.documents_text, agent_id))

    # Optional pre-scraped text ingestion
    if agent_request.scraped_data:
        _accumulate_ingest_metrics(_ingest_scraped_data(agent_request.scraped_data, agent_id))

    # Optional URL scrape refresh
    if normalized["urls"]:
        background_tasks.add_task(process_urls, normalized["urls"], agent_id)

    # Optional runtime restart behavior: clear agent chat history and reset LLM chain cache.
    if agent_request.restart_after_update:
        clear_history(agent_id=agent_id)
        update_agent_metadata(agent_id, message_count=0)
        reset_chain()

    # Agent lifecycle analytics row in ClickHouse.
    try:
        from core.clickhouse import log_agent_event_to_clickhouse

        log_agent_event_to_clickhouse(
            agent_id=agent_id,
            status="Updated",
            agent_name=(normalized["name"] or current.get("name")),
            user_id=audit_user_id,
            created_at=current.get("created_at"),
            deleted_at=None,
            model_selection=(normalized["model_selection"] or current.get("model_selection")),
            role_type=(role_type if normalized["role_type"] is not None else current.get("role_type")),
            subagent_type=(industry_update if industry_update is not None else current.get("industry")),
            vector_store=f"omni_agent_{agent_id}",
            vector_chunks=vector_chunks_total,
            parent_chunks=parent_chunks_total,
            payload={
                "restart_after_update": bool(agent_request.restart_after_update),
                "agent_type": (normalized["agent_type"] or current.get("agent_type")),
                "subagent_type": (normalized["subagent_type"] or current.get("subagent_type")),
            },
        )
    except Exception:
        pass

    agent = get_agent(agent_id)
    base_url = str(request.base_url).rstrip("/")
    try:
        sync_agent_config(
            agent_id,
            event_type="update",
            event_payload=normalized,
        )
    except Exception as cfg_exc:
        logging.warning(f"Agent config sync failed on update for {agent_id}: {cfg_exc}")
    return agent_to_response(agent, base_url)


@app.delete("/agents/{agent_id}", response_model=StatusResponse)
async def delete_agent_endpoint(agent_id: str, api_key: ApiKey = Depends(get_api_key)):
    """Delete an agent"""
    existing_agent = _require_agent_access(agent_id, api_key)
    _require_auth_user_id(api_key)
    audit_user_id = _agent_owner_user_id(existing_agent)

    success = delete_agent(agent_id)
    if not success:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Agent lifecycle analytics row in ClickHouse for delete operation.
    try:
        from core.clickhouse import log_agent_event_to_clickhouse

        log_agent_event_to_clickhouse(
                agent_id=agent_id,
                status="Deleted",
                agent_name=(existing_agent or {}).get("name"),
                user_id=audit_user_id,
            created_at=(existing_agent or {}).get("created_at"),
            deleted_at=datetime.datetime.utcnow(),
            model_selection=(existing_agent or {}).get("model_selection"),
            role_type=(existing_agent or {}).get("role_type"),
            subagent_type=(existing_agent or {}).get("industry"),
            vector_store=f"omni_agent_{agent_id}",
            vector_chunks=0,
            parent_chunks=0,
            payload={"agent_deleted": True},
        )
    except Exception:
        pass

    return {"status": "deleted", "id": agent_id}


# --- Documents ---
@app.get("/agents/{agent_id}/documents")
async def list_documents(agent_id: str, api_key: ApiKey = Depends(get_api_key)):
    """List documents for an agent"""
    _require_agent_access(agent_id, api_key)
    
    return get_agent_documents(agent_id)


@app.post("/agents/{agent_id}/documents")
async def upload_documents(
    agent_id: str,
    files: List[UploadFile] = File(None),
    text: Optional[str] = Form(None),
    api_key: ApiKey = Depends(get_api_key)
):
    """Upload documents to an agent"""
    _require_agent_access(agent_id, api_key)
    
    if not files and not text:
        raise HTTPException(status_code=400, detail="Provide files or text")
    
    result = process_documents(
        files=files if files else None,
        text_input=text,
        agent_id=agent_id
    )
    
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    
    return {"status": "success", "warning": result.get("warning")}


@app.delete("/documents/{document_id}", response_model=StatusResponse)
async def delete_document_endpoint(document_id: int, api_key: ApiKey = Depends(get_api_key)):
    """Delete a document"""
    doc_agent_id = _get_document_agent_id(document_id)
    if not doc_agent_id:
        raise HTTPException(status_code=404, detail="Document not found")
    _require_agent_access(doc_agent_id, api_key)

    success = delete_document(document_id)
    if not success:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"status": "deleted", "document_id": document_id}


# --- History ---
@app.get("/agents/{agent_id}/history")
async def get_history(agent_id: str, limit: int = 20, api_key: ApiKey = Depends(get_api_key)):
    """Get conversation history for an agent"""
    _require_agent_access(agent_id, api_key)
    
    return get_conversation_history(agent_id=agent_id, limit=limit)


@app.get("/agents/{agent_id}/voice-context")
async def get_voice_context(
    agent_id: str,
    query: str = "",
    top_k: int = 3,
    api_key: ApiKey = Depends(get_api_key),
):
    """
    Retrieve compact vector context for voice sessions.
    Used by direct PersonaPlex/Moshi integrations (no OmniCortex voice proxy).
    """
    _require_agent_access(agent_id, api_key)
    agent = get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    safe_top_k = max(1, min(6, int(top_k or 3)))
    retrieval_query = str(query or "").strip()
    if _looks_like_prompt_path(retrieval_query):
        retrieval_query = ""
    if not retrieval_query:
        raw_prompt = str(agent.get("system_prompt") or "").strip()
        if _looks_like_prompt_path(raw_prompt):
            raw_prompt = str(_resolve_system_prompt(raw_prompt) or "").strip()
            if _looks_like_prompt_path(raw_prompt):
                raw_prompt = ""
        retrieval_query = raw_prompt[:500].strip()
    if not retrieval_query:
        retrieval_query = str(agent.get("description") or agent.get("name") or "").strip()[:300]
    if not retrieval_query:
        return {"agent_id": agent_id, "query": "", "documents": 0, "context": ""}

    try:
        from core.rag.retrieval import hybrid_search
        from core.chat_service import format_context

        docs = hybrid_search(retrieval_query, agent_id=agent_id, top_k=safe_top_k, rerank=False)
        context = format_context(docs)
        if context == "No relevant documents found.":
            context = ""
        return {
            "agent_id": agent_id,
            "query": retrieval_query,
            "documents": len(docs),
            "context": context,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Voice context retrieval failed: {e}")


@app.get("/voice/profile", response_model=VoiceProfileResponse)
async def get_voice_profile(api_key: ApiKey = Depends(get_api_key)):
    """
    Get persisted voice UI profile from PostgreSQL (omni_channels.config),
    scoped to authenticated token/user identity.
    """
    channel_name = _voice_profile_channel_name(api_key)
    db = SessionLocal()
    try:
        row = (
            db.query(Channel)
            .filter(
                Channel.name == channel_name,
                Channel.type == "voice",
                Channel.provider == "personaplex",
            )
            .first()
        )
        profile = dict((row.config or {}) if row else {})
        return {"status": "ok", "profile": _public_voice_profile(profile)}
    finally:
        db.close()


@app.post("/voice/profile", response_model=VoiceProfileResponse)
async def save_voice_profile(payload: VoiceProfileUpdate, api_key: ApiKey = Depends(get_api_key)):
    """
    Upsert persisted voice UI profile into PostgreSQL (omni_channels.config),
    scoped to authenticated token/user identity.
    """
    channel_name = _voice_profile_channel_name(api_key)
    db = SessionLocal()
    try:
        row = (
            db.query(Channel)
            .filter(
                Channel.name == channel_name,
                Channel.type == "voice",
                Channel.provider == "personaplex",
            )
            .first()
        )

        existing_config = dict((row.config or {}) if row else {})
        normalized = _sanitize_voice_profile_payload(
            payload.model_dump(exclude_none=True),
            keep_existing_api_key=str(existing_config.get("api_key") or "").strip(),
        )
        normalized["updated_at"] = datetime.datetime.utcnow().isoformat() + "Z"

        if row is None:
            row = Channel(
                id=str(uuid.uuid4()),
                name=channel_name,
                type="voice",
                provider="personaplex",
                config=normalized,
                agent_id=normalized.get("selected_agent_id"),
            )
            db.add(row)
        else:
            row.config = normalized
            row.agent_id = normalized.get("selected_agent_id")

        db.commit()
        return {"status": "saved", "profile": _public_voice_profile(normalized)}
    finally:
        db.close()


@app.get("/freeswitch/verto/check", response_model=VertoCheckResponse)
async def check_freeswitch_verto(
    url: Optional[str] = None,
    timeout_sec: float = 8.0,
):
    """
    Attempt a WebSocket handshake to FreeSWITCH Verto (typically /verto on 7443 or via 443 proxy).
    Useful to validate that OmniCortex can reach the Verto listener.
    """
    target_url = _resolve_verto_ws_url(url)
    safe_timeout = max(2.0, min(30.0, float(timeout_sec or 8.0)))
    ssl_ctx, ssl_verify = _verto_ssl_context(target_url)

    import aiohttp

    try:
        timeout = aiohttp.ClientTimeout(total=safe_timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.ws_connect(target_url, ssl=ssl_ctx, heartbeat=10):
                pass
        return {
            "status": "connected",
            "url": target_url,
            "ssl_verify": ssl_verify,
            "timeout_sec": safe_timeout,
            "detail": "WebSocket handshake succeeded",
        }
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail=f"Timed out connecting to {target_url}")
    except aiohttp.WSServerHandshakeError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Verto handshake failed (HTTP {exc.status}) for {target_url}: {exc.message}",
        )
    except aiohttp.ClientError as exc:
        raise HTTPException(status_code=502, detail=f"Verto connect failed for {target_url}: {exc}")


# --- Voice WebSocket Proxy (Moshi) ---
async def _authenticate_voice_websocket(websocket: WebSocket) -> Optional[str]:
    """
    Validate bearer token for WebSocket handshake.
    Returns None when authorized, otherwise an error string.
    """
    auth_header = (websocket.headers.get("authorization") or "").strip()
    token = ""
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
    # Browser WebSocket clients cannot set arbitrary headers; allow token in query.
    if not token:
        token = (websocket.query_params.get("token") or "").strip()
    if not token:
        return "Authorization Bearer token missing"

    x_user_id = (websocket.headers.get("x-user-id") or "").strip()
    if not x_user_id:
        x_user_id = (websocket.query_params.get("x_user_id") or "").strip()
    try:
        await verify_bearer_token(token, x_user_id or None)
        return None
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "Unauthorized"
        return detail
    except Exception as exc:
        logging.error(f"Voice WS auth verification failed: {exc}")
        return "Auth verification unavailable"


@app.websocket("/freeswitch/verto/ws")
async def freeswitch_verto_ws_proxy(websocket: WebSocket):
    """
    Authenticated WebSocket proxy that relays frames between client and FreeSWITCH Verto.
    Query params:
      - token: bearer token (required if Authorization header not set)
      - url / target_url: optional override for upstream verto URL
      - timeout_sec: optional client timeout (2..180)
    """
    auth_error = await _authenticate_voice_websocket(websocket)
    if auth_error:
        await websocket.close(code=1008, reason=auth_error)
        return

    override = websocket.query_params.get("target_url") or websocket.query_params.get("url")
    timeout_raw = websocket.query_params.get("timeout_sec", "60")
    try:
        safe_timeout = max(2.0, min(180.0, float(timeout_raw)))
    except Exception:
        safe_timeout = 60.0

    try:
        target_url = _resolve_verto_ws_url(override)
    except HTTPException as exc:
        await websocket.close(code=1008, reason=str(exc.detail))
        return

    ssl_ctx, _ = _verto_ssl_context(target_url)
    await websocket.accept()

    import aiohttp

    try:
        timeout = aiohttp.ClientTimeout(total=safe_timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.ws_connect(target_url, ssl=ssl_ctx, heartbeat=15) as verto_ws:
                logging.info(f"Verto WS proxy connected: upstream={target_url}")

                async def client_to_verto():
                    while True:
                        msg = await websocket.receive()
                        msg_type = msg.get("type")
                        if msg_type == "websocket.disconnect":
                            break
                        if msg_type != "websocket.receive":
                            continue
                        text_data = msg.get("text")
                        bytes_data = msg.get("bytes")
                        if text_data is not None:
                            await verto_ws.send_str(text_data)
                        elif bytes_data is not None:
                            await verto_ws.send_bytes(bytes_data)

                async def verto_to_client():
                    async for msg in verto_ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await websocket.send_text(msg.data)
                        elif msg.type == aiohttp.WSMsgType.BINARY:
                            await websocket.send_bytes(msg.data)
                        elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            break

                tasks = [
                    asyncio.create_task(client_to_verto()),
                    asyncio.create_task(verto_to_client()),
                ]
                _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()

    except aiohttp.WSServerHandshakeError as exc:
        logging.error(f"Verto WS proxy handshake failed: status={exc.status} url={target_url} msg={exc.message}")
        try:
            await websocket.close(code=1011, reason=f"Verto handshake failed HTTP {exc.status}")
        except Exception:
            pass
    except aiohttp.ClientError as exc:
        logging.error(f"Verto WS proxy connect failed: url={target_url} err={exc}")
        try:
            await websocket.close(code=1011, reason="Verto upstream unavailable")
        except Exception:
            pass
    except WebSocketDisconnect:
        logging.info("Verto WS proxy: client disconnected")
    except Exception as exc:
        logging.error(f"Verto WS proxy error: {exc}")
        try:
            await websocket.close(code=1011, reason="Verto proxy error")
        except Exception:
            pass


@app.websocket("/voice/ws")
async def voice_ws_proxy(websocket: WebSocket):
    """
    WebSocket proxy to Moshi voice server.
    Fetches agent context for RAG-enriched text_prompt, then relays binary frames.
    
    Query params (from client):
      - agent_id: (optional) Agent whose system_prompt becomes Moshi's text_prompt
      - text_prompt: (optional) Override/additional text prompt
      - voice_prompt: (optional) Voice prompt filename (default: NATF0.pt)
      - seed: (optional) Random seed
    """
    import aiohttp
    from core.config import PERSONAPLEX_URL

    auth_error = await _authenticate_voice_websocket(websocket)
    if auth_error:
        await websocket.close(code=1008, reason=auth_error)
        return

    await websocket.accept()

    # --- Build the text_prompt from agent context ---
    agent_id = websocket.query_params.get("agent_id")
    client_text_prompt = websocket.query_params.get("text_prompt", "")
    context_query = str(websocket.query_params.get("context_query", "") or "")[:1000]
    voice_prompt = websocket.query_params.get("voice_prompt", "NATF0.pt")
    seed = websocket.query_params.get("seed", "-1")

    text_prompt = str(client_text_prompt or "").strip()
    append_client_prompt = os.getenv("VOICE_APPEND_CLIENT_PROMPT", "false").strip().lower() == "true"
    agent_prompt = ""
    if agent_id:
        try:
            agent = get_agent(agent_id)
            if agent and agent.get("system_prompt"):
                # Agent prompt is authoritative for voice when agent_id is provided.
                agent_prompt = str(agent["system_prompt"])
                text_prompt = agent_prompt
                if append_client_prompt and client_text_prompt:
                    text_prompt = (
                        f"{agent_prompt}\n\n"
                        f"Additional operator instruction:\n{str(client_text_prompt).strip()}"
                    )
                logging.info(f"🎤 Voice proxy: Using agent '{agent.get('name')}' system_prompt ({len(text_prompt)} chars)")
        except Exception as e:
            logging.warning(f"⚠️ Voice proxy: Could not load agent {agent_id}: {e}")

    # Optional voice RAG: attach vector context to system prompt for /voice/ws sessions.
    voice_rag_enabled = os.getenv("VOICE_RAG_ENABLED", "true").strip().lower() == "true"
    if voice_rag_enabled and agent_id:
        retrieval_query = str(context_query or "").strip()
        if not retrieval_query and append_client_prompt:
            retrieval_query = str(client_text_prompt or "").strip()
        if not retrieval_query:
            retrieval_query = str(agent_prompt[:500]).strip()
        if retrieval_query:
            try:
                rag_top_k_raw = os.getenv("VOICE_RAG_TOP_K", "3").strip()
                rag_top_k = max(1, min(6, int(rag_top_k_raw)))
            except Exception:
                rag_top_k = 3
            try:
                from core.rag.retrieval import hybrid_search
                from core.chat_service import format_context

                docs = hybrid_search(retrieval_query, agent_id=agent_id, top_k=rag_top_k, rerank=False)
                rag_context = format_context(docs)
                if rag_context and rag_context != "No relevant documents found.":
                    prompt_prefix = text_prompt.strip()
                    rag_block = (
                        "Knowledge Base Context (vector retrieval):\n"
                        f"{rag_context}\n\n"
                        "Use this context when relevant. If the answer is not in context, say you are not certain."
                    )
                    text_prompt = f"{prompt_prefix}\n\n{rag_block}" if prompt_prefix else rag_block
                    logging.info(f"🎤 Voice proxy: Injected {len(docs)} RAG docs into voice prompt for agent {agent_id}")
                else:
                    logging.info(f"🎤 Voice proxy: No RAG docs found for agent {agent_id}")
            except Exception as e:
                logging.warning(f"⚠️ Voice proxy: RAG context injection failed for agent {agent_id}: {e}")

    # --- Build target Moshi WebSocket URL ---
    moshi_base = PERSONAPLEX_URL.rstrip("/")
    # Ensure ws:// or wss:// protocol
    if moshi_base.startswith("https"):
        moshi_ws_base = moshi_base.replace("https", "wss", 1)
    elif moshi_base.startswith("http"):
        moshi_ws_base = moshi_base.replace("http", "ws", 1)
    else:
        moshi_ws_base = moshi_base

    from urllib.parse import urlencode
    moshi_api_token = (os.getenv("MOSHI_API_TOKEN") or "").strip()
    upstream_query: Dict[str, str] = {
        "text_prompt": text_prompt,
        "voice_prompt": voice_prompt,
        "seed": seed,
    }
    if moshi_api_token:
        upstream_query["token"] = moshi_api_token

    query_params = urlencode(upstream_query)
    moshi_url = f"{moshi_ws_base}/api/chat?{query_params}"
    logging.info(f"🎤 Voice proxy: Connecting to Moshi at {moshi_ws_base}/api/chat")

    # --- Relay WebSocket frames bidirectionally ---
    # RunPod connection support: auth headers, SSL, heartbeat
    from core.config import (
        PERSONAPLEX_API_KEY as _PX_KEY,
        PERSONAPLEX_AUTH_HEADER as _PX_HDR,
        PERSONAPLEX_SSL_VERIFY as _PX_SSL_VERIFY,
        PERSONAPLEX_HEARTBEAT as _PX_HB,
    )
    _ws_headers = {}
    if _PX_KEY:
        _ws_headers[_PX_HDR] = _PX_KEY
    _ws_ssl = None
    if moshi_ws_base.startswith("wss"):
        import ssl as _ssl
        _ws_ssl = _ssl.create_default_context()
        if not _PX_SSL_VERIFY:
            _ws_ssl.check_hostname = False
            _ws_ssl.verify_mode = _ssl.CERT_NONE
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(
                moshi_url,
                headers=_ws_headers or None,
                ssl=_ws_ssl,
                heartbeat=_PX_HB,
            ) as moshi_ws:
                async def client_to_moshi():
                    """Forward binary frames from admin client to moshi server."""
                    try:
                        while True:
                            data = await websocket.receive_bytes()
                            await moshi_ws.send_bytes(data)
                    except Exception:
                        pass  # Client disconnected

                async def moshi_to_client():
                    """Forward binary frames from moshi server to admin client."""
                    try:
                        async for msg in moshi_ws:
                            if msg.type == aiohttp.WSMsgType.BINARY:
                                await websocket.send_bytes(msg.data)
                            elif msg.type == aiohttp.WSMsgType.TEXT:
                                await websocket.send_text(msg.data)
                            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                break
                    except Exception:
                        pass  # Moshi disconnected

                # Run both relay tasks concurrently; when either ends, cancel the other
                tasks = [
                    asyncio.create_task(client_to_moshi()),
                    asyncio.create_task(moshi_to_client()),
                ]
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()

    except aiohttp.ClientError as e:
        logging.error(f"❌ Voice proxy: Cannot connect to Moshi server: {e}")
        try:
            await websocket.close(code=1011, reason=f"Moshi server unavailable: {e}")
        except Exception:
            pass
    except WebSocketDisconnect:
        logging.info("🎤 Voice proxy: Client disconnected")
    except Exception as e:
        logging.error(f"❌ Voice proxy error: {e}")
        try:
            await websocket.close(code=1011, reason=str(e))
        except Exception:
            pass


# =============================================================================
# MULTI-MODE VOICE PIPELINE — /ws/voice/{agent_id}
# =============================================================================

@app.websocket("/ws/voice/{agent_id}")
async def voice_pipeline_ws(websocket: WebSocket, agent_id: str):
    """
    Multi-mode voice WebSocket endpoint.

    Query params:
      - mode: personaplex | lfm | cascade (default: personaplex)
      - token: Bearer token (required if Authorization header not set)
      - voice_prompt: Voice prompt filename (default: NATF0.pt)
      - sample_rate: Client PCM sample rate (default: 8000)
      - x_user_id: User ID override
    """
    from core.config import VOICE_DEFAULT_MODE, VOICE_PERSONAPLEX_FALLBACK
    from core.voice.voice_protocol import VoiceMode, VoiceSession, MSG_SESSION, MSG_STATUS, MSG_ERROR

    # --- Auth ---
    auth_error = await _authenticate_voice_websocket(websocket)
    if auth_error:
        await websocket.close(code=1008, reason=auth_error)
        return

    await websocket.accept()

    # --- Parse params ---
    mode_str = (websocket.query_params.get("mode") or VOICE_DEFAULT_MODE).strip().lower()
    voice_prompt = websocket.query_params.get("voice_prompt", "NATF0.pt")
    sample_rate = int(websocket.query_params.get("sample_rate", "8000"))
    x_user_id = (websocket.headers.get("x-user-id") or websocket.query_params.get("x_user_id") or "").strip() or None

    try:
        mode = VoiceMode(mode_str)
    except ValueError:
        mode = VoiceMode.PERSONAPLEX

    # --- Resolve agent ---
    system_prompt = ""
    agent_name = ""
    model_selection = None
    try:
        agent = get_agent(agent_id)
        if agent:
            system_prompt = agent.get("system_prompt") or ""
            agent_name = agent.get("name") or ""
            model_selection = agent.get("model_selection")
    except Exception:
        pass

    session = VoiceSession(
        agent_id=agent_id,
        mode=mode,
        user_id=x_user_id,
        sample_rate=sample_rate,
        voice_prompt=voice_prompt,
        system_prompt=system_prompt,
        agent_name=agent_name,
        model_selection=model_selection,
    )

    # Send session info
    try:
        import json as _json
        await websocket.send_text(_json.dumps({
            "type": MSG_SESSION,
            "session_id": session.session_id,
            "mode": session.mode.value,
            "agent_id": agent_id,
            "agent_name": agent_name,
        }))
    except Exception:
        pass

    logging.info("Voice pipeline session %s started (agent=%s, mode=%s)", session.session_id, agent_id, mode.value)

    # --- Dispatch to mode handler ---
    try:
        if mode == VoiceMode.PERSONAPLEX:
            try:
                from core.voice.mode_personaplex import handle_personaplex
                await handle_personaplex(websocket, session)
            except ConnectionError as ce:
                if VOICE_PERSONAPLEX_FALLBACK:
                    logging.warning("PersonaPlex unavailable, falling back to cascade: %s", ce)
                    try:
                        await websocket.send_text(_json.dumps({
                            "type": MSG_STATUS,
                            "status": "fallback",
                            "message": "PersonaPlex unavailable — using cascade mode",
                        }))
                    except Exception:
                        pass
                    session.mode = VoiceMode.CASCADE
                    from core.voice.mode_cascade import handle_cascade
                    await handle_cascade(websocket, session)
                else:
                    await websocket.send_text(_json.dumps({
                        "type": MSG_ERROR,
                        "message": f"PersonaPlex unavailable: {ce}",
                    }))

        elif mode == VoiceMode.LFM:
            from core.voice.mode_lfm import handle_lfm
            await handle_lfm(websocket, session)

        elif mode == VoiceMode.CASCADE:
            from core.voice.mode_cascade import handle_cascade
            await handle_cascade(websocket, session)

    except WebSocketDisconnect:
        logging.info("Voice pipeline session %s disconnected", session.session_id)
    except Exception as exc:
        logging.error("Voice pipeline session %s error: %s", session.session_id, exc)
        try:
            await websocket.send_text(_json.dumps({"type": MSG_ERROR, "message": str(exc)}))
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
        logging.info("Voice pipeline session %s ended", session.session_id)


# --- Voice ---
@app.post("/voice/transcribe")
async def transcribe_voice(audio: UploadFile = File(...), api_key: ApiKey = Depends(get_api_key)):
    """
    Moshi-only mode: REST transcription is not supported.
    Use WebSocket /voice/ws for real-time voice interaction.
    """
    raise HTTPException(
        status_code=501,
        detail="Moshi-only mode does not support REST transcription. Use /voice/ws.",
    )


@app.post("/voice/speak")
async def speak_text(
    text: str = Form(...),
    voice: str = Form(None),
    allow_fallback: bool = Form(False),
    api_key: ApiKey = Depends(get_api_key),
):
    """
    Moshi-only mode: REST TTS is not supported.
    Use WebSocket /voice/ws for real-time voice interaction.
    """
    raise HTTPException(
        status_code=501,
        detail="Moshi-only mode does not support REST TTS. Use /voice/ws.",
    )


@app.post("/voice/chat")
async def voice_chat(
    audio: UploadFile = File(...),
    agent_id: str = Form(None),
    allow_fallback: bool = Form(False),
    api_key: ApiKey = Depends(get_api_key),
):
    """
    Moshi-only mode: REST voice chat is not supported.
    Use WebSocket /voice/ws for real-time voice interaction.
    """
    raise HTTPException(
        status_code=501,
        detail="Moshi-only mode does not support REST /voice/chat. Use /voice/ws.",
    )


# --- LiquidAI Voice ---
@app.post("/api/v1/voice/liquid")
async def voice_chat_liquid(
    audio: UploadFile = File(...),
    agent_id: str = Form(None),
    system_prompt: str = Form("You are a helpful assistant. Respond with interleaved text and audio."),
    api_key: ApiKey = Depends(get_api_key),
):
    """
    Disabled in Moshi-only mode.
    """
    raise HTTPException(
        status_code=410,
        detail="Liquid voice endpoint disabled in Moshi-only mode. Use /voice/ws.",
    )


# ============== RUN ==============
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)



