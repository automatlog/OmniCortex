# OmniCortex Project Flow

Last updated: 2026-03-16

## 1. Runtime Topology

| Component | Purpose | Default Port |
|---|---|---|
| FastAPI (`api.py`) | Main API, RAG, auth, voice proxy | `8000` |
| vLLM1 | Primary text LLM backend (`MODEL_BACKENDS.default`) | `8080` |
| vLLM2 (optional) | Secondary LLM backend/profile | `8082` |
| Moshi / PersonaPlex (`moshi.server`) | Full-duplex voice engine + web UI | `8998` |
| Voice Gateway (`scripts/voice_gateway.py`) | FreeSWITCH media bridge (`/calls`) | `8099` (or `443` TLS) |
| PostgreSQL + pgvector | Primary data store and vectors | `5432` |
| ClickHouse (optional) | Usage/chat/agent-event analytics sink | `8123` |

```mermaid
flowchart LR
  A[Admin UI / Clients] --> B[FastAPI api.py :8000]
  B --> C[vLLM1 :8080]
  B --> D[vLLM2 :8082 optional]
  B --> E[(PostgreSQL + pgvector :5432)]
  B --> F[(ClickHouse :8123 optional)]
  A --> G[Moshi UI/WS :8998]
  G --> B
  H[FreeSWITCH / Dialer] --> I[Voice Gateway /calls]
  I --> B
```

## 2. Core Backend Responsibilities

- `api.py`: REST and WS endpoints, startup validation, auth/ownership enforcement, orchestration.
- `core/agent_manager.py`: agent CRUD and vector store delete on agent removal.
- `core/chat_service.py`: chat pipeline (guardrails, PII masking, cache, retrieval, LLM invoke, persistence).
- `core/rag/*`: embeddings, vector store ops, hybrid retrieval (vector + keyword + RRF, optional rerank).
- `core/llm.py`: OpenAI-compatible LLM invocation via LangChain (`MODEL_BACKENDS` driven).
- `core/database.py`: SQLAlchemy models, schema/index setup, message/document/usage storage.
- `core/clickhouse.py`: buffered async analytics writing (usage/chat/agent events).
- `scripts/voice_gateway.py`: `/calls` WS bridge between telephony media and OmniCortex `/voice/ws`.
- `personaplex/moshi/moshi/server.py`: PersonaPlex runtime, OmniCortex-aware agent/prompt fetch, UI patching.

## 3. End-to-End Flows

### 3.0 Consolidated Project Flow

```mermaid
flowchart TB
    A[Client / Admin UI / Voice Client] --> B[FastAPI api.py]

    B --> C[Bearer Auth<br/>core/auth.py]
    C --> D{Authorized?}
    D -->|No| E[403]
    D -->|Yes| F{Route Type}

    F -->|POST /agents| G[Normalize + Validate Payload]
    G --> H[create_agent<br/>core/agent_manager.py]
    H --> I[(PostgreSQL<br/>omni_agents)]
    G --> J[process_documents / process_urls]
    J --> K[parent_child_split]
    K --> L[(pgvector collection<br/>omni_agent_<id>)]
    H --> M[log_agent_event_to_clickhouse]
    M --> N[(ClickHouse AgentLogs)]
    H --> O[Optional Agent Ready Webhook]

    F -->|POST /query| P[_require_agent_access]
    P --> Q[Session Resolve/Create]
    Q --> R[process_question<br/>core/chat_service.py]
    R --> S{Semantic Cache Hit?}
    S -->|Yes| T[Return Cached Answer]
    S -->|No| U[hybrid_search<br/>core/rag/retrieval.py]
    U --> V[invoke_chain<br/>core/llm.py -> vLLM backend]
    V --> W[enforce media tags + output guardrails]
    T --> X[Save messages/history]
    W --> X
    X --> Y[(PostgreSQL<br/>messages/usage)]
    X --> Z[log_usage_to_clickhouse + log_chat_to_clickhouse]
    Z --> AA[(ClickHouse UsageLogs + ChatArchive)]
    W --> AB[QueryResponse<br/>answer + session_id + request_id]

    F -->|WS /voice/ws| AC[Voice Proxy]
    AC --> AD[Load agent prompt + optional voice context]
    AD --> AE[Moshi/PersonaPlex upstream WS]
    AE --> AF[Bidirectional audio/text relay]
```

### 3.1 Agent create and ingest flow

1. Client calls `POST /agents` with Bearer token.
2. API validates owner identity and normalizes payload (`agent_type`, `subagent_type`, prompts, model selection).
3. Agent row is created in `omni_agents`.
4. Optional ingestion runs from:
   - `file_paths` / uploaded files
   - `documents_text`
   - `scraped_data`
5. URL list triggers background `process_urls(...)`.
6. `process_documents(...)` performs:
   - extraction and text combine
   - parent-child split
   - parent chunk save in Postgres
   - child embedding + vector upsert in pgvector collection `omni_agent_<agent_id>`
7. Agent event is logged to ClickHouse (if enabled).
8. Optional outbound webhook `AGENT_READY_WEBHOOK_URL` is called.

```mermaid
flowchart LR
  A[Client POST /agents] --> B[api.py validate auth + owner]
  B --> C[Normalize payload]
  C --> D[create_agent in omni_agents]
  D --> E{Any ingest input?}
  E -->|files/text/scraped_data| F[process_documents]
  F --> G[parent_child_split]
  G --> H[Save parent chunks to Postgres]
  G --> I[Embed child chunks]
  I --> J[Upsert pgvector collection omni_agent_AGENT_ID]
  E -->|urls| K[background process_urls]
  J --> L[ClickHouse agent event]
  L --> M[Optional AGENT_READY_WEBHOOK_URL]
```

### 3.2 Text query flow (`POST /query`)

1. Request is authenticated and agent ownership is checked.
2. Session is resolved/created (daily policy per `agent + user + channel` when absent).
3. `process_question(...)` pipeline:
   - input guardrails
   - PII masking
   - rule-based greeting/end response from agent-specific `conversation_starters` / `conversation_end`
   - semantic cache lookup
   - hybrid retrieval (`hybrid_search`)
   - context/history formatting
   - LLM call (`invoke_chain`) to selected backend/model
   - output guardrails
   - cache save + message persistence
4. Response tags are normalized and rendered for frontend (`[image]`, `[video]`, `[document]`, `[buttons]`, etc).
5. Usage/chat analytics are written to Postgres and optionally ClickHouse.

```mermaid
flowchart TB
  A[User sends query] --> B[POST /query]
  B --> C[Auth + agent ownership + session resolve]
  C --> D[process_question]
  D --> E[Input guardrails + PII mask]
  E --> F{Cache hit?}
  F -->|Yes| G[Return cached answer]
  G --> H[Save messages in Postgres]
  H --> I[Write chat/usage analytics]
  F -->|No| J[Hybrid retrieval vector + keyword + RRF]
  J --> K[Build context + history]
  K --> L[Invoke vLLM backend]
  L --> M[Output guardrails]
  M --> N[Save cache + messages]
  N --> I
  I --> O[QueryResponse to user]
```

### 3.3 Voice flow through OmniCortex proxy (`/voice/ws`)

1. Voice client connects to `ws://<api>:8000/voice/ws` with token (query/header), `agent_id`, `voice_prompt`.
2. API authenticates token via external auth callback.
3. If `agent_id` is present, API loads agent system prompt.
4. If `VOICE_RAG_ENABLED=true`, API retrieves top-k vector context and appends it into voice prompt.
5. API opens upstream WS to Moshi `/api/chat` and relays binary frames bidirectionally.
6. Client receives AI audio frames and text/control frames as streamed by Moshi.

```mermaid
flowchart TB
  A[Voice client] --> B[WS connect /voice/ws]
  B --> C[Bearer auth verify]
  C --> D[Load agent system prompt]
  D --> E{VOICE_RAG_ENABLED?}
  E -->|Yes| F[Retrieve top-k voice context]
  F --> G[Append context to text_prompt]
  E -->|No| G
  G --> H[Open upstream WS to Moshi /api/chat]
  H --> I[Forward client audio frames]
  H --> J[Forward Moshi audio/text/control frames]
  I --> K[Bi-directional streaming loop]
  J --> K
```

### 3.4 Telephony flow via Voice Gateway (`/calls`)

1. FreeSWITCH/dialer connects to Voice Gateway endpoint (`/calls`).
2. Gateway opens upstream WS to OmniCortex `/voice/ws` with agent/token/voice params.
3. Audio bridge behavior:
   - inbound FS PCM16 -> resample -> Opus -> Moshi audio frame `0x01`
   - upstream audio frame `0x01` -> Opus decode -> resample -> PCM16 back to FS
   - text/control frames are forwarded or logged based on config
4. This keeps telephony media adaptation outside `api.py`.

```mermaid
flowchart TB
  A[FreeSWITCH / Dialer] --> B[Voice Gateway /calls]
  B --> C[Open upstream /voice/ws]
  C --> D[FastAPI voice proxy]
  D --> E[Moshi /api/chat]
  A --> F[Inbound PCM16 or Moshi frame]
  F --> G[Gateway transcode PCM16 to Opus frame 0x01]
  G --> E
  E --> H[Audio frame 0x01 returned]
  H --> I[Gateway Opus decode + resample]
  I --> J[Outbound PCM16 to FreeSWITCH]
  E --> K[Text/control frames]
  K --> L[Forward or log]
```

### 3.5 Moshi UI agent mode flow

1. Browser opens Moshi UI (`:8998`).
2. UI patch (enabled by default) replaces stock examples with OmniCortex agents.
3. UI calls:
   - `/api/agents` (Moshi server -> OmniCortex `/agents`)
   - `/api/agent-prompt` (Moshi server -> OmniCortex `/agents/{id}` + `/agents/{id}/voice-context`)
4. Voice websocket `/api/chat` carries selected `agent_id` and optional `omni_bearer`.

```mermaid
flowchart LR
  A[Browser opens Moshi UI :8998] --> B[Injected UI patch]
  B --> C[Examples label becomes Agents]
  C --> D[/api/agents]
  D --> E[Moshi server fetch_agents]
  E --> F[OmniCortex /agents]
  C --> G[Agent chip selected]
  G --> H[/api/agent-prompt]
  H --> I[Moshi fetch_agent_prompt]
  I --> J[OmniCortex /agents/id + /voice-context]
  J --> K[Text prompt textarea populated]
  K --> L[WS /api/chat with agent_id]
```

### 3.6 Voice Diagrams (Separated)

#### 3.6.1 Voice WS sequence (`/voice/ws`)

```mermaid
sequenceDiagram
    participant VC as Voice Client
    participant API as OmniCortex API (/voice/ws)
    participant AUTH as Auth Verify URL
    participant PG as PostgreSQL/pgvector
    participant MOSHI as Moshi (/api/chat)

    VC->>API: WS connect + bearer + agent_id + voice_prompt
    API->>AUTH: verify_bearer_token(...)
    AUTH-->>API: OK / 403
    API->>PG: Load agent prompt (+ optional voice context)
    API->>MOSHI: Open upstream WS /api/chat (text_prompt)
    VC->>API: audio frames
    API->>MOSHI: forward audio frames
    MOSHI-->>API: audio/text/control frames
    API-->>VC: relay frames (bi-directional stream)
```

#### 3.6.2 Telephony bridge sequence (`/calls` via Voice Gateway)

```mermaid
sequenceDiagram
    participant FS as FreeSWITCH/Dialer
    participant GW as Voice Gateway (/calls)
    participant API as OmniCortex (/voice/ws)
    participant MOSHI as Moshi (/api/chat)

    FS->>GW: media WS connect
    GW->>API: WS connect /voice/ws (agent/token params)
    API->>MOSHI: Open /api/chat
    FS->>GW: inbound PCM16
    GW->>GW: resample + opus encode (frame 0x01)
    GW->>API: send audio frame
    API->>MOSHI: forward frame
    MOSHI-->>API: response audio frame
    API-->>GW: forward frame
    GW->>GW: opus decode + resample to PCM16
    GW-->>FS: outbound PCM16
```

#### 3.6.3 Moshi UI agent mode sequence

```mermaid
sequenceDiagram
    participant UI as Browser (Moshi UI)
    participant MS as Moshi Server
    participant API as OmniCortex API

    UI->>MS: Open UI (:8998)
    MS-->>UI: Patched agent-mode UI
    UI->>MS: GET /api/agents
    MS->>API: GET /agents
    API-->>MS: Agent list
    MS-->>UI: Render agent chips
    UI->>MS: GET /api/agent-prompt?agent_id=...
    MS->>API: GET /agents/{id} + /agents/{id}/voice-context
    API-->>MS: prompt + context
    MS-->>UI: Fill prompt textarea
    UI->>MS: WS /api/chat (agent_id)
```

## 4. Data and Isolation Model

- Agent ownership isolation is enforced at API level per Bearer identity.
- Vector collection isolation is per-agent: `omni_agent_<agent_id>`.
- Core tables:
  - `omni_agents`
  - `omni_documents`
  - `omni_messages`
  - `omni_usage`
  - `omni_parent_chunks`
  - `omni_semantic_cache`

### 4.1 Agent YAML snapshots

- Path: `storage/agents/<agent_name>/config.yaml`
- Written/updated on:
  - `POST /agents` (event `create`)
  - `PUT /agents/{id}` (event `update`)
  - successful LLM usage logging (usage totals sync)
- Contains:
  - current agent configuration snapshot
  - lifecycle event history (`create`/`update`)
  - cumulative token totals:
    - `total_input_tokens` (prompt tokens)
    - `total_output_tokens` (completion tokens)
    - `total_query_tokens`
    - `total_rag_query_tokens`

## 5. Auth and Security Boundaries

- Main API auth: external bearer verification (`AUTH_VERIFY_URL`).
- `/voice/ws` also requires bearer token.
- Moshi auth is separate (`MOSHI_API_TOKEN`) for its own endpoints.
- Moshi -> OmniCortex calls can use server-side key (`OMNICORTEX_API_KEY`) or per-user `omni_bearer`.

## 6. Observability and Health

- `/health` reports database, LLM backend, and Moshi status with short cache TTL.
- Query traces written to `storage/logs/query_trace.log`.
- WhatsApp logs written to `storage/logs/whatsapp.log`.
- ClickHouse writer uses in-memory buffers with periodic flush and drop-on-unavailable behavior.

```mermaid
flowchart LR
  A[Runtime Events] --> B[Postgres logs/messages]
  A --> C[In-memory ClickHouse buffers]
  C --> D{ClickHouse reachable?}
  D -->|Yes| E[Insert UsageLogs, ChatArchive, Agent events]
  D -->|No| F[Drop batch + warning log]
  A --> G[storage/logs/query_trace.log]
  A --> H[storage/logs/whatsapp.log]
```

## 7. Recommended Startup Order

1. Start PostgreSQL (+ pgvector) and optional ClickHouse.
2. Start vLLM1 on `8080`.
3. Start FastAPI on `8000`.
4. Start Moshi on `8998` (if voice needed).
5. Start Voice Gateway on `8099` or `443` (if FreeSWITCH integration is needed).

```mermaid
flowchart TD
  A[Start PostgreSQL/pgvector] --> B[Start ClickHouse optional]
  B --> C[Start vLLM1 :8080]
  C --> D[Start FastAPI :8000]
  D --> E[Start Moshi :8998 optional]
  E --> F[Start Voice Gateway :8099 or :443 optional]
```
