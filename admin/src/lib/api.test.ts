// Manual test file for error classification
// This file demonstrates the error classification logic

import { ApiError } from './api';

// Mock test cases to verify error classification
const testCases = [
  {
    name: "Connection Error - Failed to fetch",
    error: new Error("Failed to fetch"),
    expectedType: "connection",
    expectedRetryable: true,
  },
  {
    name: "Connection Error - ECONNREFUSED",
    error: new Error("ECONNREFUSED"),
    expectedType: "connection",
    expectedRetryable: true,
  },
  {
    name: "Timeout Error - timeout in message",
    error: new Error("Request timeout after 5000ms"),
    expectedType: "timeout",
    expectedRetryable: true,
  },
  {
    name: "Timeout Error - AbortError",
    error: Object.assign(new Error("The operation was aborted"), { name: "AbortError" }),
    expectedType: "timeout",
    expectedRetryable: true,
  },
  {
    name: "Network Error - network in message",
    error: new Error("network error occurred"),
    expectedType: "network",
    expectedRetryable: true,
  },
  {
    name: "Network Error - DNS failure",
    error: new Error("DNS lookup failed"),
    expectedType: "network",
    expectedRetryable: true,
  },
];

// Note: To properly test this, you would need to:
// 1. Export the classifyError function from api.ts
// 2. Run these tests with a test framework like Jest or Vitest
// 3. Verify that each error is classified correctly

// Example of what the test would look like:
/*
describe('Error Classification', () => {
  testCases.forEach(({ name, error, expectedType, expectedRetryable }) => {
    it(name, () => {
      const classified = classifyError(error, undefined, 'testOperation');
      expect(classified.type).toBe(expectedType);
      expect(classified.retryable).toBe(expectedRetryable);
      expect(classified.operation).toBe('testOperation');
      expect(classified.timestamp).toBeDefined();
    });
  });

  it('should classify 5xx responses as server errors', () => {
    const mockResponse = { status: 500 } as Response;
    const classified = classifyError(new Error('Server error'), mockResponse, 'testOp');
    expect(classified.type).toBe('server');
    expect(classified.retryable).toBe(true);
  });

  it('should classify 4xx responses as client errors', () => {
    const mockResponse = { status: 400 } as Response;
    const classified = classifyError(new Error('Bad request'), mockResponse, 'testOp');
    expect(classified.type).toBe('client');
    expect(classified.retryable).toBe(false);
  });

  it('should not re-classify already classified errors', () => {
    const apiError: ApiError = {
      type: 'timeout',
      message: 'Already classified',
      retryable: true,
      timestamp: new Date().toISOString(),
    };
    const result = classifyError(apiError, undefined, 'testOp');
    expect(result).toBe(apiError);
  });
});
*/

console.log('Error classification test cases defined. To run tests, set up a test framework.');
