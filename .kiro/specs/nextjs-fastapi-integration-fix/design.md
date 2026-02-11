# Design Document: Next.js to FastAPI Integration Fix

## Overview

This design addresses the "Failed to fetch" errors occurring between the Next.js frontend (port 3000) and FastAPI backend (port 8000) in the OmniCortex system. The root causes include:

1. **Service startup race conditions**: Frontend attempts connections before Backend is ready
2. **Inadequate timeout configuration**: Default timeouts too short for some operations
3. **Missing health check integration**: No verification that Backend is ready before API calls
4. **Insufficient error handling**: Generic error messages that don't guide users to solutions
5. **Lack of service orchestration**: No dependency checking or ordered startup

The solution implements a comprehensive health check system, enhanced retry logic with appropriate timeouts, service startup orchestration, and improved error handling to ensure reliable communication between Frontend and Backend.

### Key Design Decisions

- **Health-first approach**: All API operations verify Backend health before proceeding
- **Tiered timeout strategy**: Different timeouts for different operation types (health checks: 5s, CRUD: 10s, uploads: 30s, chat: 90s)
- **Smart retry logic**: Exponential backoff with retry only on retryable errors (5xx, network errors)
- **Startup orchestration**: Script-based dependency verification and ordered service startup
- **User-centric error messages**: Clear, actionable error messages that guide users to solutions

## Architecture

### System Components

```
┌─────────────────────────────────────────────────────────────┐
│                     Browser (Client)                         │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Next.js Frontend (Port 3000)                          │ │
│  │  ┌──────────────────────────────────────────────────┐ │ │
│  │  │  Health Monitor (Background Polling)             │ │ │
│  │  └──────────────────────────────────────────────────┘ │ │
│  │  ┌──────────────────────────────────────────────────┐ │ │
│  │  │  API Client (api.ts)                             │ │ │
│  │  │  - Health Check Integration                      │ │ │
│  │  │  - Retry Logic with Exponential Backoff          │ │ │
│  │  │  - Tiered Timeout Configuration                  │ │ │
│  │  └──────────────────────────────────────────────────┘ │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                            │
                            │ HTTP/REST
                            │ CORS-enabled
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  FastAPI Backend (Port 8000)                                │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Health Check Endpoint (/health)                       │ │
│  │  - Service Status                                      │ │
│  │  - Database Connectivity                               │ │
│  │  - LLM Service Availability                            │ │
│  └────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  CORS Middleware (Enhanced)                            │ │
│  │  - Explicit Origin Allowlist                           │ │
│  │  - Preflight Request Handling                          │ │
│  └────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Startup Validation                                    │ │
│  │  - Database Connection Check                           │ │
│  │  - Ollama Connectivity Check                           │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘


### Service Startup Flow

```
┌─────────────────────────────────────────────────────────────┐
│  Startup Script (start_services.bat / .sh)                  │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 1: Verify Dependencies                                │
│  - Check PostgreSQL (port 5433)                             │
│  - Check Ollama (port 11434)                                │
│  - Exit if dependencies not available                       │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 2: Start Backend                                      │
│  - Launch FastAPI (port 8000)                               │
│  - Wait for health check to pass (max 30s)                  │
│  - Exit if Backend doesn't become healthy                   │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 3: Start Frontend                                     │
│  - Launch Next.js (port 3000)                               │
│  - Frontend performs health check on mount                  │
└─────────────────────────────────────────────────────────────┘
```

## Components and Interfaces

### 1. Backend Health Check Endpoint

**Location**: `api.py`

**Endpoint**: `GET /health`

**Response Schema**:
```typescript
interface HealthResponse {
  status: "healthy" | "degraded" | "unhealthy";
  version: string;
  timestamp: string;
  services: {
    database: {
      status: "up" | "down";
      latency_ms: number;
    };
    ollama: {
      status: "up" | "down";
      latency_ms: number;
      model_loaded: boolean;
    };
  };
  uptime_seconds: number;
}
```

**Implementation Details**:
- Checks database connectivity with a simple query (`SELECT 1`)
- Checks Ollama availability by calling `/api/tags`
- Returns within 2 seconds (requirement 1.2)
- Caches results for 5 seconds to avoid overwhelming dependencies
- Returns 200 for "healthy", 503 for "degraded" or "unhealthy"

### 2. Enhanced CORS Middleware

**Location**: `api.py`

**Configuration**:
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000"
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600
)
```

**Key Changes**:
- Explicit origin allowlist instead of wildcard (requirement 2.1)
- Includes both localhost and 127.0.0.1 for compatibility
- Explicit OPTIONS handler for preflight requests (requirement 2.3)
- CORS error logging middleware (requirement 2.5)

### 3. API Client with Health Check Integration

**Location**: `admin/src/lib/api.ts`

**Core Functions**:

```typescript
// Health check with caching
async function checkHealthWithCache(): Promise<boolean> {
  // Returns cached result if checked within last 5 seconds
  // Otherwise performs fresh health check
}

// Enhanced fetch with health check
async function fetchWithHealthCheck(
  url: string,
  options: RequestInit = {},
  timeout: number = 30000
): Promise<Response> {
  // 1. Check health (with cache)
  // 2. If unhealthy, throw descriptive error
  // 3. If healthy, proceed with request
  // 4. Apply timeout and retry logic
}
```

**Timeout Configuration** (requirement 3):
- Health checks: 5 seconds
- Agent operations (list, create, delete): 10 seconds
- Document uploads: 30 seconds
- Chat queries: 90 seconds

**Retry Configuration** (requirement 4):
- Max retries: 3
- Initial delay: 1 second
- Backoff: Exponential (1s, 2s, 4s)
- Retry on: 5xx errors, network errors
- No retry on: 4xx errors

### 4. Frontend Health Monitor

**Location**: `admin/src/components/HealthMonitor.tsx` (new component)

**Functionality**:
- Polls `/health` endpoint every 30 seconds when tab is visible (requirement 10.1)
- Displays warning banner when Backend becomes unhealthy (requirement 10.2)
- Auto-dismisses banner when Backend recovers (requirement 10.3)
- Pauses polling when tab is hidden (requirement 10.4)
- Does not interfere with normal API operations (requirement 10.5)

**State Management**:
```typescript
interface HealthState {
  isHealthy: boolean;
  lastCheck: Date | null;
  error: string | null;
}
```

### 5. Backend Startup Validation

**Location**: `api.py` (startup event handler)

**Implementation**:
```python
@app.on_event("startup")
async def validate_dependencies():
    # Check database (requirement 7.1)
    # Check Ollama (requirement 7.2)
    # Log errors and exit if dependencies unavailable (requirement 7.3)
    # Log successful startup (requirement 7.4)
```

**Validation Checks**:
1. Database connectivity test (10 second timeout)
2. Ollama connectivity test (10 second timeout)
3. Model availability verification
4. Log startup status with version and port

### 6. Service Startup Orchestration Script

**Location**: `start_services_enhanced.bat` / `start_services_enhanced.sh`

**Flow** (requirement 5):
1. Check PostgreSQL is running (requirement 5.1)
2. Check Ollama is running (requirement 5.2)
3. Start Backend and wait for health check (requirement 5.3)
4. Display error and exit if dependencies missing (requirement 5.4)
5. Wait up to 30 seconds for Backend health (requirement 5.5)
6. Display diagnostics if Backend doesn't become healthy (requirement 5.6)
7. Start Frontend once Backend is healthy

### 7. Network Diagnostics Script

**Location**: `scripts/diagnose_network.py` (new script)

**Functionality** (requirement 8):
- Tests Backend reachability from Frontend perspective (requirement 8.2)
- Verifies CORS configuration with test request (requirement 8.3)
- Checks for port conflicts on 3000 and 8000 (requirement 8.4)
- Provides specific remediation steps (requirement 8.5)

**Output Format**:
```
Network Diagnostics Report
==========================
✅ Backend reachable at http://localhost:8000
✅ CORS configured correctly
✅ No port conflicts detected
✅ All checks passed
```

## Data Models

### Health Check Response

```typescript
interface HealthResponse {
  status: "healthy" | "degraded" | "unhealthy";
  version: string;
  timestamp: string;
  services: {
    database: ServiceStatus;
    ollama: OllamaStatus;
  };
  uptime_seconds: number;
}

interface ServiceStatus {
  status: "up" | "down";
  latency_ms: number;
}

interface OllamaStatus extends ServiceStatus {
  model_loaded: boolean;
}
```

### API Error Response

```typescript
interface ApiError {
  type: "connection" | "timeout" | "server" | "client" | "network";
  message: string;
  details?: string;
  retryable: boolean;
  timestamp: string;
}
```

### Health Monitor State

```typescript
interface HealthMonitorState {
  isHealthy: boolean;
  lastCheck: Date | null;
  error: string | null;
  isPolling: boolean;
}
```


## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system—essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Server Errors Trigger Retries

*For any* HTTP request that fails with a 5xx server error status code (500-599), the API client should automatically retry the request up to the maximum retry limit.

**Validates: Requirements 4.3**

### Property 2: Client Errors Do Not Trigger Retries

*For any* HTTP request that fails with a 4xx client error status code (400-499), the API client should NOT retry the request and should immediately throw an error.

**Validates: Requirements 4.4**

### Property 3: Missing Response Fields Get Default Values

*For any* API response that is missing expected fields, the API client should provide sensible default values for those fields rather than throwing an error, ensuring the application remains functional.

**Validates: Requirements 9.3**

## Error Handling

### Error Classification

The system classifies errors into five categories:

1. **Connection Errors**: Cannot establish connection to Backend
   - User message: "Cannot connect to server. Please ensure the backend is running."
   - Retryable: Yes
   - Action: Retry with exponential backoff

2. **Timeout Errors**: Request exceeds configured timeout
   - User message: "Request timed out. The server may be overloaded."
   - Retryable: Yes (for idempotent operations)
   - Action: Retry with exponential backoff

3. **Server Errors (5xx)**: Backend encountered an error
   - User message: Display error from Backend response
   - Retryable: Yes
   - Action: Retry with exponential backoff

4. **Client Errors (4xx)**: Invalid request from Frontend
   - User message: Display error from Backend response
   - Retryable: No
   - Action: Display error to user with retry button (manual retry)

5. **Network Errors**: DNS failure, network unreachable, etc.
   - User message: "Network error. Please check your connection."
   - Retryable: Yes
   - Action: Retry with exponential backoff

### Error Response Format

All API errors follow a consistent format:

```typescript
interface ApiError {
  type: "connection" | "timeout" | "server" | "client" | "network";
  message: string;        // User-friendly message
  details?: string;       // Technical details for debugging
  retryable: boolean;     // Whether automatic retry is appropriate
  timestamp: string;      // ISO 8601 timestamp
  operation?: string;     // Which operation failed (e.g., "getAgents")
}
```

### Frontend Error Display

The Frontend displays errors using a toast notification system with:
- Error icon and color-coded severity
- User-friendly message
- Retry button (for retryable errors)
- "Show details" expandable section (for technical details)
- Auto-dismiss after 10 seconds (for non-critical errors)

### Backend Error Logging

The Backend logs all errors with:
- Timestamp
- Request ID (for tracing)
- Endpoint and method
- Error type and message
- Stack trace (for 500 errors)
- Client IP and user agent

## Testing Strategy

### Dual Testing Approach

This feature requires both unit tests and property-based tests to ensure comprehensive coverage:

**Unit Tests**: Focus on specific examples, edge cases, and integration points
- Health check endpoint returns correct structure
- CORS headers are present in responses
- Timeout configuration for each operation type
- Retry behavior for specific error scenarios
- Startup script dependency checking
- Error message display in UI

**Property-Based Tests**: Verify universal properties across all inputs
- All 5xx errors trigger retries (Property 1)
- All 4xx errors do not trigger retries (Property 2)
- All responses with missing fields get defaults (Property 3)

### Unit Testing Focus Areas

1. **Health Check Endpoint**
   - Returns 200 when all services healthy
   - Returns 503 when any service unhealthy
   - Response includes all required fields
   - Response time under 2 seconds

2. **CORS Configuration**
   - Preflight requests return correct headers
   - Requests from localhost:3000 are allowed
   - Requests from other origins are blocked

3. **Timeout Configuration**
   - Health checks timeout at 5 seconds
   - Agent operations timeout at 10 seconds
   - Uploads timeout at 30 seconds
   - Chat queries timeout at 90 seconds

4. **Retry Logic**
   - Retries happen 3 times maximum
   - Exponential backoff timing (1s, 2s, 4s)
   - Network errors trigger retries
   - Final error includes last failure reason

5. **Service Orchestration**
   - Script checks PostgreSQL before starting Backend
   - Script checks Ollama before starting Backend
   - Script waits for Backend health before starting Frontend
   - Script exits with error if dependencies missing

6. **Error Handling**
   - Connection errors show correct message
   - Timeout errors show correct message
   - Server errors display Backend message
   - Retry button appears for retryable errors

7. **Health Monitoring**
   - Polls every 30 seconds when tab visible
   - Stops polling when tab hidden
   - Displays banner when Backend unhealthy
   - Dismisses banner when Backend recovers

### Property-Based Testing Configuration

**Library**: fast-check (for TypeScript/JavaScript)

**Configuration**:
- Minimum 100 iterations per property test
- Each test tagged with feature name and property number
- Tag format: `Feature: nextjs-fastapi-integration-fix, Property {N}: {description}`

**Property Test Implementations**:

1. **Property 1: Server Errors Trigger Retries**
   - Generate random 5xx status codes (500-599)
   - Mock API responses with these status codes
   - Verify retry logic is invoked
   - Verify retry count reaches maximum (3)

2. **Property 2: Client Errors Do Not Trigger Retries**
   - Generate random 4xx status codes (400-499)
   - Mock API responses with these status codes
   - Verify retry logic is NOT invoked
   - Verify error is thrown immediately

3. **Property 3: Missing Response Fields Get Default Values**
   - Generate random API responses with various missing fields
   - Verify default values are provided for missing fields
   - Verify application does not crash
   - Verify default values are type-appropriate

### Integration Testing

Integration tests verify end-to-end flows:

1. **Startup Flow**
   - Start all services in order
   - Verify Frontend can reach Backend
   - Verify health check passes
   - Verify API operations work

2. **Error Recovery Flow**
   - Stop Backend while Frontend running
   - Verify Frontend detects unhealthy state
   - Restart Backend
   - Verify Frontend detects recovery

3. **CORS Flow**
   - Make requests from Frontend to Backend
   - Verify CORS headers present
   - Verify requests succeed

### Manual Testing Checklist

- [ ] Start services with startup script
- [ ] Verify health check passes on Frontend load
- [ ] Stop Backend and verify error message
- [ ] Restart Backend and verify recovery
- [ ] Test agent creation with Backend running
- [ ] Test document upload with Backend running
- [ ] Test chat query with Backend running
- [ ] Verify timeout errors display correctly
- [ ] Verify retry logic works for transient failures
- [ ] Run diagnostic script and verify output

## Implementation Notes

### Backward Compatibility

This fix maintains backward compatibility with existing API contracts. No breaking changes to:
- API endpoint URLs
- Request/response formats
- Authentication mechanisms

### Performance Considerations

1. **Health Check Caching**: Health check results cached for 5 seconds to avoid overwhelming Backend
2. **Retry Backoff**: Exponential backoff prevents retry storms
3. **Timeout Tuning**: Different timeouts for different operations optimize for both speed and reliability
4. **Polling Optimization**: Health monitoring pauses when tab hidden to save resources

### Security Considerations

1. **CORS Allowlist**: Explicit origin allowlist instead of wildcard prevents unauthorized access
2. **Error Messages**: User-facing error messages don't expose sensitive system details
3. **Logging**: Backend logs include request IDs for security auditing

### Deployment Strategy

1. Deploy Backend changes first (health endpoint, CORS, startup validation)
2. Verify Backend health endpoint works
3. Deploy Frontend changes (health check integration, enhanced error handling)
4. Update startup scripts
5. Test end-to-end flow
6. Monitor error rates and health check metrics

### Monitoring and Observability

Add metrics for:
- Health check success/failure rate
- API request retry rate
- Timeout occurrence rate
- CORS error rate
- Service startup time
- Time to healthy state

These metrics help identify issues early and track improvement over time.
