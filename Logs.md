# OmniCortex — Session Logs

---

## 2026-03-20 — Session 1: Full Project Analysis & Critical Fixes

### 2026-03-20 | Project Analysis Output

#### Project Overview

OmniCortex is a multi-agent RAG (Retrieval-Augmented Generation) platform built with FastAPI, LangChain, pgvector, and vLLM-compatible LLM backends. It enables creating configurable AI agents, each with their own knowledge base, system prompts, and media assets — exposed via REST API, WebSocket, and WhatsApp Business API.

#### Architecture

```
                        ┌──────────────────────────────────┐
                        │           api.py (FastAPI)        │
                        │  REST + WebSocket + WhatsApp WH   │
                        └──────────┬───────────────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                     │
     ┌────────▼───────┐  ┌────────▼────────┐  ┌────────▼────────┐
     │  core/auth.py   │  │core/chat_service│  │core/agent_mgr   │
     │  Bearer → ext   │  │  Orchestrator   │  │  CRUD agents    │
     └─────────────────┘  └───────┬─────────┘  └─────────────────┘
                                  │
         ┌──────────┬─────────────┼─────────────┬──────────┐
         │          │             │             │          │
   ┌─────▼────┐ ┌───▼───┐ ┌──────▼─────┐ ┌────▼────┐ ┌───▼────┐
   │guardrails│ │ cache  │ │ rag/       │ │  llm    │ │response│
   │  input/  │ │semantic│ │ retrieval  │ │vLLM/Groq│ │ parser │
   │  output  │ │pgvector│ │ hybrid     │ │LangChain│ │ media  │
   └──────────┘ └────────┘ │ search+RRF │ └────┬────┘ │ tags   │
                           └──────┬──────┘      │      └────────┘
                                  │             │
                     ┌────────────┼──────┐      │
                     │            │      │      │
               ┌─────▼────┐ ┌────▼───┐  │  ┌───▼──────┐
               │vector_store│ │keyword │  │  │clickhouse│
               │ pgvector   │ │  FTS   │  │  │analytics │
               └────────────┘ └────────┘  │  └──────────┘
                                          │
                              ┌────────────▼──────────┐
                              │   PostgreSQL + pgvector│
                              │   (ORM: SQLAlchemy)    │
                              └───────────────────────┘
```

#### Module Dependency Chain

```
config.py ──────────────┬──→ database.py ──→ agent_manager.py ──→ chat_service.py ──→ api.py
                        │         │                   │                    │
                        │         ├──→ clickhouse.py ──┘                   │
                        │         ├──→ whatsapp_history.py                 │
                        │         └──→ agent_config.py                     │
                        │                                                  │
                        ├──→ llm.py ───────────────────────────────────────┘
                        │         └──→ monitoring.py
                        │
                        ├──→ rag/embeddings.py ──→ rag/vector_store.py ──→ rag/retrieval.py
                        │                                                       │
                        │                         processing/chunking.py ───────┘
                        │
                        └──→ cache.py ──→ rag/embeddings.py
```

#### Key Features

- **Multi-Agent RAG** — Each agent gets isolated vector store, conversation history, and system prompt
- **Hybrid Search** — Vector similarity (pgvector) + keyword (FTS via tsvector) fused with Reciprocal Rank Fusion
- **Parent-Child Chunking** — Small chunks for precision retrieval, parent chunks for full context
- **Semantic Cache** — pgvector cosine similarity cache with 24h TTL to avoid redundant LLM calls
- **Rich Media Responses** — Tag-based media (`[image]`, `[video]`, `[document]`, `[link]`, `[location]`, `[buttons]`) parsed and resolved per-agent
- **WhatsApp Business API** — Full send/receive integration with interactive buttons, flows, media
- **Multi-Backend LLM** — vLLM, Groq, or any OpenAI-compatible backend via `MODEL_BACKENDS` config
- **Triple Analytics** — PostgreSQL usage logs + ClickHouse buffered analytics + Prometheus metrics
- **Voice Pipeline** — WebSocket-based PersonaPlex/Moshi voice bridge (Opus codec, resampling)
- **Tool System** — Scaffolded for API calls, Web Search, and Unsplash image picker

#### Strengths

1. Clean RAG pipeline — Parent-child splitting + hybrid search + RRF + optional cross-encoder reranking
2. Agent isolation — Per-agent vector stores, configs, media, and conversation history
3. Graceful degradation — Embedding model fallback chain, optional ClickHouse, optional reranker
4. Schema migration — `ensure_schema_updates()` handles column additions idempotently
5. Connection pooling — SQLAlchemy pool with pre-ping and recycling
6. ClickHouse buffering — Thread-safe batch writer with overflow protection
7. Canonical media tag enforcement — Normalizes LLM output before delivery

#### Areas for Improvement

- PII masking inconsistency (masked for search, raw sent to LLM) — **FIXED**
- Blocking sync HTTP in async auth handler — **FIXED**
- Missing vector cleanup on document deletion — **FIXED**
- No cache invalidation on document upload — **FIXED**
- Misleading Prometheus metric names — **FIXED**
- Thread safety gaps in embedding singleton — **FIXED**
- Dead code and unused imports — **CLEANED**

#### Application Startup Flow

```
Module load (api.py import time)
  ├─ core/__init__.py imported
  │    ├─ core/config.py → loads .env, RAISES ValueError if DATABASE_URL missing
  │    ├─ core/database.py → creates SQLAlchemy engine, runs init_db() / schema migrations
  │    ├─ core/monitoring.py → loads logging_config.yaml, creates Prometheus metrics
  │    └─ core/rag/embeddings.py → deferred (lazy singleton)
  ├─ ConnectionManager() instantiated
  └─ init_db() runs DDL BEFORE lifespan validation
       ↓
lifespan() async context manager
  ├─ validate_dependencies()
  │    ├─ PostgreSQL SELECT 1 (10s timeout, ThreadPoolExecutor)
  │    └─ vLLM /health → fallback /v1/models
  └─ If STRICT_STARTUP_VALIDATION=true and any check fails → RuntimeError (process dies)
       ↓
CORS middleware registered → metrics_middleware registered → App ready
```

**Logic Break:** `init_db()` runs at import time, before `lifespan()` validation. If the DB is unreachable, the process crashes with an opaque SQLAlchemy error rather than the graceful validation message.

#### Request Flow — `/query` (Main Chat Pipeline)

```
POST /query
  ├─ Auth: get_api_key (Depends) → async httpx to AUTH_VERIFY_URL [FIXED]
  ├─ Resolve agent_id, user_id, session_id
  ├─ Auto-create/reuse DB session per (agent_id, user_id, channel_name)
  ├─ process_question(agent_id, question, ...)        [core/chat_service.py]
  │    ├─ get_agent(agent_id)                          [core/agent_manager.py]
  │    ├─ _rule_based_agent_reply()                    (greeting/goodbye shortcuts)
  │    ├─ mask_pii(question) → safe_question           [core/processing/pii.py]
  │    ├─ check_cache(safe_question, agent_id)         [core/cache.py]
  │    │    └─ pgvector cosine similarity search
  │    ├─ hybrid_search(safe_question, agent_id)       [core/rag/retrieval.py]
  │    │    ├─ search_documents() via pgvector          [core/rag/vector_store.py]
  │    │    ├─ keyword_search() via raw SQL
  │    │    ├─ reciprocal_rank_fusion()
  │    │    └─ rerank_documents() via CrossEncoder (optional)
  │    ├─ invoke_chain(safe_question, context, ...)    [core/llm.py] [FIXED → uses masked question]
  │    │    ├─ get_qa_chain() → LRU-cached ChatOpenAI
  │    │    ├─ retry_with_backoff(chain.invoke)
  │    │    ├─ log_usage() → PostgreSQL                 [core/database.py]
  │    │    ├─ log_usage_to_clickhouse()                [core/clickhouse.py]
  │    │    └─ sync_agent_config()                      [core/agent_config.py]
  │    ├─ enforce_canonical_media_tags(answer)          [core/response_parser.py]
  │    ├─ save_to_cache(question, answer, agent_id)    [core/cache.py]
  │    ├─ save_message(question) + save_message(answer) [core/database.py]
  │    └─ log_chat_to_clickhouse()                      [core/clickhouse.py]
  ├─ process_rich_response_for_frontend(answer)         [core/response_parser.py]
  └─ Return QueryResponse {answer, id, session_id, request_id}
```

#### File-by-File Edit Risk Map

**EXTREME RISK** (changes break the entire system):
- `api.py` — Monolith with all routes, 20+ Pydantic models, ~30 helpers with inline logic
- `core/__init__.py` — Facade re-exporting 33 symbols; removing any breaks imports globally
- `core/config.py` — Every constant consumed by multiple modules
- `core/database.py` — ORM models + CRUD + session factory used by virtually every module

**HIGH RISK** (changes break the chat pipeline):
- `core/chat_service.py` — `process_question` is the critical path for ALL queries
- `core/llm.py` — `PROMPT_TEMPLATE` is the ACTUAL system prompt; `invoke_chain` called every turn
- `core/rag/retrieval.py` — `hybrid_search` is the sole retrieval function
- `core/rag/vector_store.py` — Collection naming `omni_agent_{id}` is hardcoded
- `core/auth.py` — Changing return shape breaks all 20+ authenticated endpoints
- `core/agent_manager.py` — `get_agent` return dict shape consumed by 4+ modules

**MEDIUM RISK** (changes break specific features):
- `core/response_parser.py` — Tag syntax change breaks WhatsApp + frontend
- `core/processing/chunking.py` — Chunk size changes affect retrieval quality
- `core/cache.py` — Threshold/TTL changes affect answer freshness
- `core/clickhouse.py` — Column order must match ClickHouse DDL exactly
- `core/whatsapp.py` — Webhook return format change breaks processing
- `core/whatsapp_history.py` — Module-level create_all(); race in get_or_create_session

**LOW RISK** (isolated, changes stay contained):
- `core/guardrails.py`, `core/graph.py`, `core/crew.py`, `core/monitoring.py`, `core/processing/pii.py`, `core/voice/*`, `core/agent_config.py`

---

### 2026-03-20 | All Critical Logic Breaks Fixed — 16 fixes across 11 files

#### P0 — Security / Data Integrity

**Fix 1: PII leak to LLM** `core/chat_service.py`
- Problem: `mask_pii` created `safe_question` for search/storage, but raw `question` with PII was passed to `invoke_chain`. LLM could see and echo back emails, phone numbers, SSNs.
- Fix: Changed `invoke_chain(question, ...)` → `invoke_chain(safe_question, ...)` at line 324.
- Before:
```python
answer = invoke_chain(
    question,       # <-- raw PII
    context,
    history,
```
- After:
```python
answer = invoke_chain(
    safe_question,  # <-- PII masked
    context,
    history,
```

**Fix 2: Blocking sync HTTP in async auth** `core/auth.py`
- Problem: `verify_bearer_token` used synchronous `requests.get()` but was called from async `get_api_key`. Blocked the entire event loop under load.
- Fix: Replaced `import requests` with `import httpx`. Made `verify_bearer_token` async. Added reusable `httpx.AsyncClient` with connection pooling.
- Before:
```python
import requests
def verify_bearer_token(token, ...):
    response = requests.get(verify_url, headers=..., timeout=...)
```
- After:
```python
import httpx
_http_client: httpx.AsyncClient | None = None
async def verify_bearer_token(token, ...):
    client = _get_http_client()
    response = await client.get(verify_url, headers=...)
```

**Fix 3: Sync sleep in async handler** `api.py`
- Problem: Mock mode used `time.sleep(0.1)` inside an async route handler, blocking the event loop for 100ms.
- Fix: Changed to `await asyncio.sleep(0.1)`.
- Before: `time.sleep(0.1)  # Simulate network latency`
- After: `await asyncio.sleep(0.1)  # Simulate network latency`

#### P1 — Data Quality / Consistency

**Fix 4: delete_document doesn't delete vectors** `core/database.py`
- Problem: `delete_document` removed the DB metadata row but left embeddings in pgvector. Deleted documents still appeared in RAG search results.
- Fix: Added `db.query(ParentChunk).filter(ParentChunk.source_doc_id == doc.id).delete()` before deleting the document row.
- Before:
```python
def delete_document(document_id):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if doc:
        db.delete(doc)  # <-- vectors left orphaned
```
- After:
```python
def delete_document(document_id):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if doc:
        db.query(ParentChunk).filter(ParentChunk.source_doc_id == doc.id).delete()
        db.delete(doc)
```

**Fix 5: delete_agent non-atomic** `core/agent_manager.py`
- Problem: `delete_vector_store(agent_id)` was called before `db.delete(agent)`. If DB commit failed after vectors were deleted, vectors were lost but agent row persisted.
- Fix: Reordered — DB commit first (cache cleanup + agent delete), then vector store cleanup as best-effort after.
- Before:
```python
delete_vector_store(agent_id)  # <-- point of no return
db.delete(agent)
db.commit()                    # <-- if this fails, vectors already gone
```
- After:
```python
db.delete(agent)
db.commit()                    # <-- DB consistent first
try:
    delete_vector_store(agent_id)  # <-- best effort cleanup
except Exception as exc:
    print(f"[WARN] Vector store cleanup failed: {exc}")
```

**Fix 6: No cache invalidation on document upload** `core/cache.py` + `core/chat_service.py`
- Problem: When new documents were uploaded, old cached answers remained for up to 24 hours. Users saw stale answers.
- Fix: Added `invalidate_agent_cache(agent_id)` function to `cache.py`. Called it from `process_documents` after successful indexing.
- New function in `cache.py`:
```python
def invalidate_agent_cache(agent_id):
    db.execute(text("DELETE FROM omni_semantic_cache WHERE agent_id = :agent_id"), {"agent_id": agent_id})
    db.commit()
```
- Added to `chat_service.py` after successful `process_documents`:
```python
if status == "ready":
    update_agent_metadata(agent_id, document_count=len(doc_ids))
    invalidate_agent_cache(agent_id)  # <-- new
```

**Fix 7: Misleading Prometheus metrics** `core/monitoring.py` + `core/llm.py`
- Problem: `CACHE_HITS` / `CACHE_MISSES` counters actually measured "LLM had RAG context" vs "no RAG context" — not semantic cache behavior.
- Fix: Renamed to `RAG_CONTEXT_HIT` / `RAG_CONTEXT_MISS` to accurately reflect what they measure.
- Before:
```python
CACHE_HITS = Counter('omnicortex_rag_cache_hits_total', ...)
CACHE_MISSES = Counter('omnicortex_rag_cache_misses_total', ...)
```
- After:
```python
RAG_CONTEXT_HIT = Counter('omnicortex_rag_context_hit_total', 'LLM invocations where RAG context was available', ...)
RAG_CONTEXT_MISS = Counter('omnicortex_rag_context_miss_total', 'LLM invocations where no RAG context was available', ...)
```

#### P2 — Robustness / Edge Cases

**Fix 8: Embedding singleton not thread-safe** `core/rag/embeddings.py`
- Problem: Multiple threads calling `get_embeddings()` on first load could trigger multiple simultaneous model loads, wasting memory.
- Fix: Added `threading.Lock()` with double-checked locking pattern.
- Before:
```python
_EMBEDDINGS_INSTANCE = None
def get_embeddings():
    global _EMBEDDINGS_INSTANCE
    if _EMBEDDINGS_INSTANCE is not None:
        return _EMBEDDINGS_INSTANCE
    # ... load model (not thread-safe)
```
- After:
```python
_EMBEDDINGS_INSTANCE = None
_EMBEDDINGS_LOCK = threading.Lock()
def get_embeddings():
    global _EMBEDDINGS_INSTANCE
    if _EMBEDDINGS_INSTANCE is not None:
        return _EMBEDDINGS_INSTANCE
    with _EMBEDDINGS_LOCK:
        if _EMBEDDINGS_INSTANCE is not None:
            return _EMBEDDINGS_INSTANCE
        # ... load model (protected)
```

**Fix 9: Embedding error permanently cached** `core/rag/embeddings.py`
- Problem: `_EMBEDDINGS_ERROR` was set once and never cleared. A transient failure (network, disk) required a full process restart.
- Fix: Removed `_EMBEDDINGS_ERROR` caching entirely. Errors now raise immediately and allow retry on the next call.
- Before: `_EMBEDDINGS_ERROR = "..."; raise RuntimeError(_EMBEDDINGS_ERROR)` (cached forever)
- After: `raise RuntimeError("...")` (retryable on next call)

**Fix 10: Keyword search excludes orphan chunks** `core/rag/retrieval.py`
- Problem: `JOIN omni_documents d ON p.source_doc_id = d.id` silently dropped parent chunks with `NULL source_doc_id`.
- Fix: Changed `JOIN` → `LEFT JOIN` and updated agent filter to include `NULL` agent_id.
- Before:
```sql
FROM omni_parent_chunks p
JOIN omni_documents d ON p.source_doc_id = d.id
WHERE ... AND d.agent_id = :agent_id
```
- After:
```sql
FROM omni_parent_chunks p
LEFT JOIN omni_documents d ON p.source_doc_id = d.id
WHERE ... AND (d.agent_id = :agent_id OR d.agent_id IS NULL)
```

**Fix 11: batch_save_parent_chunks swallows errors** `core/database.py`
- Problem: On failure, only `print()` was called. In production with redirected stdout, the error was invisible.
- Fix: Replaced `print` with `logging.getLogger(__name__).error(...)`.
- Before: `print(f"⚠️ Batch save failed: {e}")`
- After: `logging.getLogger(__name__).error("Batch save parent chunks failed: %s", e)`

**Fix 12: ws_bridge.py NameError on disconnect** `ws_bridge.py`
- Problem: After the `for t in done` loop, line 388 referenced `exc` which was only defined inside the loop body. On normal WebSocket disconnect (no task exception), `exc` was undefined → `NameError`.
- Fix: Replaced with a proper `except websockets.exceptions.ConnectionClosed as closed` handler.
- Before:
```python
        # end of async with block, indentation drops
    code = getattr(exc, "code", None)        # <-- exc undefined here
    reason = getattr(exc, "reason", "")
    print(f"[call] Connection closed code={code} reason={reason!r}")
except Exception as error:
```
- After:
```python
    except websockets.exceptions.ConnectionClosed as closed:
        code = getattr(closed, "code", None)
        reason = getattr(closed, "reason", "")
        print(f"[call] Connection closed code={code} reason={reason!r}")
    except Exception as error:
```

**Fix 13: update_agent truthy check on name** `core/agent_manager.py`
- Problem: `if name:` rejected empty string updates. Passing `name=""` would not update the name, inconsistent with all other fields using `is not None`.
- Fix: Changed to `if name is not None:`.
- Before: `if name:`
- After: `if name is not None:`

**Fix 14: monitoring ConfigLoader caching bug** `core/monitoring.py`
- Problem: `if ConfigLoader._model_config:` is falsy for `{}` (empty dict). If the YAML file was empty, it re-read the file on every call.
- Fix: Changed to `if ConfigLoader._model_config is not None:`.
- Before: `if ConfigLoader._model_config:`
- After: `if ConfigLoader._model_config is not None:`

**Fix 15: WhatsApp mutable default argument** `core/whatsapp.py`
- Problem: `send_flow_message(data: dict = {})` — shared mutable default across all calls.
- Fix: Changed to `data: dict = None` with `data or {}` at usage site.
- Before: `def send_flow_message(..., data: dict = {}):`
- After: `def send_flow_message(..., data: dict = None):` + `"data": data or {}`

**Fix 16: WhatsApp missing title truncation** `core/whatsapp.py`
- Problem: `send_interactive_message` passed button titles as-is without truncation. WhatsApp rejects titles > 20 chars. Also missing the 3-button limit.
- Fix: Added `buttons[:3]` limit and `[:20]` title truncation.
- Before:
```python
for btn in buttons:
    button_actions.append({"type": "reply", "reply": {"id": btn.get("id"), "title": btn.get("title")}})
```
- After:
```python
safe_buttons = buttons[:3]
for btn in safe_buttons:
    button_actions.append({"type": "reply", "reply": {"id": btn.get("id"), "title": btn.get("title", "")[:20]}})
```

#### Dead Code Cleanup

| Item | Action | Reason |
|------|--------|--------|
| `from core.graph import create_rag_agent` in api.py | **REMOVED** | Never called in any route handler |
| `PrometheusMiddleware` import in api.py | **REMOVED** | Hand-written `metrics_middleware` duplicates it; `PrometheusMiddleware` was never added to the app |
| `tool/` package | **KEPT** | Retained for API calls, Web Search, and Unsplash image picker per user requirement |

---

## 2026-03-20 — Session 2: Multi-Mode Voice Pipeline Implementation

### 2026-03-20 | Prerequisite Fix

**File:** `api.py:2799`

| Before | After |
|--------|-------|
| `await asyncio.to_thread(verify_bearer_token, token, x_user_id or None)` | `await verify_bearer_token(token, x_user_id or None)` |

**Reason:** `verify_bearer_token` was made async in Session 1 (auth.py rewrite to httpx). Wrapping an async function in `asyncio.to_thread()` fails silently — the coroutine is never awaited.

---

### 2026-03-20 | New Files Created (8 files)

#### 1. `core/voice/voice_protocol.py` — Shared Types & Constants
- `VoiceMode` enum: `personaplex`, `lfm`, `cascade`
- `SessionState` enum: `listening`, `thinking`, `speaking`, `idle`
- `VoiceSession` dataclass: session_id, agent_id, mode, user_id, sample_rate, voice_prompt, text_prompt, state, system_prompt, agent_name, model_selection
- Sample rate constants: GATEWAY_RATE=8000, PERSONAPLEX_RATE=24000, LFM_INPUT_RATE=16000, BIGVGAN_OUTPUT_RATE=22050
- WS message types: `transcript`, `answer`, `status`, `error`, `session`, `control`

#### 2. `core/voice/resampler.py` — Audio Utilities
- `Resampler(src_rate, dst_rate)` — torch Resample with numpy linear-interpolation fallback
- `pcm16_bytes_to_float32(bytes) -> np.ndarray`
- `float32_to_pcm16_bytes(np.ndarray) -> bytes`
- Extracted from `ws_bridge.py:154-196` pattern

#### 3. `core/voice/asr_engine.py` — faster-whisper ASR Singleton
- `ASREngine(model_size, device)` with lazy model load
- `async transcribe(pcm_float32, sample_rate) -> (text, confidence)` via `run_in_executor`
- `async get_asr_engine()` — double-checked locking with `asyncio.Lock`
- Config: `VOICE_ASR_MODEL` (default "base.en"), `VOICE_ASR_DEVICE` (default "cuda")

#### 4. `core/voice/vocoder_engine.py` — BigVGAN v2 Vocoder Singleton
- `VocoderEngine(device)` with lazy BigVGAN v2 load
- `async synthesize(mel) -> np.ndarray` — mel-to-waveform via executor
- `async tts_to_audio(text) -> bytes` — LFM2.5 `text_to_speech()` fallback
- `async get_vocoder_engine()` — double-checked locking singleton
- Model: `nvidia/bigvgan_v2_22khz_80band_256x`, output 22050 Hz

#### 5. `core/voice/mode_personaplex.py` — Mode 1: PersonaPlex + Reasoner
- 3 concurrent asyncio tasks:
  - `client_to_personaplex`: relay audio upstream + tee to reasoner queue (zero-latency on main path; drops if queue full)
  - `personaplex_to_client`: relay audio downstream, decode kind bytes
  - `reasoner_loop`: drain queue -> energy VAD -> faster-whisper ASR -> intent detection -> `process_question_voice()` -> drip-feed text to PersonaPlex
- `_drip_feed_text()`: 20 chars per 80ms as PersonaPlex kind=2 text frames
- `_is_query_intent()`: regex heuristic (what/how/when/who/where/why/explain/tell me/describe)
- `_simple_energy_vad()`: energy-based utterance boundary detection
- Raises `ConnectionError` on PersonaPlex unreachable -> api.py catches and falls back to cascade

#### 6. `core/voice/mode_lfm.py` — Mode 2: LFM2.5 Interleaved
- Utterance-based loop: receive audio -> VAD -> resample 8k->16k -> LFM2.5 `speech_to_text()` -> intent check -> RAG grounding or LFM conversational response -> LFM2.5 `text_to_speech()` -> resample 24k->8k -> send
- Reuses existing `core/voice/liquid_voice.py` singleton (`get_voice_engine()`)
- Query-intent utterances routed through `process_question_voice()` for RAG grounding

#### 7. `core/voice/mode_cascade.py` — Mode 3: STT -> RAG+LLM -> TTS
- Classic sequential pipeline per utterance:
  1. Audio + VAD -> 8kHz -> 16kHz -> faster-whisper ASR
  2. `process_question_voice(transcript)` -> grounded answer
  3. LFM2.5 `tts_to_audio(answer)` -> resample -> 8kHz PCM16
- Simplest mode; good for testing the full RAG+LLM chain with voice

#### 8. `core/voice_chat_service.py` — Voice-Optimized Question Processing
- `process_question_voice()` — streamlined `process_question()` for voice:
  - **SKIP:** `validate_input()`, `_rule_based_agent_reply()`, `check_cache()`/`save_to_cache()`, `enforce_canonical_media_tags()`, `validate_output()`, media inventory injection
  - **KEEP:** `mask_pii()`, `hybrid_search()` + `format_context()`, `invoke_chain()`, `save_message()`
  - **CHANGED:** `channel_name="VOICE"`, `channel_type="TRANSACTIONAL"`
  - **ADDED:** `_strip_media_tags()` to remove unspeakable `[IMAGE:...]`, `[VIDEO|...]` tags

---

### 2026-03-20 | Modified Files (3 files)

#### 1. `core/config.py` — Voice Pipeline Constants (appended after line 136)
```
VOICE_DEFAULT_MODE      = "personaplex"
VOICE_ASR_MODEL         = "base.en"
VOICE_ASR_DEVICE        = "cuda"
VOICE_VOCODER_DEVICE    = "cuda"
VOICE_DRIP_FEED_CHARS   = 20
VOICE_DRIP_FEED_INTERVAL_MS = 80
VOICE_VAD_SILENCE_MS    = 600
VOICE_VAD_ENERGY_THRESHOLD  = 0.01
VOICE_REASONER_QUEUE_SIZE   = 200
VOICE_PERSONAPLEX_FALLBACK  = true
```

#### 2. `core/voice/__init__.py` — Added Exports
```python
from .voice_protocol import VoiceMode, VoiceSession, SessionState
```

#### 3. `api.py` — Added `/ws/voice/{agent_id}` WebSocket Route (~110 lines)
- Query params: `mode` (default "personaplex"), `token`, `voice_prompt`, `sample_rate`, `x_user_id`
- Auth via existing `_authenticate_voice_websocket()`
- Resolves agent system_prompt, name, model_selection via `get_agent()`
- Creates `VoiceSession` and dispatches to mode handler
- PersonaPlex fallback: catches `ConnectionError` -> cascade mode with status message
- Sends `MSG_SESSION` frame on connect with session_id, mode, agent info

---

### 2026-03-20 | WebSocket Protocol — `/ws/voice/{agent_id}`

**Client -> Server:**

| Frame | Content | Description |
|-------|---------|-------------|
| Binary | PCM16-LE mono 8kHz | Audio chunk |
| Text JSON | `{"type":"control","action":"stop"}` | End session |

**Server -> Client:**

| Frame | Content | Description |
|-------|---------|-------------|
| Binary | PCM16-LE mono 8kHz | Audio response |
| Text JSON | `{"type":"session",...}` | On connect — session_id, mode, agent |
| Text JSON | `{"type":"transcript","text":"...","final":bool}` | ASR transcript |
| Text JSON | `{"type":"answer","text":"..."}` | RAG+LLM answer text |
| Text JSON | `{"type":"status","status":"listening\|thinking\|speaking\|idle"}` | State change |
| Text JSON | `{"type":"error","message":"..."}` | Error |

---

## 2026-03-26 — Session 3: pgvector Text Injection + Bridge Fixes

### 2026-03-26 | PersonaPlex pgvector Text Injection (2 changes to mode_personaplex.py)

#### Change 1: Phase 1 — pgvector Prefill at Session Init

**File:** `core/voice/mode_personaplex.py` (inserted before `_build_personaplex_url()` call)

**What:** Before connecting to PersonaPlex, fetches top-5 knowledge chunks from pgvector and injects them into `text_prompt`. PersonaPlex's KV-cache prefills with domain knowledge so Helium speaks with full context from the first word.

**Flow:**
```
handle_personaplex() entry
  ├─ get_agent(agent_id) → system_prompt (if not already set)
  ├─ hybrid_search("account information loan balance", agent_id, top_k=5)
  ├─ text_prompt = system_prompt + "\n\nKnowledge:\n" + chunks[:1000]
  └─ _build_personaplex_url(session) — now uses enriched text_prompt
```

**Key details:**
- `hybrid_search()` runs in executor (sync function, I/O-bound)
- Wrapped in try/except — prefill failure is non-fatal, call continues without knowledge
- Max 1000 chars to avoid overloading PersonaPlex text prompt buffer
- Agent config fetched only if `text_prompt` AND `system_prompt` are both empty (avoids overwriting client-provided prompts)

#### Change 2: Phase 4 — Dynamic pgvector Drip-Feed on Query

**File:** `core/voice/mode_personaplex.py` (inserted in `reasoner_loop()` after intent detection, before LLM call)

**What:** When a query is detected, FIRST drip-feeds raw pgvector chunks for immediate context (~1s), THEN runs the existing LLM pipeline for a refined answer. PersonaPlex receives context twice — fast raw chunks first, then polished LLM answer.

**Flow:**
```
reasoner_loop() → query detected
  ├─ NEW: hybrid_search(transcript, agent_id, top_k=3)
  │    └─ join chunks[:400] → split 20-char pieces → drip-feed at 80ms
  └─ EXISTING: process_question_voice() → RAG+LLM → drip-feed LLM answer
```

**Key details:**
- `loop = asyncio.get_running_loop()` moved before Phase 4 to avoid UnboundLocalError (Python scoping: assignment at line 376 made `loop` local to `reasoner_loop()`, but Phase 4 code referenced it before that assignment)
- Max 400 chars per drip-feed to avoid overloading Helium mid-conversation
- Wrapped in try/except — drip-feed failure doesn't block LLM path

**Bug fixed during implementation:**
- `loop` variable scoping: Phase 4 used `loop.run_in_executor()` but `loop` was assigned later in the same function (line 376). Python treats any locally-assigned variable as local for the entire function scope, causing `UnboundLocalError`. Fixed by moving `loop = asyncio.get_running_loop()` to right after intent detection, before Phase 4 code.

---

### 2026-03-26 | bridge.py Text Display Fixes

**File:** `bridge.py` — `log_text()` function

#### Fix 1: SentencePiece `▁` underscores in transcript display

**Problem:** Moshi's SentencePiece tokenizer produces tokens like `▁Hello,▁this▁is▁Sarah`. The `log_text()` function printed these raw, showing `▁` (U+2581) characters in the terminal.

**Fix:** Added `.replace("\u2581", " ")` before display.

- Before: `▁Hey,▁let▁me▁know▁if▁you▁have▁any▁questions.`
- After: `Hey, let me know if you have any questions.`

#### Fix 2: Text tokens printed on infinite single line

**Problem:** `log_text()` used `end=""` causing all tokens to concatenate on one line, forcing horizontal scrolling across hundreds of characters.

**Fix:** Added newline after sentence-ending punctuation (`.!?\n`).

- Before: `end=""`
- After: `end_char = "\n" if any(c in text for c in ".!?\n") else ""`

---

### 2026-03-26 | bridge.py Enhanced Diagnostics

Added diagnostic logging to debug caller audio not reaching Moshi:

1. **FS PCM RMS logging:** `fs_to_moshi()` now logs RMS of first 5 + every 250th frame from FreeSWITCH (instead of only first 3). Revealed all frames had rms=0.0000 — phone mic was muted.

2. **Pump silence gap:** `audio_pump()` now logs `last_fs=X.Xs ago` showing how long since the last real FS frame. Confirms whether FS audio is continuously arriving.

---

### 2026-03-26 | PROJECT.md Updated

Added PersonaPlex 4-Phase voice flow diagram showing:
- Phase 1 (Session Init) → Phase 2 (KV-Cache Prefill) → Phase 3 (Live Conversation) → Phase 4 (Dynamic Drip-Feed)
- Audio rate conversion chain (8kHz ↔ 24kHz ↔ 16kHz)
- FreeSWITCH telephony bridge flow (bridge.py)

---

## 2026-03-27 — Session 4: Runtime Safety and Security Hardening

### Startup/Lifecycle
- Moved DB initialization out of import-time execution in `api.py` and into `lifespan()`.
- Updated `core.database.init_db()` to return an error string on failure instead of raising from import-time paths.
- Added auth HTTP client lifecycle management (`init_http_client()`/`close_http_client()`) and wired it to FastAPI lifespan startup/shutdown.

### Agent Deletion Atomicity
- Implemented soft-delete flow for agents (`Agent.deleted`), with reads/updates filtering out soft-deleted rows.
- Replaced direct hard-delete path with:
    1. mark `deleted=True` + commit
    2. background retriable vector cleanup
    3. hard-delete only after vector cleanup succeeds
- This prevents DB/vector ordering races and avoids immediate orphan-vector risk.

### API/Voice WebSocket Robustness
- Fixed `sample_rate` parsing to handle invalid values safely with fallback to 8000.
- Removed `_json` alias risk by using module-scope `json` in all websocket send/error paths.
- Replaced client-facing exception leaks in cascade/LFM handlers with generic error text.

### Bridge Security and Stability
- Removed hardcoded bridge API keys from source; now read from `MOSHI_API_KEY` and fail fast if missing.
- Added UUID validation/sanitization before command usage.
- Added quoting for FS CLI command arguments that include filesystem paths.
- Added `t_fs` to `core_tasks` so disconnects from `fs_to_moshi` terminate session waits correctly.
- Made PCM debug capture opt-in (`DEBUG_DUMP_PCM`/`DEBUG_WAV`) and bounded (`MAX_DEBUG_PCM_BYTES`) to prevent unbounded growth.

### Core Reliability
- `core/agent_config.py`: hardened fallback path creation, now returns `None` when no writable dir exists and caller handles that safely.
- `core/cache.py`: `invalidate_agent_cache` now accepts `Optional[str]` and uses explicit `None` branching.
- `core/rag/embeddings.py`: fixed false fallback warning by comparing normalized primary model names.
- `core/rag/retrieval.py`: replaced racy global failure reason with lock-protected, time-throttled failure logging and reset-on-success.

### Metrics Compatibility
- Renamed RAG context counters to Prometheus plural forms:
    - `omnicortex_rag_context_hits_total`
    - `omnicortex_rag_context_misses_total`
- Added deprecated compatibility counters:
    - `omnicortex_rag_cache_hits_total`
    - `omnicortex_rag_cache_misses_total`
- Both new and deprecated counters are emitted in parallel for migration safety.

### Voice Engine Fixes
- `core/voice/asr_engine.py`:
    - Added per-instance thread lock for model loading (double-checked pattern)
    - Resamples non-16kHz input before transcription
    - Returns `NaN` confidence sentinel when no segments are produced
- `core/voice/mode_personaplex.py`:
    - `_send_json` now logs failures instead of swallowing silently
    - conversation history trimming now mutates list in place
- `core/voice/vocoder_engine.py`:
    - Added per-instance load lock and load-failure flag to prevent concurrent retries/retry storms

### Voice Chat Privacy
- `core/voice_chat_service.py` now sends masked `safe_question` (not raw question) to ClickHouse logging.
- Agent lookup exceptions are logged and fallback naming is consistent (`"default"`).
- Media-tag stripping regex updated to support multi-line/inner-bracket tag payloads.

### Standalone LFM Server
- `start_lfm.py` now runs `lfm.ensure_loaded()` via `asyncio.to_thread()` to avoid blocking the event loop.
- Added `_rag_session_lock` to prevent concurrent `aiohttp.ClientSession` creation races.

### Snapshot Server Hardening (`tmp/server_omni_snapshot.py`)
- Replaced fragile tar extraction checks with `Path.relative_to()` containment checks.
- Rejected absolute archive members and symlink/hardlink entries in tar extraction.
- Added robust peer-port extraction with safe fallback when `peername` is missing.
- Replaced missing voice prompt exception crash path with websocket error response + graceful close.
- Narrowed `self.lock` scope to shared model setup/reset only; handshake/task loops now run outside lock.
- Reworked liveness check to use ping-based checks instead of consuming `ws.receive()` messages.
- Added SSRF protections for call-trigger proxy:
    - scheme validation
    - DNS resolution checks
    - blocked local/private/metadata ranges
    - enforced host/CIDR allowlist requirement
- Replaced assert-based path validation with explicit `FileNotFoundError` checks.
- Set static serving to `follow_symlinks=False`.

### Misc
- Clarified internal/external port logging in `test_py.py` startup output.
