# Implementation Plan: Next.js to FastAPI Integration Fix

## Overview

This implementation plan addresses the "Failed to fetch" errors between the Next.js frontend and FastAPI backend. Most core functionality has been implemented, including health checks, retry logic, CORS configuration, and error handling. This refreshed task list focuses on remaining work: service orchestration scripts, testing, UI improvements, and documentation.

## Implementation Status

**✅ Completed:**
- Backend health check endpoint with caching (`/health` in `api.py`)
- Enhanced CORS configuration with explicit origin allowlist
- Backend startup validation with dependency checking
- API client health check integration (`admin/src/lib/api.ts`)
- Tiered timeout configuration (5s/10s/30s/90s)
- Enhanced retry logic with exponential backoff
- Error classification and handling (ApiError types)
- Frontend health monitor component (`admin/src/components/HealthMonitor.tsx`)
- Network diagnostics script (`scripts/diagnose_network.py`)

**🔨 Remaining Work:**
- Service startup orchestration scripts
- Comprehensive test suite (unit + property-based)
- Frontend error display UI enhancements
- Frontend startup health check integration
- Documentation updates

## Tasks

### Service Orchestration

- [ ] 1. Create enhanced service startup scripts
  - [ ] 1.1 Create `start_services.bat` for Windows
    - Check PostgreSQL connectivity on port 5433 (exit with error if not running)
    - Check Ollama connectivity on port 11434 (exit with error if not running)
    - Start Backend process (FastAPI on port 8000) in new terminal
    - Poll Backend `/health` endpoint every 2 seconds (max 30 seconds)
    - Display diagnostic information if Backend doesn't become healthy
    - Start Frontend process (Next.js on port 3000) in new terminal once Backend is healthy
    - Use `start` command to open new terminal windows for each service
    - Design reference: Components section 6, Service Startup Flow
    - _Requirements: 5.1, 5.2, 5.3, 5.5, 5.6_

  - [ ] 1.2 Create `start_services.sh` for Linux/Mac
    - Implement same logic as Windows version
    - Use bash-compatible commands for port checking (nc or curl)
    - Use appropriate process management for Unix systems (background processes or tmux)
    - Make script executable with proper shebang
    - Design reference: Components section 6, Service Startup Flow
    - _Requirements: 5.1, 5.2, 5.3, 5.5, 5.6_

  - [ ]* 1.3 Write integration tests for startup scripts
    - Test script exits with error when PostgreSQL not running
    - Test script exits with error when Ollama not running
    - Test script waits for Backend health before starting Frontend
    - Test script displays diagnostics when Backend doesn't become healthy within 30s
    - _Requirements: 5.1, 5.2, 5.3, 5.5, 5.6_

### Backend Testing

- [ ] 2. Write Backend unit tests
  - [ ]* 2.1 Write unit tests for health check endpoint
    - Test healthy state (all services up) returns 200 with correct structure
    - Test unhealthy database returns 503 with appropriate status
    - Test unhealthy Ollama returns 503 with appropriate status
    - Test response includes all required fields (status, version, timestamp, services, uptime)
    - Test response time is under 2 seconds
    - Test caching works (subsequent calls within 5 seconds return cached result)
    - File: `tests/test_health_endpoint.py`
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [ ]* 2.2 Write unit tests for CORS configuration
    - Test preflight OPTIONS requests return correct CORS headers
    - Test requests from `http://localhost:3000` are allowed
    - Test requests from `http://127.0.0.1:3000` are allowed
    - Test requests from other origins are blocked
    - Test CORS headers include credentials, methods, and headers
    - File: `tests/test_cors.py`
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [ ]* 2.3 Write unit tests for startup validation
    - Test startup succeeds when all dependencies available
    - Test startup fails and exits when database unavailable
    - Test startup fails and exits when Ollama unavailable
    - Test appropriate error messages are logged
    - File: `tests/test_startup_validation.py` (may already exist)
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

### Frontend API Client Testing

- [ ] 3. Write Frontend API client tests
  - [ ]* 3.1 Write unit tests for health check integration
    - Test `checkHealthWithCache()` caches results for 5 seconds
    - Test `fetchWithHealthCheck()` checks health before proceeding
    - Test descriptive error thrown when Backend unhealthy
    - Test API functions use health-aware fetch
    - File: `admin/src/lib/api.test.ts` (already exists, extend it)
    - _Requirements: 1.1, 1.2_

  - [ ]* 3.2 Write unit tests for timeout configuration
    - Test health checks timeout at 5 seconds
    - Test agent operations timeout at 10 seconds
    - Test uploads timeout at 30 seconds
    - Test chat queries timeout at 90 seconds
    - Test timeout errors include operation name for debugging
    - File: `admin/src/lib/api.test.ts`
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

  - [ ]* 3.3 Write property test for server error retries
    - **Property 1: Server Errors Trigger Retries**
    - **Validates: Design Property 1**
    - Use fast-check to generate random 5xx status codes (500-599)
    - Mock API responses with generated status codes
    - Verify retry logic is invoked for each status code
    - Verify retry count reaches maximum (3 attempts)
    - Run minimum 100 iterations
    - Tag: `Feature: nextjs-fastapi-integration-fix, Property 1: Server Errors Trigger Retries`
    - File: `admin/src/lib/api.property.test.ts` (new file)
    - _Requirements: 4.3_

  - [ ]* 3.4 Write property test for client error no-retry
    - **Property 2: Client Errors Do Not Trigger Retries**
    - **Validates: Design Property 2**
    - Use fast-check to generate random 4xx status codes (400-499)
    - Mock API responses with generated status codes
    - Verify retry logic is NOT invoked for any status code
    - Verify error is thrown immediately without retry
    - Run minimum 100 iterations
    - Tag: `Feature: nextjs-fastapi-integration-fix, Property 2: Client Errors Do Not Trigger Retries`
    - File: `admin/src/lib/api.property.test.ts`
    - _Requirements: 4.4_

  - [ ]* 3.5 Write property test for missing field defaults
    - **Property 3: Missing Response Fields Get Default Values**
    - **Validates: Design Property 3**
    - Use fast-check to generate API responses with various missing fields
    - Verify default values are provided for missing fields
    - Verify application doesn't crash or throw errors
    - Verify default values are type-appropriate (empty arrays, null, etc.)
    - Run minimum 100 iterations
    - Tag: `Feature: nextjs-fastapi-integration-fix, Property 3: Missing Response Fields Get Default Values`
    - File: `admin/src/lib/api.property.test.ts`
    - _Requirements: 9.3_

  - [ ]* 3.6 Write unit tests for retry logic
    - Test exponential backoff timing (1s, 2s, 4s)
    - Test network errors trigger retries
    - Test final error includes last failure reason
    - Test maximum 3 retry attempts enforced
    - Test retry attempt logging includes attempt number
    - File: `admin/src/lib/api.test.ts`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [ ]* 3.7 Write unit tests for error classification
    - Test connection errors produce correct error type and user message
    - Test timeout errors produce correct error type and user message
    - Test server errors include Backend error message in details
    - Test empty responses throw descriptive error
    - Test malformed JSON throws descriptive error
    - Test status code validation occurs before JSON parsing
    - File: `admin/src/lib/api.test.ts`
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

### Frontend UI Implementation

- [ ] 4. Enhance Frontend error display
  - [ ] 4.1 Create or enhance toast notification component for API errors
    - Create reusable toast component with error icon and color-coded severity
    - Display user-friendly error messages based on `ApiError.type`
    - Add retry button for retryable errors that re-invokes the failed operation
    - Add expandable "Show details" section for technical details
    - Implement auto-dismiss after 10 seconds for non-critical errors
    - Log all API errors to browser console with full details
    - File: `admin/src/components/ErrorToast.tsx` (new or enhance existing)
    - Design reference: Error Handling section
    - _Requirements: 9.1, 9.2, 9.4, 9.5_

  - [ ]* 4.2 Write unit tests for error display
    - Test connection error shows correct message
    - Test timeout error shows correct message
    - Test server error displays Backend message
    - Test retry button appears only for retryable errors
    - Test auto-dismiss works for non-critical errors
    - File: `admin/src/components/ErrorToast.test.tsx`
    - _Requirements: 9.1, 9.2, 9.4, 9.5_

- [ ] 5. Integrate health check on Frontend startup
  - [ ] 5.1 Update main layout or page component to check Backend health
    - Check Backend health before rendering main interface
    - Display loading state with spinner while checking health
    - Display error message with troubleshooting guidance if Backend unhealthy
    - Implement automatic retry every 5 seconds until Backend available
    - Provide manual retry button for user control
    - File: `admin/src/app/layout.tsx` or `admin/src/app/page.tsx`
    - Design reference: Components section 4
    - _Requirements: 6.1, 6.2, 6.3_

  - [ ]* 5.2 Write unit tests for startup health check
    - Test health check called before main interface renders
    - Test loading state displayed during health check
    - Test error message displayed when Backend unhealthy
    - Test automatic retry occurs every 5 seconds
    - Test manual retry button works
    - File: `admin/src/app/page.test.tsx`
    - _Requirements: 6.1, 6.2, 6.3_

### Frontend Health Monitor Testing

- [ ] 6. Write tests for HealthMonitor component
  - [ ]* 6.1 Write unit tests for health monitor
    - Test polling occurs every 30 seconds when tab visible
    - Test polling stops when tab hidden
    - Test polling resumes when tab becomes visible
    - Test warning banner displays when Backend unhealthy
    - Test banner dismisses when Backend recovers
    - Test banner can be manually dismissed
    - File: `admin/src/components/HealthMonitor.test.tsx`
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

### Diagnostics Testing

- [ ] 7. Write tests for diagnostics script
  - [ ]* 7.1 Write unit tests for diagnostics script
    - Test Backend reachability check works
    - Test CORS verification detects misconfigurations
    - Test port conflict detection works
    - Test remediation steps are provided for each issue type
    - Test health endpoint check works
    - File: `tests/test_diagnose_network.py`
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

### Documentation

- [ ] 8. Update project documentation
  - [ ] 8.1 Update README with startup instructions
    - Document new startup scripts (`start_services.bat` and `start_services.sh`)
    - Add troubleshooting section referencing diagnostic script
    - Document health check endpoint and monitoring
    - Add section on error handling and retry behavior
    - File: `README.md`

  - [ ] 8.2 Create API documentation for health endpoint
    - Document `/health` endpoint request/response format
    - Document health status meanings (healthy, degraded, unhealthy)
    - Document service status fields (database, ollama)
    - Add examples of health responses
    - File: `docs/API.md` or add to existing API docs

  - [ ] 8.3 Create troubleshooting guide
    - Document common connection issues and solutions
    - Document timeout configuration for different operations
    - Document error types and their meanings
    - Add diagnostic script usage instructions
    - Reference deployment strategy from design document
    - File: `docs/TROUBLESHOOTING.md` (new file)

### Final Verification

- [ ] 9. Final checkpoint - Verify complete integration
  - [ ] 9.1 Run all Backend tests
    - Run pytest for all Backend unit tests
    - Verify all tests pass
    - Check test coverage for health, CORS, and startup validation

  - [ ] 9.2 Run all Frontend tests
    - Run npm test for all Frontend unit tests
    - Run property-based tests (min 100 iterations each)
    - Verify all tests pass
    - Check test coverage for api.ts and components

  - [ ] 9.3 Test manual startup flow
    - Test startup script on Windows (if applicable)
    - Test startup script on Linux/Mac (if applicable)
    - Verify services start in correct order
    - Verify health checks pass before Frontend starts

  - [ ] 9.4 Test error recovery flow
    - Start all services normally
    - Stop Backend while Frontend running
    - Verify Frontend detects unhealthy state and shows banner
    - Restart Backend
    - Verify Frontend detects recovery and dismisses banner

  - [ ] 9.5 Test end-to-end functionality
    - Test agent creation with Backend running
    - Test document upload with Backend running
    - Test chat query with Backend running
    - Verify timeout errors display correctly
    - Verify retry logic works for transient failures
    - Run diagnostic script and verify output

  - [ ] 9.6 Final review and user confirmation
    - Review all completed tasks
    - Verify all documentation is updated
    - Ask the user if questions arise or if additional work is needed

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Most core functionality is already implemented and working
- Focus is on testing, orchestration scripts, and documentation
- Property tests use fast-check library and run minimum 100 iterations each
- Each property test validates a specific correctness property from the design document
- Unit tests validate specific examples, edge cases, and integration points
- Integration tests verify end-to-end flows across Frontend and Backend
- The final checkpoint ensures all components work together correctly
- All tasks reference specific design sections and requirements for implementation guidance
