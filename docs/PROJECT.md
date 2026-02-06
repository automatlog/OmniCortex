# OmniCortex - Multi-Agent RAG Platform

**Version**: 2.0 | **Last Updated**: January 2026

---

## Overview

OmniCortex is a **multi-tenant, multi-agent AI platform** that enables businesses to create intelligent chatbots with domain-specific knowledge. Each agent can be trained on custom documents and deployed across multiple channels (Web, WhatsApp, Voice).

---

## Core Features

| Feature | Description |
|---------|-------------|
| **Multi-Agent** | Create unlimited isolated AI agents |
| **RAG Pipeline** | Upload PDFs/docs for agent-specific knowledge |
| **Local LLM** | Run Llama 3.1 via vLLM (no API costs) |
| **Voice Chat** | LiquidAI for real-time audio (optional) |
| **WhatsApp** | Business API integration |
| **Persistent Memory** | Conversation history per user |
| **Analytics** | ClickHouse integration for detailed logs |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      CLIENT LAYER                           │
│   [Streamlit UI]  [WhatsApp API]  [Voice/LiquidAI]          │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                   APPLICATION LAYER                         │
│   [FastAPI :8000]  ←→  [vLLM Server :8080]                  │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                     CORE SERVICES                           │
│   [Agent Manager]  [Chat Service]  [RAG Pipeline]           │
│   [Document Processor]                                      │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                       DATA LAYER                            │
│   [PostgreSQL + pgvector]  [ClickHouse]  [File Storage]     │
└─────────────────────────────────────────────────────────────┘
```

---

## Data Flow

### Document Ingestion
```
PDF Upload → Text Extraction → Chunking (700 tokens)
    → Embedding (HuggingFace) → pgvector Storage
```

### Chat Query
```
User Question → Vector Search (agent-filtered)
    → Context Retrieval → LLM Generation (vLLM)
    → Response → Postgres (History) + ClickHouse (Analytics)
```

---

## Project Structure

```
OmniCortex/
├── core/
│   ├── inference/      # vLLM client (Deprecated, uses llm.py)
│   ├── processing/     # Chunking, document loading
│   ├── rag/            # Vector store, embeddings
│   └── voice/          # LiquidAI integration
├── docs/               # Documentation (you are here)
├── scripts/            # Deployment scripts
├── tests/              # Test suite
├── config/             # Configuration files
├── api.py              # FastAPI backend
├── main.py             # Streamlit UI
└── pyproject.toml      # Dependencies
```

---

## Key Design Decisions

### Agent Isolation
Each agent has its own vector collection with metadata filtering. No cross-contamination.

### TPM-Safe Chunking
700-token chunks with 17% overlap prevents rate limit explosions.

### Simple Retry Logic
Basic exponential backoff handles temporary vLLM unavailability.

---

## Challenges Solved

| Challenge | Solution |
|-----------|----------|
| Rate limits (429) | Retry with backoff |
| Cross-agent contamination | Metadata-filtered retrieval |
| High API costs | Local vLLM inference |
| Context window limits | Smart chunking (700 tokens) |
| Concurrent agents | Connection pooling + async |

---

## Performance Targets

| Metric | Target | Achieved |
|--------|--------|----------|
| Concurrent agents | 50+ | ✅ 80 (on 2x A10) |
| Response latency | <3s | ✅ 1-2s |
| API cost | $0 | ✅ Local LLM |
| Uptime | 99.9% | ✅ Auto-restart |

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| **Backend** | Python 3.12, FastAPI, SQLAlchemy |
| **UI** | Streamlit |
| **LLM Inference** | vLLM + Llama 3.1-8B-Instruct |
| **Embeddings** | HuggingFace all-MiniLM-L6-v2 |
| **Database** | PostgreSQL 16 + pgvector |
| **Analytics** | ClickHouse (Optional) |
| **Voice** | LiquidAI LFM2.5-Audio-1.5B |
| **Package Manager** | uv (Astral) |
| **Orchestration** | LangChain LCEL, LangGraph, CrewAI |

---

## Core Module Structure

```
core/
├── __init__.py              # Public API exports
├── config.py                # Environment variables & settings
├── database.py              # SQLAlchemy models, connection pooling
├── agent_manager.py         # Agent CRUD operations
├── chat_service.py          # RAG workflow orchestration
├── llm.py                   # Unified LLM integration
├── clickhouse.py            # Analytics Logger
├── prompts.py               # Prompt templates
├── crew.py                  # CrewAI Orchestration
├── graph.py                 # LangGraph state machine
├── whatsapp.py              # WhatsApp API client
├── whatsapp_history.py      # WhatsApp conversation storage
├── rate_limit_manager.py    # Rate limiting
│
├── processing/              # Document Processing
│   ├── __init__.py
│   ├── chunking.py          # Text splitting (700 tokens)
│   └── document_loader.py   # PDF/TXT extraction
│
├── rag/                     # Retrieval-Augmented Generation
│   ├── __init__.py
│   ├── vector_store.py      # pgvector operations
│   ├── embeddings.py        # HuggingFace embedding model
│   └── ingestion_fixed.py   # Agent-aware document ingestion
│
└── voice/                   # Voice Processing
    ├── __init__.py
    ├── liquid_voice.py      # LiquidAI integration
    └── voice_engine.py      # Audio processing utilities
```

### Module Responsibilities

| Module | Purpose |
|--------|---------|
| `llm.py` | Unified LLM interface (vLLM via LangChain) |
| `processing/` | Text chunking and document extraction |
| `rag/` | Vector storage, embeddings, retrieval |
| `voice/` | Real-time audio chat with LiquidAI |

### Key Files

| File | Description |
|------|-------------|
| `chat_service.py` | Orchestrates RAG: retrieval → context → LLM → response |
| `agent_manager.py` | Create, read, update, delete agents |
| `database.py` | PostgreSQL models with connection pooling |
| `clickhouse.py` | Usage & Chat analytics logger |
| `deploy_runpod.sh`| RunPod deployment automation script |
| `ingestion_fixed.py` | Agent-isolated document ingestion |
