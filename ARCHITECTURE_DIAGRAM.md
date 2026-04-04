# PersonaPlex Architecture Diagram

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         USER BROWSER                             │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  React UI (Port 8998)                                       │ │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │ │
│  │  │ Agent    │  │ Voice    │  │ Language │  │ Voice    │  │ │
│  │  │ Card     │  │ Mode     │  │ Selector │  │ Card     │  │ │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘  │ │
│  │                                                             │ │
│  │  TailwindCSS + DaisyUI + TypeScript + Vite                 │ │
│  └────────────────────────────────────────────────────────────┘ │
│                              │                                   │
│                              │ WebSocket (ws://localhost:8998)   │
│                              ↓                                   │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    PERSONAPLEX SERVER                            │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  Moshi Server (Python) - Port 8998                          │ │
│  │                                                              │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │ │
│  │  │ WebSocket    │  │ Voice        │  │ Agent        │    │ │
│  │  │ Handler      │  │ Processing   │  │ Manager      │    │ │
│  │  └──────────────┘  └──────────────┘  └──────────────┘    │ │
│  │                                                              │ │
│  │  ┌──────────────────────────────────────────────────────┐  │ │
│  │  │ PersonaPlex Model (7B parameters)                     │  │ │
│  │  │  - Mimi Audio Encoder/Decoder                         │  │ │
│  │  │  - LLM Generation                                      │  │ │
│  │  │  - Voice Embeddings (18 voices)                       │  │ │
│  │  └──────────────────────────────────────────────────────┘  │ │
│  └────────────────────────────────────────────────────────────┘ │
│                              │                                   │
│                              │ HTTP/REST API                     │
│                              ↓                                   │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    OMNICORTEX API                                │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  FastAPI Backend - Port 8000                                │ │
│  │                                                              │ │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │ │
│  │  │ Agent    │  │ RAG      │  │ Auth     │  │ Voice    │  │ │
│  │  │ Manager  │  │ Service  │  │ Service  │  │ Proxy    │  │ │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘  │ │
│  │                                                              │ │
│  │  Endpoints:                                                  │ │
│  │  - GET  /agents                                             │ │
│  │  - GET  /agents/{id}/system-prompt                          │ │
│  │  - GET  /agents/{id}/voice-context (RAG)                    │ │
│  │  - POST /query (text chat)                                  │ │
│  │  - WS   /voice/ws (voice proxy)                             │ │
│  └────────────────────────────────────────────────────────────┘ │
│                              │                                   │
│                              │ SQL + Vector Queries              │
│                              ↓                                   │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    DATABASE LAYER                                │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  PostgreSQL + pgvector - Port 5432                          │ │
│  │                                                              │ │
│  │  Tables:                                                     │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │ │
│  │  │ omni_agents  │  │ omni_        │  │ omni_        │    │ │
│  │  │              │  │ documents    │  │ messages     │    │ │
│  │  │ - id         │  │              │  │              │    │ │
│  │  │ - name       │  │ - agent_id   │  │ - session_id │    │ │
│  │  │ - type       │  │ - content    │  │ - content    │    │ │
│  │  │ - prompt     │  │ - embedding  │  │ - timestamp  │    │ │
│  │  └──────────────┘  └──────────────┘  └──────────────┘    │ │
│  │                                                              │ │
│  │  Vector Collections (pgvector):                             │ │
│  │  - omni_agent_{id} (per-agent embeddings)                   │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔄 Data Flow Diagrams

### 1. Agent Selection Flow

```
┌──────────┐
│  User    │
│  clicks  │
│ "Refresh"│
└────┬─────┘
     │
     ↓
┌────────────────┐
│ React UI       │
│ GET /api/agents│
└────┬───────────┘
     │
     ↓
┌─────────────────────┐
│ Moshi Server        │
│ Proxies to          │
│ OmniCortex          │
└────┬────────────────┘
     │
     ↓
┌─────────────────────┐
│ OmniCortex API      │
│ GET /agents         │
│ Query PostgreSQL    │
└────┬────────────────┘
     │
     ↓
┌─────────────────────┐
│ PostgreSQL          │
│ SELECT * FROM       │
│ omni_agents         │
└────┬────────────────┘
     │
     ↓ (Returns agent list)
┌─────────────────────┐
│ React UI            │
│ Displays AgentCards │
└─────────────────────┘
```

### 2. Knowledge Retrieval (RAG) Flow

```
┌──────────┐
│  User    │
│  selects │
│  agent   │
└────┬─────┘
     │
     ↓
┌────────────────────────────┐
│ React UI                   │
│ GET /api/agent-prompt      │
│ ?agent_id=X&context_query=Y│
└────┬───────────────────────┘
     │
     ↓
┌─────────────────────────────────┐
│ Moshi Server                    │
│ 1. GET /agents/{id}/system-     │
│    prompt                        │
│ 2. GET /agents/{id}/voice-      │
│    context?query=Y&top_k=3      │
└────┬────────────────────────────┘
     │
     ↓
┌─────────────────────────────────┐
│ OmniCortex RAG Service          │
│ 1. Embed context_query          │
│ 2. Vector similarity search     │
│ 3. Retrieve top-k documents     │
└────┬────────────────────────────┘
     │
     ↓
┌─────────────────────────────────┐
│ pgvector                        │
│ SELECT * FROM                   │
│ omni_agent_{id}                 │
│ ORDER BY embedding <=> query    │
│ LIMIT 3                         │
└────┬────────────────────────────┘
     │
     ↓ (Returns documents)
┌─────────────────────────────────┐
│ Moshi Server                    │
│ Combines:                       │
│ - System prompt                 │
│ - Retrieved context             │
│ - Initial greeting              │
└────┬────────────────────────────┘
     │
     ↓
┌─────────────────────────────────┐
│ React UI                        │
│ Displays combined prompt        │
└─────────────────────────────────┘
```

### 3. Voice Conversation Flow

```
┌──────────┐
│  User    │
│  speaks  │
└────┬─────┘
     │ (Audio)
     ↓
┌─────────────────────┐
│ Browser Microphone  │
│ Capture PCM audio   │
└────┬────────────────┘
     │
     ↓
┌─────────────────────┐
│ Opus Encoder        │
│ Compress audio      │
└────┬────────────────┘
     │
     ↓ (Binary frame 0x01)
┌─────────────────────┐
│ WebSocket           │
│ Send to server      │
└────┬────────────────┘
     │
     ↓
┌─────────────────────────────┐
│ Moshi Server                │
│ 1. Opus decode → PCM        │
│ 2. Mimi encode → tokens     │
│ 3. LLM generate (with RAG)  │
│ 4. Mimi decode → PCM        │
│ 5. Opus encode              │
└────┬────────────────────────┘
     │
     ↓ (Binary frame 0x01 + text 0x02)
┌─────────────────────┐
│ WebSocket           │
│ Send to client      │
└────┬────────────────┘
     │
     ↓
┌─────────────────────┐
│ Browser             │
│ 1. Opus decode      │
│ 2. Play audio       │
│ 3. Display text     │
└─────────────────────┘
```

---

## 🎨 UI Component Hierarchy

```
Queue.tsx (Main Container)
│
├── Homepage (Before Connection)
│   │
│   ├── Header
│   │   ├── Title (OmniCortex)
│   │   └── Subtitle
│   │
│   ├── Agent Section
│   │   ├── Refresh Button
│   │   ├── Bearer Token Input
│   │   ├── User ID Input
│   │   └── AgentCard[] (List)
│   │       ├── Icon (emoji)
│   │       ├── Name
│   │       ├── Type
│   │       └── Badges (docs, msgs)
│   │
│   ├── Language Section
│   │   ├── LanguageSelector
│   │   │   ├── English (recommended)
│   │   │   ├── Hindi (experimental)
│   │   │   └── Bilingual (experimental)
│   │   └── HindiWarning (conditional)
│   │       ├── Warning message
│   │       ├── Voice recommendations
│   │       └── Tips
│   │
│   ├── Voice Mode Section
│   │   └── VoiceModeSelector
│   │       ├── PersonaPlex card
│   │       ├── LFM card
│   │       └── Cascade card
│   │
│   ├── Voice Selection Section
│   │   ├── Natural Voices
│   │   │   └── EnhancedVoiceCard[] (grid)
│   │   │       ├── Icon (👩/👨)
│   │   │       ├── Name
│   │   │       └── Category badge
│   │   └── Variety Voices
│   │       └── EnhancedVoiceCard[] (grid)
│   │
│   ├── Text Prompt Section
│   │   ├── Preset buttons
│   │   ├── Textarea
│   │   └── Character counter
│   │
│   ├── Context Query Section
│   │   ├── Textarea
│   │   └── Character counter
│   │
│   └── Connect Button
│       ├── Icon
│       └── Label
│
└── Conversation (After Connection)
    │
    ├── Controls
    │   ├── Disconnect button
    │   └── Status indicator
    │
    ├── Audio Visualizers
    │   ├── ServerAudio (AI voice)
    │   └── UserAudio (User mic)
    │
    ├── Text Display
    │   ├── User transcript
    │   └── AI transcript
    │
    └── Stats
        ├── Audio duration
        ├── Latency
        └── Message count
```

---

## 🔌 WebSocket Protocol

### Frame Types

```
┌─────────┬──────────────────────────────────┐
│ Type    │ Description                      │
├─────────┼──────────────────────────────────┤
│ 0x00    │ Handshake (server → client)      │
│ 0x01    │ Audio data (bidirectional)       │
│ 0x02    │ Text transcript (server → client)│
│ 0x03    │ Control tokens (BOS, EOS, PAD)   │
└─────────┴──────────────────────────────────┘
```

### Connection Sequence

```
Client                          Server
  │                               │
  │──── WS Connect ──────────────>│
  │     (with params)             │
  │                               │
  │<──── 0x00 Handshake ──────────│
  │                               │
  │<──── 0x02 Initial Greeting ───│
  │     (if configured)           │
  │                               │
  │──── 0x01 Audio Frame ────────>│
  │                               │
  │<──── 0x01 Audio Frame ────────│
  │<──── 0x02 Text Token ─────────│
  │                               │
  │──── 0x01 Audio Frame ────────>│
  │                               │
  │<──── 0x01 Audio Frame ────────│
  │<──── 0x02 Text Token ─────────│
  │                               │
  └──── (continues) ──────────────┘
```

---

## 🌐 Network Topology

```
Internet
    │
    ↓
┌─────────────────┐
│  Load Balancer  │ (Optional)
│  nginx/Caddy    │
└────────┬────────┘
         │
         ├──────────────────┬──────────────────┐
         │                  │                  │
         ↓                  ↓                  ↓
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ PersonaPlex     │  │ OmniCortex      │  │ PostgreSQL      │
│ Server :8998    │  │ API :8000       │  │ :5432           │
│                 │  │                 │  │                 │
│ - WebSocket     │  │ - REST API      │  │ - SQL           │
│ - Voice Model   │  │ - RAG Service   │  │ - pgvector      │
│ - UI Serving    │  │ - Auth          │  │ - Embeddings    │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

---

## 📊 Data Models

### Agent Model
```typescript
interface Agent {
  id: string;              // UUID
  name: string;            // Display name
  type: string;            // assistant, service, etc.
  system_prompt: string;   // Base instructions
  conversation_starters: string[];
  initial_greeting: string;
  document_count: number;  // Number of uploaded docs
  message_count: number;   // Conversation history
  created_at: Date;
  updated_at: Date;
}
```

### Voice Context Model
```typescript
interface VoiceContext {
  agent_id: string;
  context: string;         // Retrieved text
  documents: Document[];   // Source documents
  query: string;           // Original query
  top_k: number;           // Number retrieved
}
```

### WebSocket Message Model
```typescript
interface WSMessage {
  type: 0x00 | 0x01 | 0x02 | 0x03;
  payload: Uint8Array;     // Binary data
}
```

---

This architecture provides a complete view of how PersonaPlex integrates with OmniCortex for voice AI conversations with RAG-powered knowledge retrieval.
