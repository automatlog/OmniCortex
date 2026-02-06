# =============================================================================
# OmniCortex Testing Strategy
# Comprehensive testing for 1000+ concurrent users
# =============================================================================

## Quick Reference

### Install Dev Dependencies
```bash
uv sync --group dev
```

### Run Tests

```bash
# Unit/Integration Tests (pytest)
uv run pytest tests/ -v

# Specific test file
uv run pytest tests/test_api.py -v

# Golden Tests (Agent Validation)
uv run python tests/test_agents.py

# Performance Tests
uv run python tests/test_agents.py perf

# Stress Test (100 concurrent users, 60s)
uv run python tests/stress_test_heavy.py

# Load Test with Locust (1000+ users)
uv run locust -f tests/locustfile.py --host http://localhost:8000
```

---

## Testing Architecture

### 1. Functional Testing (UAT)
Manual verification of UI flows.

| Feature | Action | Expected Result |
|---------|--------|-----------------|
| Onboarding | Open Web UI | Page loads < 2s |
| Agent Creation | Create agent "TestBot" | Agent appears in list |
| Ingestion | Upload PDF | Document in Knowledge Base |
| RAG Chat | Ask question from PDF | Answer cites document |
| Voice | Click Microphone | Audio records/transcribes |
| History | Refresh Page | Previous chat preserved |

### 2. API Integration Tests (`tests/test_api.py`)
Automated pytest tests for API endpoints.

```bash
uv run pytest tests/test_api.py -v
```

Covers:
- Health check (`GET /`)
- Agent CRUD (`POST/GET/DELETE /agents`)
- Query endpoint (`POST /query`)
- Document upload (`POST /documents`)

### 3. Golden Tests (`tests/test_agents.py`)
Validates each agent's RAG pipeline:
1. Documents exist
2. Vector retrieval works
3. LLM responds correctly

```bash
uv run python tests/test_agents.py
```

### 4. Load Testing (`tests/locustfile.py`)
Simulates 1000+ concurrent users using Locust.

```bash
# With Web UI (recommended)
uv run locust -f tests/locustfile.py --host http://localhost:8000

# Headless (CI/CD)
uv run locust -f tests/locustfile.py --host http://localhost:8000 \
    --headless -u 1000 -r 50 -t 5m
```

Options:
- `-u 1000` = 1000 total users
- `-r 50` = spawn 50 users/second
- `-t 5m` = run for 5 minutes

### 5. Mock Mode for Load Testing
To test infrastructure WITHOUT calling the LLM:

```python
# In locustfile.py
MOCK_MODE = True
```

This makes `/query` return instantly, testing only:
- FastAPI throughput
- Database connections
- Vector store lookups

---

## Scaling to 1000+ Users

### A. Database Connection Pooling
PostgreSQL defaults to ~100 connections. Add PgBouncer or configure SQLAlchemy:

```python
engine = create_engine(
    DATABASE_URL,
    pool_size=20,
    max_overflow=30,
    pool_pre_ping=True
)
```

### B. Consider Alternative Frontends
Streamlit maintains heavy server-side state per user.
For 1000+ users, consider:
- React/Vue frontend calling FastAPI
- Static HTML + JavaScript

### C. Semantic Caching
Already implemented in OmniCortex!
- Similar questions hit cache instead of LLM
- Reduces cost and latency dramatically

---

## Test Files

| File | Purpose |
|------|---------|
| `tests/test_api.py` | Pytest API integration tests |
| `tests/test_agents.py` | Golden tests + performance |
| `tests/stress_test_heavy.py` | 100 concurrent users (async) |
| `tests/locustfile.py` | Locust for 1000+ users |
| `tests/evaluate_rag.py` | RAGAS evaluation |
