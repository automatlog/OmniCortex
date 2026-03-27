# OmniCortex — Project Documentation

## Project Overview

OmniCortex is a multi-agent RAG (Retrieval-Augmented Generation) platform built with FastAPI, LangChain, pgvector, and vLLM-compatible LLM backends. It enables creating configurable AI agents, each with their own knowledge base, system prompts, and media assets — exposed via REST API, WebSocket, and WhatsApp Business API.

## Architecture

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

### Module Dependency Chain

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

## Key Features

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

## Strengths

1. **Clean RAG pipeline** — Parent-child splitting + hybrid search + RRF + optional cross-encoder reranking
2. **Agent isolation** — Per-agent vector stores, configs, media, and conversation history
3. **Graceful degradation** — Embedding model fallback chain, optional ClickHouse, optional reranker
4. **Schema migration** — `ensure_schema_updates()` handles column additions idempotently
5. **Connection pooling** — SQLAlchemy pool with pre-ping and recycling
6. **ClickHouse buffering** — Thread-safe batch writer with overflow protection
7. **Canonical media tag enforcement** — Normalizes LLM output before delivery

## Voice Pipeline — PersonaPlex 4-Phase Flow

```
┌──────────────────────────────────────────────────────────────────────┐
│                     /ws/voice/{agent_id}                             │
│                     mode=personaplex                                 │
└──────────┬───────────────────────────────────────────────────────────┘
           │
           ▼
┌─── Phase 1: Session Init ───────────────────────────────────────────┐
│                                                                      │
│  get_agent(agent_id) ──→ system_prompt                              │
│          │                                                           │
│          ▼                                                           │
│  hybrid_search("account info...", agent_id, top_k=5)                │
│          │                                                           │
│          ▼                                                           │
│  text_prompt = system_prompt + "\n\nKnowledge:\n" + chunks[:1000]   │
│                                                                      │
└──────────┬───────────────────────────────────────────────────────────┘
           │
           ▼
┌─── Phase 2: KV-Cache Prefill (automatic) ───────────────────────────┐
│                                                                      │
│  PersonaPlex WS connect ──→ send init {voice_prompt, text_prompt}   │
│  Helium prefills KV-cache with knowledge ──→ ready to speak         │
│                                                                      │
└──────────┬───────────────────────────────────────────────────────────┘
           │
           ▼
┌─── Phase 3: Live Conversation (3 concurrent tasks) ─────────────────┐
│                                                                      │
│  Task 1: client_to_personaplex                                       │
│    Client PCM 8kHz ──→ resample 24kHz ──→ Opus encode               │
│    ──→ kind=1 frame ──→ PersonaPlex                                  │
│    Also tees audio to reasoner queue (non-blocking)                  │
│                                                                      │
│  Task 2: personaplex_to_client                                       │
│    PersonaPlex ──→ kind=0: handshake (log)                           │
│                ──→ kind=1: Opus decode ──→ resample 8kHz ──→ Client  │
│                ──→ kind=2: text token ──→ transcript JSON to Client  │
│                ──→ kind=3: special (ignore)                          │
│                                                                      │
│  Task 3: reasoner_loop                                               │
│    Drain audio queue ──→ energy VAD ──→ utterance boundary?          │
│      │ No  → continue accumulating                                   │
│      │ Yes → resample 16kHz ──→ faster-whisper ASR                   │
│              │                                                       │
│              ▼                                                       │
│         transcript ──→ is_query_intent()?                            │
│           │ No  → continue (non-query utterance)                     │
│           │ Yes → ┌──────────────────────────────┐                   │
│                   │  PHASE 4 TRIGGERED           │                   │
│                   └──────────┬───────────────────┘                   │
│                              ▼                                       │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
                               ▼
┌─── Phase 4: Dynamic Drip-Feed ──────────────────────────────────────┐
│                                                                      │
│  Step A — Fast pgvector injection (~1s):                             │
│    hybrid_search(transcript, agent_id, top_k=3)                     │
│    ──→ join chunks[:400] ──→ split 20-char pieces                   │
│    ──→ drip-feed to PersonaPlex at 80ms cadence (kind=2 frames)     │
│                                                                      │
│  Step B — LLM-refined answer (slower):                               │
│    process_question_voice(transcript, agent_id, history)             │
│    ──→ hybrid_search + invoke_chain (RAG + LLM)                     │
│    ──→ drip-feed LLM answer to PersonaPlex at 80ms cadence          │
│    ──→ update conversation_history                                   │
│                                                                      │
│  PersonaPlex receives context TWICE:                                 │
│    1. Raw chunks (fast, immediate knowledge)                         │
│    2. LLM answer (refined, contextual response)                      │
│                                                                      │
│  ──→ Back to Phase 3                                                 │
└──────────────────────────────────────────────────────────────────────┘
```

### Audio Rate Conversion Chain

```
Client (8kHz PCM16)
  ──→ Resampler 8k→24k ──→ OpusCodec.encode() ──→ PersonaPlex (24kHz Opus)
  ←── Resampler 24k→8k ←── OpusCodec.decode() ←── PersonaPlex (24kHz Opus)

Reasoner sidecar:
  Client audio tee (8kHz) ──→ Resampler 8k→16k ──→ faster-whisper ASR
```

### FreeSWITCH Telephony Bridge (bridge.py — separate process)

```
Phone (PCMU/8kHz)
  ──→ FreeSWITCH (mod_audio_stream, L16/16kHz)
  ──→ bridge.py WS :8001
  ──→ resample 16k→24k ──→ Opus encode ──→ Moshi/PersonaPlex (RunPod:8998)

Moshi response:
  ──→ Opus decode ──→ resample 24k→8k
  ──→ edge-tts (text tokens → WAV) ──→ uuid_broadcast ──→ caller hears speech
```

## Areas for Improvement

See the audit sections below for full details. Key areas:
- PII masking inconsistency (masked for search, raw sent to LLM)
- Blocking sync HTTP in async auth handler
- Missing vector cleanup on document deletion
- No cache invalidation on document upload
- Misleading Prometheus metric names
- Thread safety gaps in embedding singleton
- Dead code and unused imports

---

## OmniCortex — Full Flow, Logic & Edit-Risk Audit

### 1. Application Startup Flow

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

### 2. Request Flow — `/query` (Main Chat Pipeline)

```
POST /query
  ├─ Auth: get_api_key (Depends) → sync HTTP to AUTH_VERIFY_URL [FIXED → async httpx]
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

### 3. Critical Logic Breaks

#### P0 — Security / Data Integrity (FIXED)

| # | Issue | File(s) | Status |
|---|-------|---------|--------|
| 1 | PII sent to LLM — `mask_pii` creates `safe_question` but raw question was passed to `invoke_chain` | chat_service.py:324 | **FIXED** |
| 3 | Sync HTTP blocks event loop — `auth.py` used `requests.get()` inside async `get_api_key` | auth.py | **FIXED** |
| 4 | `time.sleep(0.1)` in async handler — mock mode used sync sleep | api.py:868 | **FIXED** |

#### P1 — Data Quality / Consistency (FIXED)

| # | Issue | File(s) | Status |
|---|-------|---------|--------|
| 6 | `delete_document` doesn't delete vectors — leaves embeddings in pgvector | database.py | **FIXED** |
| 7 | `delete_agent` non-atomic — vector store deletion and DB deletion were separate | agent_manager.py | **FIXED** |
| 8 | No cache invalidation on doc upload — stale answers served up to 24h | cache.py + chat_service.py | **FIXED** |
| 10 | Misleading Prometheus metrics — `CACHE_HITS`/`CACHE_MISSES` measured RAG context not cache | llm.py + monitoring.py | **FIXED** |

#### P2 — Robustness / Edge Cases (FIXED)

| # | Issue | File(s) | Status |
|---|-------|---------|--------|
| 11 | Embedding singleton not thread-safe on first load | rag/embeddings.py | **FIXED** |
| 12 | Embedding error permanently cached — transient failure needs restart | rag/embeddings.py | **FIXED** |
| 13 | Keyword search excludes orphan chunks — JOIN drops NULL source_doc_id | rag/retrieval.py | **FIXED** |
| 14 | `batch_save_parent_chunks` swallows errors — returns `{}` silently | database.py | **FIXED** |
| 15 | `ws_bridge.py` NameError — references undefined `exc` on normal disconnect | ws_bridge.py | **FIXED** |
| 17 | `update_agent` truthy check on name — `if name:` rejects empty string | agent_manager.py | **FIXED** |
| 18 | `monitoring.ConfigLoader` caching bug — truthiness check on `{}` | monitoring.py | **FIXED** |

### 4. File-by-File Edit Risk Map

#### EXTREME RISK (changes break the entire system)
| File | Why |
|------|-----|
| api.py | Monolith with all routes, 20+ Pydantic models, ~30 helpers with inline logic |
| core/__init__.py | Facade re-exporting 33 symbols; removing any breaks imports globally |
| core/config.py | Every constant consumed by multiple modules |
| core/database.py | ORM models + CRUD + session factory used by virtually every module |

#### HIGH RISK (changes break the chat pipeline)
| File | What breaks |
|------|-------------|
| core/chat_service.py | `process_question` is the critical path for ALL queries |
| core/llm.py | `PROMPT_TEMPLATE` is the ACTUAL system prompt; `invoke_chain` called every turn |
| core/rag/retrieval.py | `hybrid_search` is the sole retrieval function |
| core/rag/vector_store.py | Collection naming `omni_agent_{id}` is hardcoded; LangChain internal tables |
| core/auth.py | Changing return shape breaks all 20+ authenticated endpoints |
| core/agent_manager.py | `get_agent` return dict shape consumed by 4+ modules |

#### MEDIUM RISK (changes break specific features)
| File | Scope |
|------|-------|
| core/response_parser.py | Tag syntax change breaks WhatsApp + frontend |
| core/processing/chunking.py | Chunk size changes affect retrieval quality |
| core/cache.py | Threshold/TTL changes affect answer freshness |
| core/clickhouse.py | Column order must match ClickHouse DDL exactly |
| core/whatsapp.py | Webhook return format change breaks processing |
| core/whatsapp_history.py | Module-level create_all(); race in get_or_create_session |

#### LOW RISK (isolated, changes stay contained)
| File | Notes |
|------|-------|
| core/guardrails.py | Standalone blacklist module |
| core/graph.py | Not used by main chat path |
| core/crew.py | Auxiliary CrewAI orchestration |
| core/monitoring.py | Metrics + config loader |
| core/processing/pii.py | US-centric patterns only |
| core/voice/* | REST stubs; real voice is WebSocket-only |
| core/agent_config.py | Fire-and-forget YAML writer |

### 5. Dead Code / Unused Components

| Item | Location | Status |
|------|----------|--------|
| `PrometheusMiddleware` | Imported in api.py | **REMOVED** — hand-written middleware duplicates it |
| `create_rag_agent` | Imported in api.py | **REMOVED** — never called in any route |
| `tool/` package | Entire directory | **KEPT** — repurposed for API calls, Web Search, Unsplash |
| Voice REST stubs | `/voice/transcribe`, `/voice/speak`, etc. | Present but return 501/410 |
| `core/rag/ingestion_fixed.py` | Alternative ingestion | Not called by production code |

### 6. Dependency Chain (what breaks what)

**Most dangerous edit:** `core/config.py` — root of entire dependency tree.

**Most impactful refactor:** Split `api.py` into router modules + extract inline business logic into a service layer.
