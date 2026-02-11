# Verification Checklist: Integration Fix

Use this checklist to verify that all integration fixes are working correctly.

## Pre-Flight Checks

- [ ] PostgreSQL is running on port 5433
- [ ] Ollama is running on port 11434
- [ ] Model llama3.2:3b is installed
- [ ] Python environment is activated
- [ ] Node.js dependencies are installed (`cd admin && npm install`)

## Backend Verification

### 1. Startup Validation

- [ ] Start backend: `python api.py`
- [ ] See startup validation messages
- [ ] PostgreSQL check passes ✅
- [ ] Ollama check passes ✅
- [ ] Backend reports "ready on http://localhost:8000"
- [ ] No errors in terminal

### 2. Health Endpoint

- [ ] Test health endpoint: `curl http://localhost:8000/health`
- [ ] Returns HTTP 200
- [ ] Response includes `status: "healthy"`
- [ ] Database status is "up"
- [ ] Ollama status is "up"
- [ ] Model loaded is true
- [ ] Response time < 2 seconds

### 3. CORS Configuration

- [ ] Test CORS: `curl -X OPTIONS http://localhost:8000/agents -H "Origin: http://localhost:3000" -v`
- [ ] Response includes `Access-Control-Allow-Origin` header
- [ ] Response includes `Access-Control-Allow-Methods` header
- [ ] No CORS errors in response

### 4. Basic Endpoints

- [ ] Test root: `curl http://localhost:8000/`
- [ ] Returns `{"status": "ok"}`
- [ ] Test agents: `curl http://localhost:8000/agents`
- [ ] Returns array (empty or with agents)
- [ ] No errors

## Frontend Verification

### 1. Startup

- [ ] Start frontend: `cd admin && npm run dev`
- [ ] No compilation errors
- [ ] Server starts on port 3000
- [ ] No errors in terminal

### 2. Health Monitor Component

- [ ] Open http://localhost:3000
- [ ] No red warning banner at top (backend is healthy)
- [ ] Check browser console - no errors
- [ ] Health monitor component is loaded (check React DevTools)

### 3. API Client

- [ ] Open browser DevTools → Network tab
- [ ] Refresh page
- [ ] See request to `/agents`
- [ ] Request succeeds (200 status)
- [ ] No "Failed to fetch" errors in console

### 4. Agent Operations

- [ ] Click "Create Agent"
- [ ] Enter name: "Test Agent"
- [ ] Enter description: "Test Description"
- [ ] Click "Create"
- [ ] Agent created successfully
- [ ] No errors in console
- [ ] Agent appears in list

### 5. Error Handling

- [ ] Stop backend (Ctrl+C in backend terminal)
- [ ] Wait 30 seconds
- [ ] Red warning banner appears at top
- [ ] Banner shows "Backend Connection Lost"
- [ ] Banner shows last check timestamp
- [ ] Restart backend: `python api.py`
- [ ] Wait 30 seconds
- [ ] Banner auto-dismisses
- [ ] API calls work again

## Integration Tests

### 1. Test Suite

- [ ] Run: `python test_integration_fix.py`
- [ ] Test 1 (Health Endpoint): PASSED ✅
- [ ] Test 2 (CORS Configuration): PASSED ✅
- [ ] Test 3 (Basic Endpoint): PASSED ✅
- [ ] Test 4 (Agents Endpoint): PASSED ✅
- [ ] All tests passed (4/4)

### 2. Network Diagnostics

- [ ] Run: `python scripts/diagnose_network.py`
- [ ] Backend reachability: ✅
- [ ] Health endpoint: ✅
- [ ] CORS configuration: ✅
- [ ] Port 3000 in use: ✅
- [ ] Port 8000 in use: ✅
- [ ] Port 5433 in use: ✅
- [ ] Port 11434 in use: ✅
- [ ] All checks passed

### 3. Enhanced Startup Script

- [ ] Close all services
- [ ] Run: `start_services_enhanced.bat`
- [ ] PostgreSQL check passes
- [ ] Ollama check passes
- [ ] Backend starts
- [ ] Backend becomes healthy
- [ ] Frontend starts
- [ ] Browser opens automatically
- [ ] No "Failed to fetch" errors

## End-to-End Flow

### 1. Agent Creation

- [ ] Open http://localhost:3000
- [ ] Click "Create Agent"
- [ ] Enter name: "Pizza Store Assistant"
- [ ] Enter description: "AI assistant for pizza store"
- [ ] Click "Create"
- [ ] Agent created successfully
- [ ] Agent appears in list with correct name

### 2. Document Upload

- [ ] Click on "Pizza Store Assistant" agent
- [ ] Click "Upload Documents"
- [ ] Select a PDF file
- [ ] Click "Upload"
- [ ] Upload succeeds
- [ ] Document count updates
- [ ] No timeout errors

### 3. Chat Query

- [ ] Go to agent chat page
- [ ] Type: "Hello, how are you?"
- [ ] Press Enter or click Send
- [ ] Response appears within 5-10 seconds (first query)
- [ ] Response is coherent
- [ ] No timeout errors
- [ ] Type another message
- [ ] Response appears within 2-4 seconds
- [ ] Conversation history maintained

## Performance Checks

### 1. Health Check Caching

- [ ] Open browser DevTools → Network tab
- [ ] Refresh page multiple times quickly
- [ ] Health check requests are cached (not sent every time)
- [ ] Cache TTL is ~5 seconds

### 2. Retry Logic

- [ ] Stop backend
- [ ] Try to create an agent
- [ ] See retry attempts in console (1/3, 2/3, 3/3)
- [ ] Exponential backoff timing (1s, 2s, 4s)
- [ ] Final error after 3 attempts
- [ ] Error message is clear

### 3. Timeout Configuration

- [ ] Health check times out at 5 seconds
- [ ] Agent operations timeout at 10 seconds
- [ ] Chat queries timeout at 90 seconds
- [ ] Timeouts are appropriate for operation type

## Error Handling Checks

### 1. Connection Errors

- [ ] Stop backend
- [ ] Try to fetch agents
- [ ] Error type: "connection"
- [ ] Error message: "Cannot connect to server..."
- [ ] Error is retryable: true
- [ ] Retry attempts logged

### 2. Timeout Errors

- [ ] Simulate slow backend (if possible)
- [ ] Error type: "timeout"
- [ ] Error message: "Request timed out..."
- [ ] Error includes operation name

### 3. Server Errors

- [ ] Trigger a 500 error (if possible)
- [ ] Error type: "server"
- [ ] Error message includes backend error
- [ ] Retry attempts occur

### 4. Client Errors

- [ ] Send invalid request (e.g., empty agent name)
- [ ] Error type: "client"
- [ ] Error message from backend
- [ ] No retry attempts (4xx errors don't retry)

## Documentation Checks

- [ ] `INTEGRATION_FIX_README.md` exists and is comprehensive
- [ ] `IMPLEMENTATION_SUMMARY.md` exists and is accurate
- [ ] `BEFORE_AFTER_COMPARISON.md` exists and is clear
- [ ] `QUICK_START.md` exists and is helpful
- [ ] `VERIFICATION_CHECKLIST.md` exists (this file)
- [ ] All documentation is up-to-date

## Code Quality Checks

### Backend (api.py)

- [ ] Health endpoint implemented
- [ ] CORS configured with explicit origins
- [ ] Startup validation implemented
- [ ] No syntax errors
- [ ] No linting errors
- [ ] Code is well-commented

### Frontend (api.ts)

- [ ] Health check integration implemented
- [ ] Retry logic with exponential backoff
- [ ] Error classification implemented
- [ ] Tiered timeouts configured
- [ ] No TypeScript errors
- [ ] No linting errors
- [ ] Code is well-typed

### Health Monitor Component

- [ ] Component renders correctly
- [ ] Polling works (30 second interval)
- [ ] Tab visibility detection works
- [ ] Banner shows/hides correctly
- [ ] No React errors
- [ ] No console warnings

## Final Verification

- [ ] All backend checks passed
- [ ] All frontend checks passed
- [ ] All integration tests passed
- [ ] All end-to-end flows work
- [ ] All performance checks passed
- [ ] All error handling works
- [ ] All documentation is complete
- [ ] No outstanding issues

## Sign-Off

**Date**: _______________

**Verified By**: _______________

**Status**: 
- [ ] ✅ All checks passed - Ready for use
- [ ] ⚠️ Some checks failed - See notes below
- [ ] ❌ Major issues - Needs more work

**Notes**:
```
[Add any notes, issues, or observations here]
```

---

## Quick Reference

### Start Services
```bash
start_services_enhanced.bat
```

### Test Integration
```bash
python test_integration_fix.py
```

### Diagnose Issues
```bash
python scripts/diagnose_network.py
```

### Check Health
```bash
curl http://localhost:8000/health
```

### View Logs
- Backend: Check terminal where `python api.py` is running
- Frontend: Check terminal where `npm run dev` is running
- Browser: Open DevTools → Console

---

**Checklist Version**: 1.0.0  
**Last Updated**: February 9, 2026  
**Spec Reference**: `.kiro/specs/nextjs-fastapi-integration-fix/`
