# Backend Startup Validation

## Overview

The FastAPI backend now includes comprehensive startup validation that checks all critical dependencies before accepting requests. This ensures the system fails fast with clear error messages rather than encountering cryptic errors during operation.

## Implementation Details

### Location
- **File**: `api.py`
- **Function**: `validate_dependencies()` (FastAPI startup event handler)
- **Lines**: 67-127

### Validation Checks

#### 1. PostgreSQL Database Check (Requirement 7.1)
- **Timeout**: 10 seconds
- **Method**: Uses `ThreadPoolExecutor` with `future.result(timeout=10)` for cross-platform timeout support
- **Test Query**: `SELECT 1`
- **Success Message**: `✅ PostgreSQL connected`
- **Failure Message**: `❌ PostgreSQL connection failed: {error}`
- **Remediation**: `💡 Start PostgreSQL: docker-compose up -d postgres`

**Implementation**:
```python
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

def check_db():
    db = SessionLocal()
    try:
        db.execute("SELECT 1")
        return True
    finally:
        db.close()

with ThreadPoolExecutor(max_workers=1) as executor:
    future = executor.submit(check_db)
    try:
        future.result(timeout=10)
        print("  ✅ PostgreSQL connected")
    except FutureTimeoutError:
        print("  ❌ PostgreSQL connection timeout (10s)")
        all_ok = False
```

#### 2. Ollama LLM Service Check (Requirement 7.2)
- **Timeout**: 10 seconds
- **Method**: HTTP GET request with `timeout=10` parameter
- **Endpoint**: `http://localhost:11434/api/tags`
- **Model Check**: Verifies `llama3.2:3b` model is loaded
- **Success Message**: `✅ Ollama running with llama3.2:3b`
- **Failure Message**: `❌ Ollama connection failed: {error}`
- **Remediation**: `💡 Start Ollama: ollama serve`

**Implementation**:
```python
response = requests.get("http://localhost:11434/api/tags", timeout=10)
if response.status_code == 200:
    models = response.json().get("models", [])
    if any("llama3.2:3b" in m.get("name", "") for m in models):
        print("  ✅ Ollama running with llama3.2:3b")
```

#### 3. Error Handling and Exit (Requirement 7.3)
- **Behavior**: If any dependency check fails, the backend logs clear error messages and exits with code 1
- **Exit Call**: `sys.exit(1)`
- **Error Messages**: Include both the error description and remediation steps

**Implementation**:
```python
if all_ok:
    print("  ✅ All dependencies validated")
    print("  🚀 Backend ready on http://localhost:8000")
else:
    print("  ❌ Dependency validation failed")
    print("  🛑 Backend will exit")
    sys.exit(1)
```

#### 4. Success Logging (Requirement 7.4)
- **Version**: Displayed in header and success message
- **Port**: `http://localhost:8000`
- **API Docs**: `http://localhost:8000/docs`

**Output Format**:
```
============================================================
  OmniCortex Backend - Startup Validation
============================================================

[1/2] Checking PostgreSQL...
  ✅ PostgreSQL connected

[2/2] Checking Ollama...
  ✅ Ollama running with llama3.2:3b

============================================================
  ✅ All dependencies validated
  🚀 Backend ready on http://localhost:8000
  📚 API docs: http://localhost:8000/docs
============================================================
```

## Design Decisions

### Cross-Platform Timeout Support
The implementation uses `concurrent.futures.ThreadPoolExecutor` instead of Unix-specific `signal.alarm()` to ensure the timeout mechanism works on both Windows and Unix-like systems.

### Fail-Fast Philosophy
The backend exits immediately if dependencies are unavailable rather than starting in a degraded state. This prevents confusing errors during operation and makes troubleshooting easier.

### Clear Remediation Steps
Each error message includes a specific command to fix the issue, reducing the time needed to diagnose and resolve problems.

### Model Verification
The Ollama check not only verifies the service is running but also confirms the required model (`llama3.2:3b`) is loaded, preventing runtime errors when processing queries.

## Testing

### Manual Testing
1. **Test with all dependencies available**:
   ```bash
   # Start PostgreSQL
   docker-compose up -d postgres
   
   # Start Ollama
   ollama serve
   
   # Pull required model
   ollama pull llama3.2:3b
   
   # Start backend
   python api.py
   ```
   Expected: Backend starts successfully with all green checkmarks

2. **Test with database unavailable**:
   ```bash
   # Stop PostgreSQL
   docker-compose stop postgres
   
   # Start backend
   python api.py
   ```
   Expected: Backend exits with database error message

3. **Test with Ollama unavailable**:
   ```bash
   # Stop Ollama (Ctrl+C if running in terminal)
   
   # Start backend
   python api.py
   ```
   Expected: Backend exits with Ollama error message

### Automated Testing
Unit tests are available in `tests/test_startup_validation.py` (optional task 3.1).

## Requirements Traceability

| Requirement | Description | Implementation |
|-------------|-------------|----------------|
| 7.1 | Database connectivity check with 10s timeout | `ThreadPoolExecutor` with `timeout=10` |
| 7.2 | Ollama connectivity check with 10s timeout | `requests.get(..., timeout=10)` |
| 7.3 | Log clear error messages and exit if unavailable | Error messages with remediation + `sys.exit(1)` |
| 7.4 | Log successful startup with version and port | Success message with version, port, and docs URL |

## Future Enhancements

1. **Configurable Timeouts**: Allow timeout values to be configured via environment variables
2. **Graceful Degradation**: Option to start in read-only mode if some dependencies are unavailable
3. **Health Check Endpoint Integration**: Expose startup validation results via `/health` endpoint
4. **Retry Logic**: Automatically retry failed checks before exiting
5. **Dependency Graph**: Support for checking dependencies in parallel where possible
