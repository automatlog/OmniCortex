"""
OmniCortex FastAPI Backend
REST API for chat, agents, and documents
"""
import time
import uuid
from typing import Optional, List, Dict
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response
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

# Import core modules
from core import (
    get_all_agents,
    get_agent,
    create_agent,
    update_agent,
    delete_agent,
    get_agent_documents,
    delete_document,
    get_conversation_history,
    process_question,
    process_documents,
)
from core.database import Channel, Tool, Session, SessionLocal, ApiKey # Phase 2 & 3 & 4 support
from core.graph import create_rag_agent
from core.processing.scraper import process_urls

# Import metrics from core.monitoring
from core.monitoring import (
    REQUEST_COUNT,
    REQUEST_LATENCY,
    CHAT_REQUESTS,
    PrometheusMiddleware
)
from core.manager.connection_manager import ConnectionManager
from core.auth import get_api_key, create_new_api_key, get_db
from fastapi import Depends

# Initialize Connection Manager
manager = ConnectionManager()

# ============== APP SETUP ==============
from core.database import init_db

# Initialize Database
init_db()

app = FastAPI(
    title="OmniCortex API",
    description="Modern RAG Chatbot API with LangGraph, Prometheus metrics",
    version="1.0.0"
)


# ============== STARTUP VALIDATION ==============
@app.on_event("startup")
async def validate_dependencies():
    """
    Validate all required dependencies on startup
    Exit if critical dependencies are unavailable
    """
    import sys
    import requests
    
    print("\n" + "="*60)
    print("  OmniCortex Backend - Startup Validation")
    print("="*60)
    
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
        
        # Use ThreadPoolExecutor with 10-second timeout
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(check_db)
            try:
                future.result(timeout=10)
                print("  ✅ PostgreSQL connected")
            except FutureTimeoutError:
                print("  ❌ PostgreSQL connection timeout (10s)")
                print("  💡 Start PostgreSQL: docker-compose up -d postgres")
                all_ok = False
            except Exception as e:
                print(f"  ❌ PostgreSQL connection failed: {e}")
                print("  💡 Start PostgreSQL: docker-compose up -d postgres")
                all_ok = False
                
    except Exception as e:
        print(f"  ❌ PostgreSQL connection failed: {e}")
        print("  💡 Start PostgreSQL: docker-compose up -d postgres")
        all_ok = False
    
    # Check LLM Backend (Ollama or vLLM)
    expected_model = os.environ.get("VLLM_MODEL", "llama3.1:8b")
    vllm_base_url = os.environ.get("VLLM_BASE_URL", "http://localhost:11434/v1")
    is_ollama = ":11434" in vllm_base_url
    
    if is_ollama:
        print("\n[2/2] Checking Ollama...")
        try:
            response = requests.get("http://localhost:11434/api/tags", timeout=10)
            if response.status_code == 200:
                models = response.json().get("models", [])
                if any(expected_model in m.get("name", "") for m in models):
                    print(f"  ✅ Ollama running with {expected_model}")
                else:
                    print(f"  ⚠️  Ollama running but {expected_model} not found")
                    print(f"  💡 Pull model: ollama pull {expected_model}")
                    all_ok = False
            else:
                print(f"  ❌ Ollama returned status {response.status_code}")
                all_ok = False
        except Exception as e:
            print(f"  ❌ Ollama connection failed: {e}")
            print("  💡 Start Ollama: ollama serve")
            all_ok = False
    else:
        print(f"\n[2/2] Checking vLLM at {vllm_base_url}...")
        try:
            # vLLM exposes OpenAI-compatible /models endpoint
            health_url = vllm_base_url.rstrip('/').replace('/v1', '') + '/health'
            response = requests.get(health_url, timeout=10)
            if response.status_code == 200:
                print(f"  ✅ vLLM running with {expected_model}")
            else:
                print(f"  ⚠️  vLLM returned status {response.status_code}")
                print(f"  💡 vLLM may still be loading the model...")
                all_ok = False
        except Exception as e:
            print(f"  ⚠️  vLLM connection failed: {e}")
            print(f"  💡 vLLM may not be started yet (start via systemctl start omni-vllm)")
            # Don't fail hard — vLLM takes time to load
            print(f"  ℹ️  Continuing startup (vLLM will be checked via /health endpoint)")
    
    print("\n" + "="*60)
    if all_ok:
        print("  ✅ All dependencies validated")
        print("  🚀 Backend ready on http://localhost:8000")
        print("  📚 API docs: http://localhost:8000/docs")
    else:
        print("  ❌ Dependency validation failed")
        print("  🛑 Backend will exit")
        print("="*60 + "\n")
        sys.exit(1)
    
    print("="*60 + "\n")

# CORS Configuration - Enhanced with explicit origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",  # Alternative port
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,  # Cache preflight requests for 1 hour
)

# Track startup time for uptime calculation
import datetime
STARTUP_TIME = datetime.datetime.now()

# Health check cache
_health_cache = {"result": None, "timestamp": 0}


# ============== MODELS ==============
class QueryRequest(BaseModel):
    question: str
    agent_id: Optional[str] = None
    user_id: Optional[str] = "anonymous" # For session tracking
    session_id: Optional[str] = None # Resume existing session
    max_history: int = 5
    model_selection: Optional[str] = None
    mock_mode: bool = False  # True = bypass LLM for load testing


class QueryResponse(BaseModel):
    answer: str
    agent_id: Optional[str] = None
    session_id: Optional[str] = None


class AgentDocumentText(BaseModel):
    filename: str
    text: str


class ScrapedContent(BaseModel):
    url: Optional[str] = None
    text: str


class AgentCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    system_prompt: Optional[str] = None
    role_type: Optional[str] = None
    industry: Optional[str] = None
    urls: Optional[List[str]] = None
    conversation_starters: Optional[List[str]] = None
    image_urls: Optional[List[str]] = None
    video_urls: Optional[List[str]] = None
    documents_text: Optional[List[AgentDocumentText]] = None
    scraped_data: Optional[List[ScrapedContent]] = None
    file_paths: Optional[List[str]] = None  # Backward-compatible local files path list


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
    
    document_count: int
    message_count: int
    webhook_url: Optional[str] = None


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    role_type: Optional[str] = None
    industry: Optional[str] = None
    urls: Optional[List[str]] = None
    conversation_starters: Optional[List[str]] = None
    image_urls: Optional[List[str]] = None
    video_urls: Optional[List[str]] = None
    scraped_data: Optional[List[ScrapedContent]] = None


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
        allowed_origins = [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3001"
        ]
        if origin not in allowed_origins:
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
    
    health_status = {
        "status": "healthy",
        "version": "1.0.0",
        "timestamp": datetime.datetime.now().isoformat(),
        "services": {
            "database": {"status": "down", "latency_ms": 0},
            "ollama": {"status": "down", "latency_ms": 0, "model_loaded": False}
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
    
    # Check LLM Backend (Ollama or vLLM)
    try:
        import requests
        vllm_base_url = os.environ.get("VLLM_BASE_URL", "http://localhost:11434/v1")
        expected_model = os.environ.get("VLLM_MODEL", "llama3.1:8b")
        is_ollama = ":11434" in vllm_base_url
        
        llm_start = time.time()
        
        if is_ollama:
            response = requests.get("http://localhost:11434/api/tags", timeout=2)
            llm_latency = int((time.time() - llm_start) * 1000)
            if response.status_code == 200:
                models = response.json().get("models", [])
                model_loaded = any(expected_model in m.get("name", "") for m in models)
                health_status["services"]["llm"] = {
                    "status": "up",
                    "backend": "ollama",
                    "latency_ms": llm_latency,
                    "model_loaded": model_loaded
                }
                if not model_loaded:
                    health_status["status"] = "degraded"
            else:
                health_status["status"] = "degraded"
        else:
            health_url = vllm_base_url.rstrip('/').replace('/v1', '') + '/health'
            response = requests.get(health_url, timeout=2)
            llm_latency = int((time.time() - llm_start) * 1000)
            health_status["services"]["llm"] = {
                "status": "up" if response.status_code == 200 else "degraded",
                "backend": "vllm",
                "latency_ms": llm_latency,
                "model": expected_model
            }
            if response.status_code != 200:
                health_status["status"] = "degraded"
    except Exception as e:
        logging.error(f"LLM health check failed: {e}")
        health_status["status"] = "unhealthy"
        health_status["services"]["llm"] = {"status": "down", "error": str(e)}
    
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
async def metrics():
    """Expose Prometheus metrics"""
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    from starlette.responses import Response
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/auth/keys")
async def create_api_key_endpoint(owner: str, db: Session = Depends(get_db)):
    """Generate a new API Key (Unprotected for setup)"""
    new_key = create_new_api_key(owner, db)
    return {"key": new_key, "owner": owner}


@app.get("/stats/dashboard")
async def dashboard_stats():
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
async def get_document_chunks_api(document_id: int):
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
async def agent_stats():
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
    """Chat with an agent using RAG"""
    try:
        # Track metrics
        CHAT_REQUESTS.labels(agent_id=request.agent_id or "default").inc()
        
        # Session Tracking
        session_id = request.session_id
        db = SessionLocal()
        try:
            if not session_id:
                # Create new session
                import uuid
                session_id = str(uuid.uuid4())
                if request.agent_id:
                    new_sess = Session(
                        id=session_id,
                        agent_id=request.agent_id,
                        user_id=request.user_id or "anonymous",
                        status="active",
                        channel_type="web"
                    )
                    db.add(new_sess)
                    db.commit()
            
            # Update existing session duration/end_time is usually done on completion or heartbeat
            # For now, we just ensure it exists
        except Exception as e:
            print(f"⚠️ Session tracking error: {e}")
        finally:
            db.close()
            
        
        # Mock Mode: Skip LLM for load testing (tests DB + vector store only)
        if request.mock_mode:
            import time
            # Simulate minimal processing
            time.sleep(0.1)  # Simulate network latency
            return QueryResponse(
                answer="[MOCK] Load test response - LLM bypassed",
                agent_id=request.agent_id,
                session_id=session_id
            )
        
        # Get conversation history
        history = []
        if request.agent_id:
            history = get_conversation_history(
                agent_id=request.agent_id,
                limit=request.max_history * 2
            )
        
        # Process question
        answer = process_question(
            question=request.question,
            agent_id=request.agent_id,
            conversation_history=history,
            max_history=request.max_history,
            model_selection=request.model_selection
        )
        
        return QueryResponse(answer=answer, agent_id=request.agent_id, session_id=session_id)
    
    except FileNotFoundError:
        raise HTTPException(status_code=400, detail="Upload documents first")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@app.websocket("/ws/chat/{agent_id}")
async def websocket_endpoint(websocket: WebSocket, agent_id: str):
    """
    WebSocket endpoint for real-time chat.
    Connects to the agent's channel.
    Supports JSON protocol: {"content": "message"}
    """
    await manager.connect(websocket, agent_id)
    import json
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
                
                # 2. Process (Simulated)
                # In real scenario: answer = await process_question_async(...)
                import asyncio
                await asyncio.sleep(1) # Simulate thinking
                
                answer = f"Echo: {question}" # Placeholder
                
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
}
MAX_URLS = 25
MAX_CONVERSATION_STARTERS = 25
MAX_MEDIA_URLS = 25


def _model_to_dict(item):
    if item is None:
        return None
    if hasattr(item, "model_dump"):
        return item.model_dump()
    return item.dict()


def _normalize_role_and_industry(role_type: Optional[str], industry: Optional[str]) -> tuple:
    if role_type is None:
        return None, industry

    role_raw = role_type.strip()
    if not role_raw:
        return None, industry

    role_lower = role_raw.lower()

    # Backward compatibility: allow old role names and map them to categories.
    if role_raw in PERSONAL_ROLES:
        return "personal", industry
    if role_raw in BUSINESS_INDUSTRIES:
        return "business", industry or role_raw

    if role_lower not in ROLE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"role_type must be one of {sorted(ROLE_TYPES)}",
        )

    if role_lower == "business":
        if not industry or not industry.strip():
            raise HTTPException(
                status_code=400,
                detail="industry is required when role_type is 'business'",
            )
        if industry not in BUSINESS_INDUSTRIES:
            raise HTTPException(
                status_code=400,
                detail=f"industry must be one of {sorted(BUSINESS_INDUSTRIES)}",
            )
    elif industry:
        raise HTTPException(
            status_code=400,
            detail="industry is only valid when role_type is 'business'",
        )

    return role_lower, industry


def _validate_list_limits(agent_payload):
    if agent_payload.urls and len(agent_payload.urls) > MAX_URLS:
        raise HTTPException(status_code=400, detail=f"urls limit exceeded ({MAX_URLS})")
    if agent_payload.conversation_starters and len(agent_payload.conversation_starters) > MAX_CONVERSATION_STARTERS:
        raise HTTPException(
            status_code=400,
            detail=f"conversation_starters limit exceeded ({MAX_CONVERSATION_STARTERS})",
        )
    if agent_payload.image_urls and len(agent_payload.image_urls) > MAX_MEDIA_URLS:
        raise HTTPException(status_code=400, detail=f"image_urls limit exceeded ({MAX_MEDIA_URLS})")
    if agent_payload.video_urls and len(agent_payload.video_urls) > MAX_MEDIA_URLS:
        raise HTTPException(status_code=400, detail=f"video_urls limit exceeded ({MAX_MEDIA_URLS})")


def _ingest_documents_text(documents_text: Optional[List[AgentDocumentText]], agent_id: str):
    if not documents_text:
        return

    blocks = []
    for idx, doc in enumerate(documents_text, start=1):
        filename = (doc.filename or f"document_{idx}.txt").strip()
        text = (doc.text or "").strip()
        if not text:
            continue
        blocks.append(f"[Document: {filename}]\n{text}")

    if blocks:
        process_documents(text_input="\n\n".join(blocks), agent_id=agent_id)


def _ingest_scraped_data(scraped_data: Optional[List[ScrapedContent]], agent_id: str):
    if not scraped_data:
        return

    blocks = []
    for idx, row in enumerate(scraped_data, start=1):
        source_url = (row.url or f"scraped_source_{idx}").strip()
        text = (row.text or "").strip()
        if not text:
            continue
        blocks.append(f"Source URL: {source_url}\n\n{text}")

    if blocks:
        process_documents(text_input="\n\n".join(blocks), agent_id=agent_id)


def generate_agent_webhook_url(agent_name: str, agent_id: str) -> str:
    """Generate a unique webhook URL for an agent"""
    from datetime import datetime
    # Create a URL-safe slug: agent_name_YYYYMMDD_shortid
    safe_name = agent_name.lower().replace(" ", "_").replace("-", "_")
    date_str = datetime.now().strftime("%Y%m%d")
    short_id = agent_id[:8]
    return f"/webhooks/capture/{safe_name}_{date_str}_{short_id}"


def agent_to_response(agent: dict, base_url: str = None) -> AgentResponse:
    """Convert agent dict to response with webhook_url"""
    webhook_path = generate_agent_webhook_url(agent['name'], agent['id'])
    full_url = f"{base_url}{webhook_path}" if base_url else webhook_path
    return AgentResponse(
        id=agent['id'],
        name=agent['name'],
        description=agent.get('description'),
        system_prompt=agent.get('system_prompt'),
        role_type=agent.get('role_type'),
        industry=agent.get('industry'),
        urls=agent.get('urls'),
        conversation_starters=agent.get('conversation_starters'),
        image_urls=agent.get('image_urls'),
        video_urls=agent.get('video_urls'),
        scraped_data=agent.get('scraped_data'),
        document_count=agent.get('document_count', 0),
        message_count=agent.get('message_count', 0),
        webhook_url=full_url
    )


@app.get("/agents", response_model=List[AgentResponse])
async def list_agents(request: Request):
    """List all agents with their webhook URLs"""
    agents = get_all_agents()
    base_url = str(request.base_url).rstrip("/")
    return [agent_to_response(a, base_url) for a in agents]


@app.get("/agents/{agent_id}")
async def get_agent_detail(agent_id: str, request: Request):
    """Get agent details with webhook URL"""
    agent = get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    base_url = str(request.base_url).rstrip("/")
    return agent_to_response(agent, base_url)


@app.post("/agents", response_model=AgentResponse)
async def create_new_agent(agent_request: AgentCreate, request: Request, background_tasks: BackgroundTasks, api_key: ApiKey = Depends(get_api_key)):
    """Create a new agent (optionally from local files)"""
    try:
        _validate_list_limits(agent_request)
        role_type, industry = _normalize_role_and_industry(
            agent_request.role_type, agent_request.industry
        )
        if role_type is None and agent_request.industry:
            raise HTTPException(
                status_code=400,
                detail="industry is only valid when role_type is 'business'",
            )
        scraped_data = [_model_to_dict(row) for row in agent_request.scraped_data] if agent_request.scraped_data else None

        agent_id = create_agent(
            name=agent_request.name, 
            description=agent_request.description,
            system_prompt=agent_request.system_prompt,
            role_type=role_type,
            industry=industry,
            urls=agent_request.urls,
            conversation_starters=agent_request.conversation_starters,
            image_urls=agent_request.image_urls,
            video_urls=agent_request.video_urls,
            scraped_data=scraped_data,
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
                    process_documents(files=file_objs, agent_id=agent_id)
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
            _ingest_documents_text(agent_request.documents_text, agent_id)

        # Handle pre-scraped web content payload
        if agent_request.scraped_data:
            _ingest_scraped_data(agent_request.scraped_data, agent_id)
        
        # Trigger URL Scraping in Background
        if agent_request.urls:
            background_tasks.add_task(process_urls, agent_request.urls, agent_id)

        agent = get_agent(agent_id)
        base_url = str(request.base_url).rstrip("/")
        return agent_to_response(agent, base_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.put("/agents/{agent_id}", response_model=AgentResponse)
async def update_agent_endpoint(agent_id: str, agent_request: AgentUpdate, request: Request, api_key: ApiKey = Depends(get_api_key)):
    """Update an existing agent"""
    current = get_agent(agent_id)
    if not current:
        raise HTTPException(status_code=404, detail="Agent not found")

    _validate_list_limits(agent_request)
    role_type, industry = _normalize_role_and_industry(agent_request.role_type, agent_request.industry)
    scraped_data = [_model_to_dict(row) for row in agent_request.scraped_data] if agent_request.scraped_data else None

    current_role, _ = _normalize_role_and_industry(current.get("role_type"), current.get("industry"))
    target_role = role_type if agent_request.role_type is not None else current_role
    target_industry = industry if agent_request.industry is not None else current.get("industry")
    if agent_request.role_type is not None and target_role != "business":
        target_industry = None

    if target_role == "business":
        if not target_industry:
            raise HTTPException(
                status_code=400,
                detail="industry is required when role_type is 'business'",
            )
        if target_industry not in BUSINESS_INDUSTRIES:
            raise HTTPException(
                status_code=400,
                detail=f"industry must be one of {sorted(BUSINESS_INDUSTRIES)}",
            )
    elif target_industry and agent_request.industry is not None:
        raise HTTPException(
            status_code=400,
            detail="industry is only valid when role_type is 'business'",
        )

    success = update_agent(
        agent_id=agent_id,
        name=agent_request.name,
        description=agent_request.description,
        system_prompt=agent_request.system_prompt,
        role_type=role_type if agent_request.role_type is not None else None,
        industry=target_industry if (agent_request.industry is not None or agent_request.role_type is not None) else None,
        urls=agent_request.urls,
        conversation_starters=agent_request.conversation_starters,
        image_urls=agent_request.image_urls,
        video_urls=agent_request.video_urls,
        scraped_data=scraped_data,
    )
    if not success:
        raise HTTPException(status_code=404, detail="Agent not found")

    agent = get_agent(agent_id)
    base_url = str(request.base_url).rstrip("/")
    return agent_to_response(agent, base_url)


@app.delete("/agents/{agent_id}")
async def delete_agent_endpoint(agent_id: str, api_key: ApiKey = Depends(get_api_key)):
    """Delete an agent"""
    success = delete_agent(agent_id)
    if not success:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "deleted", "agent_id": agent_id}


# --- Documents ---
@app.get("/agents/{agent_id}/documents")
async def list_documents(agent_id: str):
    """List documents for an agent"""
    agent = get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    return get_agent_documents(agent_id)


@app.post("/agents/{agent_id}/documents")
async def upload_documents(
    agent_id: str,
    files: List[UploadFile] = File(None),
    text: Optional[str] = Form(None),
    api_key: ApiKey = Depends(get_api_key)
):
    """Upload documents to an agent"""
    agent = get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
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


@app.delete("/documents/{document_id}")
async def delete_document_endpoint(document_id: int, api_key: ApiKey = Depends(get_api_key)):
    """Delete a document"""
    success = delete_document(document_id)
    if not success:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"status": "deleted", "document_id": document_id}


# --- History ---
@app.get("/agents/{agent_id}/history")
async def get_history(agent_id: str, limit: int = 20):
    """Get conversation history for an agent"""
    agent = get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    return get_conversation_history(agent_id=agent_id, limit=limit)


# --- Voice ---
@app.post("/voice/transcribe")
async def transcribe_voice(audio: UploadFile = File(...)):
    """
    Transcribe audio to text using Moshi/PersonaPlex
    Accepts: wav, mp3, m4a, webm
    """
    try:
        from core.voice import transcribe_audio
        import tempfile
        import os
        
        # Save uploaded file temporarily
        suffix = os.path.splitext(audio.filename)[1] or ".wav"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            content = await audio.read()
            f.write(content)
            temp_path = f.name
        
        try:
            text = transcribe_audio(temp_path)
            return {"text": text, "filename": audio.filename}
        finally:
            os.unlink(temp_path)
    
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="Voice engine not available. Ensure Moshi/PersonaPlex is configured."
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/voice/speak")
async def speak_text(text: str = Form(...), voice: str = Form(None)):
    """
    Convert text to speech using Moshi/PersonaPlex
    Returns: audio/wav file
    """
    try:
        from core.voice import speak
        from starlette.responses import Response
        
        audio_bytes = speak(text, voice=voice)
        return Response(
            content=audio_bytes,
            media_type="audio/wav",
            headers={"Content-Disposition": "attachment; filename=speech.wav"}
        )
    
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="Voice engine not available. Ensure Moshi/PersonaPlex is configured."
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/voice/chat")
async def voice_chat(
    audio: UploadFile = File(...),
    agent_id: str = Form(None)
):
    """
    Voice-to-voice chat: Transcribe audio -> RAG -> TTS response
    """
    try:
        from core.voice import transcribe_audio, speak
        import tempfile
        import os
        
        # 1. Transcribe audio
        suffix = os.path.splitext(audio.filename)[1] or ".wav"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            content = await audio.read()
            f.write(content)
            temp_path = f.name
        
        try:
            question = transcribe_audio(temp_path)
        finally:
            os.unlink(temp_path)
        
        # 2. Get RAG response
        history = []
        if agent_id:
            history = get_conversation_history(agent_id=agent_id, limit=10)
        
        answer = process_question(
            question=question,
            agent_id=agent_id,
            conversation_history=history
        )
        
        # 3. Convert to speech
        audio_bytes = speak(answer)
        
        # Return both text and audio
        import base64
        return {
            "question": question,
            "answer": answer,
            "audio_base64": base64.b64encode(audio_bytes).decode()
        }
    
    except ImportError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Channels (Phase 2) ---
@app.get("/channels", response_model=List[ChannelResponse])
async def list_channels(api_key: ApiKey = Depends(get_api_key)):
    """List all configured channels"""
    db = SessionLocal()
    try:
        channels = db.query(Channel).all()
        return [
            ChannelResponse(
                id=c.id, name=c.name, type=c.type, provider=c.provider,
                config=c.config, agent_id=c.agent_id,
                created_at=c.created_at.isoformat() if c.created_at else None
            )
            for c in channels
        ]
    finally:
        db.close()

@app.post("/channels", response_model=ChannelResponse)
async def create_channel(channel: ChannelCreate, api_key: ApiKey = Depends(get_api_key)):
    """Create a new channel"""
    db = SessionLocal()
    try:
        new_channel = Channel(
            id=str(uuid.uuid4()),
            name=channel.name,
            type=channel.type,
            provider=channel.provider,
            config=channel.config,
            agent_id=channel.agent_id
        )
        db.add(new_channel)
        db.commit()
        db.refresh(new_channel)
        return ChannelResponse(
            id=new_channel.id, name=new_channel.name, type=new_channel.type,
            provider=new_channel.provider, config=new_channel.config,
            agent_id=new_channel.agent_id,
            created_at=new_channel.created_at.isoformat() if new_channel.created_at else None
        )
    finally:
        db.close()

@app.delete("/channels/{channel_id}")
async def delete_channel(channel_id: str, api_key: ApiKey = Depends(get_api_key)):
    """Delete a channel"""
    db = SessionLocal()
    try:
        channel = db.query(Channel).filter(Channel.id == channel_id).first()
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")
        db.delete(channel)
        db.commit()
        return {"status": "deleted", "id": channel_id}
    finally:
        db.close()


# --- Tools (Phase 2) ---
@app.get("/agents/{agent_id}/tools", response_model=List[ToolResponse])
async def list_agent_tools(agent_id: str, api_key: ApiKey = Depends(get_api_key)):
    """List tools for a specific agent"""
    db = SessionLocal()
    try:
        tools = db.query(Tool).filter(Tool.agent_id == agent_id).all()
        return [
            ToolResponse(
                id=t.id, name=t.name, type=t.type, content=t.content,
                agent_id=t.agent_id,
                created_at=t.created_at.isoformat() if t.created_at else None
            )
            for t in tools
        ]
    finally:
        db.close()

@app.post("/agents/{agent_id}/tools", response_model=ToolResponse)
async def create_tool(agent_id: str, tool: ToolCreate, api_key: ApiKey = Depends(get_api_key)):
    """Create a new messaging tool for an agent"""
    if tool.agent_id != agent_id:
        raise HTTPException(status_code=400, detail="Agent ID mismatch")
        
    db = SessionLocal()
    try:
        # Check if agent exists
        if not get_agent(agent_id):
             raise HTTPException(status_code=404, detail="Agent not found")
             
        new_tool = Tool(
            id=str(uuid.uuid4()),
            name=tool.name,
            type=tool.type,
            content=tool.content,
            agent_id=agent_id
        )
        db.add(new_tool)
        db.commit()
        db.refresh(new_tool)
        return ToolResponse(
            id=new_tool.id, name=new_tool.name, type=new_tool.type,
            content=new_tool.content, agent_id=new_tool.agent_id,
            created_at=new_tool.created_at.isoformat() if new_tool.created_at else None
        )
    finally:
        db.close()

@app.delete("/tools/{tool_id}")
async def delete_tool(tool_id: str, api_key: ApiKey = Depends(get_api_key)):
    """Delete a tool"""
    db = SessionLocal()
    try:
        tool = db.query(Tool).filter(Tool.id == tool_id).first()
        if not tool:
            raise HTTPException(status_code=404, detail="Tool not found")
        db.delete(tool)
        db.commit()
        return {"status": "deleted", "id": tool_id}
    finally:
        db.close()


@app.post("/tools/{tool_id}/dispatch")
async def dispatch_tool(tool_id: str, payload: ToolDispatchRequest, api_key: ApiKey = Depends(get_api_key)):
    """
    Dispatch a tool (flow/button) to a WhatsApp user.
    Use dry_run=true to preview payload without sending.
    """
    db = SessionLocal()
    try:
        tool = db.query(Tool).filter(Tool.id == tool_id).first()
        if not tool:
            raise HTTPException(status_code=404, detail="Tool not found")

        content = tool.content or {}
        tool_type = (tool.type or "").strip().lower()

        if tool_type == "flow":
            flow_payload = {
                "to_number": payload.to_number,
                "flow_id": content.get("flow_id"),
                "flow_token": content.get("flow_token"),
                "header": content.get("header", "Flow"),
                "body": content.get("body", "Please continue"),
                "footer": content.get("footer", ""),
                "cta": content.get("cta", "Open"),
                "screen": content.get("screen", "START"),
                "data": content.get("data", {}),
            }
            if payload.dry_run:
                return {"status": "preview", "tool_type": "flow", "payload": flow_payload}

            from core.whatsapp import WhatsAppHandler

            wa = WhatsAppHandler()
            result = wa.send_flow_message(**flow_payload)
            return {"status": "sent", "tool_type": "flow", "result": result}

        if tool_type == "button_reply":
            button_payload = {
                "to_number": payload.to_number,
                "text": content.get("text", "Choose an option"),
                "buttons": content.get("buttons", []),
            }
            if payload.dry_run:
                return {"status": "preview", "tool_type": "button_reply", "payload": button_payload}

            from core.whatsapp import WhatsAppHandler

            wa = WhatsAppHandler()
            result = wa.send_interactive_message(
                to_number=button_payload["to_number"],
                text=button_payload["text"],
                buttons=button_payload["buttons"],
            )
            return {"status": "sent", "tool_type": "button_reply", "result": result}

        raise HTTPException(
            status_code=400,
            detail="Unsupported tool type. Supported: flow, button_reply",
        )
    finally:
        db.close()


# --- WhatsApp ---
from fastapi import Request
from core.whatsapp import WhatsAppHandler

@app.get("/api/v1/whatsapp/webhook")
async def verify_whatsapp_webhook(request: Request):
    """Meta Webhook Verification"""
    from core.config import WHATSAPP_VERIFY_TOKEN
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    mode = request.query_params.get("hub.mode")

    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        return int(challenge)
    raise HTTPException(status_code=403, detail="Verification failed")


@app.post("/api/v1/whatsapp/webhook")
async def whatsapp_webhook(request: Request):
    """Receive WhatsApp Messages"""
    data = await request.json()
    
    # Simple extraction
    handler = WhatsAppHandler()
    msg_data = handler.extract_message_from_webhook(data)
    
    if not msg_data:
        return {"status": "ignored", "reason": "not_text_message"}
    
    user_phone = msg_data["user_id"]
    text = msg_data.get("text")
    msg_type = msg_data.get("type", "text")
    user_name = msg_data.get("name", "User")
    
    # Handle Audio
    if msg_type == "audio":
        audio_meta = msg_data.get("audio")
        wa_logger.info(f"IN | Audio from {user_name}: {audio_meta}")
        print(f"🎤 Voice Note from {user_name} ({user_phone})")
        
        try:
            # 1. Get URL
            media_id = audio_meta.get("id")
            media_url = handler.get_media_url(media_id)
            if not media_url:
                raise ValueError("Could not get media URL")
                
            # 2. Download
            audio_data = handler.download_media(media_url)
            if not audio_data:
                raise ValueError("Could not download media")
                
            # 3. Transcribe
            import tempfile
            from core.voice import transcribe_audio
            
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
                f.write(audio_data)
                temp_path = f.name
            
            try:
                print("⏳ Transcribing audio...")
                text = transcribe_audio(temp_path)
                print(f"📝 Transcribed: {text}")
                wa_logger.info(f"TRANSCRIBED | {text}")
            finally:
                os.unlink(temp_path)
                
            if not text:
                return {"status": "ignored", "reason": "empty_transcription"}
                
        except Exception as e:
            wa_logger.error(f"AUDIO_ERR | {e}")
            print(f"❌ Audio Error: {e}")
            handler.send_message(user_phone, "Sorry, I couldn't listen to your voice note.")
            return {"status": "error", "detail": str(e)}

    # Fallback if neither text nor audio successfully processed
    if not text:
         return {"status": "ignored", "reason": "no_content"}

    wa_logger.info(f"IN | {user_name} ({user_phone}): {text}")
    print(f"📩 WhatsApp from {user_name} ({user_phone}): {text}")
    
    try:
        # Use first available agent or "default"
        # Ideally, we should check if the user is already talking to a specific agent.
        # For now, we default to the first agent in the list.
        agents = get_all_agents()
        agent_id = agents[0]['id'] if agents else None
        
        # Get persistent conversation history for this phone number
        from core.whatsapp_history import get_whatsapp_history
        wa_history = get_whatsapp_history()
        
        # Get or create session
        wa_history.get_or_create_session(user_phone, agent_id)
        
        # Get conversation history
        conversation_history = wa_history.get_history_for_llm(user_phone, limit=5)
        
        answer = process_question(
            question=text,
            agent_id=agent_id,
            conversation_history=conversation_history,
            max_history=5
        )
        
        # Save both user message and assistant response
        wa_history.add_message(user_phone, "user", text)
        wa_history.add_message(user_phone, "assistant", answer)
        
        # Send Reply
        wa_logger.info(f"OUT | {user_phone}: {answer[:100]}")
        print(f"📤 Replying to {user_phone}: {answer[:50]}...")
        result = handler.send_message(user_phone, answer)
        
        return {"status": "processed", "reply_id": result.get("messages", [{}])[0].get("id")}
        
    except Exception as e:
        wa_logger.error(f"ERR | {user_phone}: {e}")
        print(f"❌ Error processing WhatsApp: {e}")
        return {"status": "error", "detail": str(e)}


# --- Webhook Capture ---
from core.database import save_webhook_log, get_webhook_logs, clear_webhook_logs
import json as json_lib




@app.api_route("/webhooks/agent-reply", methods=["GET", "POST", "PUT"])
@app.api_route("/webhooks/capture/{path:path}", methods=["GET", "POST", "PUT"])
async def agent_reply_webhook(request: Request, path: str = None):
    """
    Enhanced Webhook:
    1. Captures/Logs the webhook data.
    2. Extract message (WhatsApp or simple JSON).
    3. Queries Agent.
    4. Returns Answer.
    
    Supports URL: /webhooks/capture/{agent_name_date} or /webhooks/agent-reply
    """
    try:
        # --- 1. CAPTURE LOGIC ---
        method = request.method
        url = str(request.url)
        query_params = str(request.query_params) if request.query_params else None
        headers = json_lib.dumps(dict(request.headers))
        source_ip = request.client.host if request.client else None
        
        body_bytes = await request.body()
        try:
            body_str = body_bytes.decode("utf-8")
            data = json_lib.loads(body_str) if body_str else {}
        except:
            body_str = "(binary/invalid)"
            data = {}
            
        print(f"📥 Agent Webhook Received (Path: {path}): {method} {url}")
        
        try:
            save_webhook_log(
                method=method,
                url=url,
                query_params=query_params,
                headers=headers,
                body=body_str,
                source_ip=source_ip
            )
        except Exception as log_err:
            print(f"⚠️ Failed to log webhook: {log_err}")

        # If it's just a GET verification (like Meta), return challenge if present
        if method == "GET":
             hub_mode = request.query_params.get("hub.mode")
             hub_challenge = request.query_params.get("hub.challenge")
             if hub_mode == "subscribe" and hub_challenge:
                 return int(hub_challenge)
             return {"status": "captured", "message": "GET request logged"}

        # --- 2. MESSAGE EXTRACTION ---
        text = None
        user_id = "unknown"
        
        # Try WhatsApp structure
        try:
            entry = data.get("entry", [])[0]
            change = entry.get("changes", [])[0]
            value = change.get("value", {})
            if "messages" in value:
                message = value["messages"][0]
                if message.get("type") == "text":
                    text = message["text"]["body"]
                    user_id = message.get("from", "whatsapp_user")
        except (IndexError, KeyError, TypeError):
            pass
            
        # Try Fallback (simple JSON)
        if not text:
            text = data.get("message") or data.get("text") or data.get("question")
            
        if not text:
            return {"status": "ignored", "reason": "no_text_found", "data": data}

        print(f"📝 Processing Question from {user_id}: {text}")

        # --- 3. AGENT SELECTION ---
        # Try to infer agent from path (e.g., "sales_agent_2023")
        agents = get_all_agents()
        target_agent_id = None
        
        if path:
            # Simple heuristic: matches agent name in path
            for agent in agents:
                if agent['name'].lower() in path.lower():
                    target_agent_id = agent['id']
                    break
        
        if not target_agent_id:
             target_agent_id = agents[0]['id'] if agents else None

        # --- 4. PROCESS RESPONSE ---
        answer = process_question(
            question=text,
            agent_id=target_agent_id,
            conversation_history=[], # Stateless for now
            max_history=5
        )
        
        print(f"📤 Agent Answer: {answer[:100]}...")
        
        return {
            "status": "success",
            "user_id": user_id,
            "question": text,
            "agent_id": target_agent_id,
            "answer": answer
        }

    except Exception as e:
        print(f"❌ Agent Webhook Error: {e}")
        return {"status": "error", "detail": str(e)}


@app.get("/webhooks/logs")
async def get_webhooks(limit: int = 50, offset: int = 0):
    """Get captured webhook logs"""
    return get_webhook_logs(limit=limit, offset=offset)



@app.delete("/webhooks/logs")
async def clear_webhooks():
    """Clear all webhook logs"""
    clear_webhook_logs()
    return {"status": "cleared"}


# --- LiquidAI Voice ---
@app.post("/api/v1/voice/liquid")
async def voice_chat_liquid(
    audio: UploadFile = File(...),
    agent_id: str = Form(None),
    system_prompt: str = Form("You are a helpful assistant. Respond with interleaved text and audio.")
):
    """
    End-to-end voice chat using LiquidAI LFM2.5-Audio.
    Accepts audio, returns audio + text response.
    """
    try:
        from core.voice.liquid_voice import get_voice_engine
        import base64
        
        # Read audio
        audio_bytes = await audio.read()
        
        # Get agent system prompt if specified
        if agent_id:
            agent = get_agent(agent_id)
            if agent and agent.get("system_prompt"):
                system_prompt = agent["system_prompt"]
        
        # Get voice engine and process
        engine = get_voice_engine()
        response = engine.transcribe_and_respond(
            audio_bytes=audio_bytes,
            system_prompt=system_prompt,
            max_new_tokens=512
        )
        
        return {
            "text": response.text,
            "audio_base64": base64.b64encode(response.audio_bytes).decode() if response.audio_bytes else None,
            "sample_rate": response.sample_rate,
            "duration_ms": response.duration_ms
        }
    
    except ImportError as e:
        raise HTTPException(
            status_code=501, 
            detail=f"LiquidAI not available. Install: pip install liquid-audio. Error: {e}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== RUN ==============
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

