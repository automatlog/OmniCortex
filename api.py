"""
OmniCortex FastAPI Backend
REST API for chat, agents, and documents
"""
import time
from typing import Optional, List
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request
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
    delete_agent,
    get_agent_documents,
    delete_document,
    get_conversation_history,
    process_question,
    process_documents,
)
from core.graph import create_rag_agent

# Import metrics from core.monitoring
from core.monitoring import (
    REQUEST_COUNT,
    REQUEST_LATENCY,
    CHAT_REQUESTS,
    PrometheusMiddleware
)

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
    max_history: int = 5
    model_selection: Optional[str] = None
    mock_mode: bool = False  # True = bypass LLM for load testing


class QueryResponse(BaseModel):
    answer: str
    agent_id: Optional[str] = None


class AgentCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    file_paths: Optional[List[str]] = []  # List of absolute paths on server


class AgentResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    document_count: int
    message_count: int
    webhook_url: Optional[str] = None


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
async def query(request: QueryRequest):
    """Chat with an agent using RAG"""
    try:
        # Track metrics
        CHAT_REQUESTS.labels(agent_id=request.agent_id or "default").inc()
        
        # Mock Mode: Skip LLM for load testing (tests DB + vector store only)
        if request.mock_mode:
            import time
            # Simulate minimal processing
            time.sleep(0.1)  # Simulate network latency
            return QueryResponse(
                answer="[MOCK] Load test response - LLM bypassed",
                agent_id=request.agent_id
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
        
        return QueryResponse(answer=answer, agent_id=request.agent_id)
    
    except FileNotFoundError:
        raise HTTPException(status_code=400, detail="Upload documents first")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Agents ---
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
async def create_new_agent(agent_request: AgentCreate, request: Request):
    """Create a new agent (optionally from local files)"""
    try:
        agent_id = create_agent(agent_request.name, agent_request.description)
        
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

        agent = get_agent(agent_id)
        base_url = str(request.base_url).rstrip("/")
        return agent_to_response(agent, base_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))



@app.delete("/agents/{agent_id}")
async def delete_agent_endpoint(agent_id: str):
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
    text: Optional[str] = Form(None)
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
async def delete_document_endpoint(document_id: int):
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

