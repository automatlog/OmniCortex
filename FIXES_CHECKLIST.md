# OmniCortex - Quick Issue Checklist

## 🚨 Critical Issues (Fix First)

### 1. Missing Optional Dependencies
- [ ] Add `elevenlabs`, `liquid-audio`, `torchaudio` to `pyproject.toml`
- [ ] Document voice feature dependencies
- [ ] Create installation guide: `uv pip install 'omnicortex[voice]'`

```toml
# Add to pyproject.toml [project.optional-dependencies]
voice = [
    "elevenlabs>=0.2.0",
    "liquid-audio>=0.1.0", 
    "torchaudio>=2.0.0",
    "openai-whisper>=20240314",
    "piper-tts>=1.2.0",
]
```

---

## ⚠️ High Priority Issues

### 2. Create .env.example
- [ ] Template file with all required/optional variables
- [ ] Document each variable with description and default

**Location:** Create `c:\Users\AMAN\Downloads\MetaCortex\OmniCortex\.env.example`

```env
# Required
DATABASE_URL=postgresql://user:password@localhost:5432/omnicortex

# LLM Configuration
VLLM_BASE_URL=http://localhost:8080/v1
VLLM_MODEL=meta-llama/Meta-Llama-3.1-8B-Instruct
LLM_TEMPERATURE=0.6

# Optional: Voice
ELEVENLABS_API_KEY=
VOICE_MODEL=LiquidAI/LFM2.5-Audio-1.5B

# Optional: WhatsApp
WHATSAPP_ACCESS_TOKEN=
WHATSAPP_PHONE_ID=

# Optional: Advanced
CHUNK_SIZE=700
CHUNK_OVERLAP=120
DEFAULT_MAX_HISTORY=5
```

### 3. Add Dockerfile
- [ ] Create Docker image for deployment
- [ ] Include vLLM sidecar setup
- [ ] Document in DEPLOY.md

### 4. Fix LLM Function Signature
- **File:** `core/llm.py`
- **Issue:** `get_llm(model_key)` but `graph.py` calls `get_llm(provider, model)`
- **Solution:** Standardize to use model_key parameter

---

## 🟡 Medium Priority Issues

### 5. Integrate Cache in Chat Service
- [ ] Update `process_question()` to check cache before RAG
- [ ] Store responses in cache after generation
- **File:** `core/chat_service.py`

### 6. Database Pool Configuration
- [ ] Move hardcoded pool_size/max_overflow to environment variables
- **File:** `core/database.py` (lines 17-21)

### 7. Voice Engine Error Handling
- [ ] Return 503 Service Unavailable when voice features missing
- [ ] Provide helpful installation message
- **File:** `api.py` (voice endpoints)

### 8. Type Hints
- [ ] Add complete type hints to:
  - `format_context(docs: List[Any])`
  - `get_agent() -> Optional[Dict[str, Any]]`
  - All functions in `chat_service.py`

---

## 🟢 Low Priority Issues

### 9. Expand Test Coverage
- [ ] Add RAG pipeline unit tests
- [ ] Add voice engine tests
- [ ] Add database integration tests
- **Directory:** `tests/`

### 10. Documentation Updates
- [ ] Document all API endpoints (OpenAPI)
- [ ] Add voice feature setup guide
- [ ] Add troubleshooting section

---

## ✅ What's Already Good

✅ **Error Handling** - Try-except blocks properly implemented  
✅ **Database Design** - Proper indexes and relationships  
✅ **Security** - PII masking and input validation  
✅ **Logging** - Prometheus metrics integrated  
✅ **Testing** - Good test suite exists  
✅ **Documentation** - Setup and deployment guides  
✅ **Code Structure** - Modular and organized  
✅ **Performance** - Connection pooling, caching layer  

---

## 🔧 Quick Fixes (< 30 minutes each)

### Fix #1: Add to pyproject.toml
```bash
cd c:\Users\AMAN\Downloads\MetaCortex\OmniCortex
# Edit pyproject.toml, add voice optional dependencies
```

### Fix #2: Create .env.example
```bash
cp .env .env.example  # Or create from template above
```

### Fix #3: Update core/llm.py
```python
def get_llm(model_key: str = "Meta Llama 3.1"):
    """Get LLM by model key"""
    if model_key not in MODEL_BACKENDS:
        raise ValueError(f"Unknown model_key: {model_key}")
    config = MODEL_BACKENDS[model_key]
    return ChatOpenAI(base_url=config["base_url"], model=config["model"], ...)
```

### Fix #4: Update core/database.py
```python
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "20"))
DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "40"))

engine = create_engine(
    DATABASE_URL,
    pool_size=DB_POOL_SIZE,
    max_overflow=DB_MAX_OVERFLOW,
    ...
)
```

---

## 📊 Project Health Score

| Category | Score | Notes |
|----------|-------|-------|
| Code Quality | 9/10 | Clean, modular, well-documented |
| Error Handling | 8/10 | Good coverage, some edge cases |
| Testing | 7/10 | Good tests, need more unit tests |
| Documentation | 8/10 | Comprehensive, needs voice guide |
| Deployment Ready | 7/10 | Needs .env.example and Dockerfile |
| Security | 8/10 | PII masking, needs audit logging |
| Performance | 8/10 | Good pooling, could use Redis |
| **OVERALL** | **8/10** | **Production-ready with minor fixes** |

---

## 📅 Implementation Timeline

**Week 1:**
- Add .env.example ✅
- Fix pyproject.toml ✅
- Standardize LLM function signatures ✅

**Week 2:**
- Add Dockerfile + docker-compose
- Integrate cache in chat_service
- Add type hints

**Week 3:**
- Expand test coverage
- Add CI/CD pipeline
- Performance optimization

**Week 4:**
- Security audit
- Production deployment
- Monitoring setup

---

**Last Updated:** 2026-02-05
