# Verification Checklist: OmniCortex Backend

Use this checklist to verify core OmniCortex behavior after deployment or API contract updates.

## Pre-Flight

- [ ] PostgreSQL is running
- [ ] LLM backend is running (vLLM or Ollama endpoint)
- [ ] Python environment is activated
- [ ] `.env` has required values (`DATABASE_URL`, model endpoint, auth callback config)

## Backend Startup

- [ ] Run: `uv run python api.py`
- [ ] Startup dependency validation passes
- [ ] API reports ready on `http://localhost:8000`
- [ ] No startup exceptions in console

## Health and Basic Endpoints

- [ ] `GET /health` returns `200`
- [ ] `GET /` returns a valid status payload
- [ ] `GET /metrics` returns `200`
- [ ] `GET /agents` returns `200`

## Auth

- [ ] Protected APIs reject missing bearer token (`403`)
- [ ] Protected APIs reject invalid bearer token (`403`)
- [ ] Valid bearer token returns success

## Agent Lifecycle

- [ ] `POST /agents` creates agent with provided `id`
- [ ] `GET /agents/{id}` returns created agent
- [ ] `PUT /agents/{id}` updates agent config
- [ ] `DELETE /agents/{id}` removes agent and vector store

## Query and RAG

- [ ] `POST /query` returns answer, `session_id`, `request_id`
- [ ] Same token can query its own agent
- [ ] Other token cannot query/delete/list this agent
- [ ] Media tags are canonical (`[image][..]`, `[video][..]`, `[document][..]`)

## Voice

- [ ] `WS /voice/ws` accepts valid auth + agent id
- [ ] Voice query path resolves agent context correctly
- [ ] Moshi/PersonaPlex proxy remains reachable

## ClickHouse (if enabled)

- [ ] `UsageLogs` receives query/usage rows
- [ ] `ChatArchive` receives chat turn rows
- [ ] `AgentLogs` receives create/update/delete rows
- [ ] `UserId`, `Id`, `ProductId`, `ChannelName`, `ChannelType` are correct

## Logging

- [ ] `storage/logs/api.log` contains request flow
- [ ] `storage/logs/error.log` has no new critical errors
- [ ] `storage/logs/query_trace.log` includes in/out trace for queries

## Quick Commands

```bash
# Start backend
uv run python api.py

# Health
curl http://localhost:8000/health

# List agents
curl -H "Authorization: Bearer <token>" http://localhost:8000/agents
```

