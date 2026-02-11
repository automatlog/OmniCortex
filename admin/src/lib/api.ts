// OmniCortex API Client - Enhanced with Health Checks and Retry Logic
// Connects to FastAPI backend at localhost:8000

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Tiered Timeout Configuration
// Different operations have different timeout requirements based on expected duration
const TIMEOUTS = {
  HEALTH_CHECK: 5000,      // 5 seconds - Quick health verification
  AGENT_OPERATIONS: 10000, // 10 seconds - CRUD operations (list, create, delete)
  DOCUMENT_UPLOAD: 30000,  // 30 seconds - File upload and processing
  CHAT_QUERY: 90000,       // 90 seconds - LLM inference and response generation
} as const;

// Health check cache
let healthCache: { isHealthy: boolean; timestamp: number } | null = null;
const HEALTH_CACHE_TTL = 5000; // 5 seconds

// Types
export interface Agent {
  id: string;
  name: string;
  description: string;
  created_at: string;
  document_count?: number;
  webhook_url?: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  timestamp?: string;
}

export interface QueryResponse {
  answer: string;
  agent_id: string;
}

export interface Document {
  id: number;
  filename: string;
  file_type: string;
  file_size: number;
  content_preview: string;
  chunk_count: number;
  uploaded_at: string;
  embedding_time: number;
}

export interface HealthResponse {
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

export interface ApiError {
  type: "connection" | "timeout" | "server" | "client" | "network";
  message: string;
  details?: string;
  retryable: boolean;
  timestamp: string;
  operation?: string;
}

// Enhanced fetch with timeout
const fetchWithTimeout = async (url: string, options: RequestInit = {}, timeout = 30000) => {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeout);
  
  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
    });
    clearTimeout(id);
    return response;
  } catch (error) {
    clearTimeout(id);
    if (error instanceof Error && error.name === 'AbortError') {
      throw new Error(`Request timeout after ${timeout}ms`);
    }
    throw error;
  }
};

// Check health with caching
async function checkHealthWithCache(): Promise<boolean> {
  const now = Date.now();
  
  // Return cached result if fresh
  if (healthCache && (now - healthCache.timestamp) < HEALTH_CACHE_TTL) {
    return healthCache.isHealthy;
  }
  
  // Perform fresh health check
  try {
    const response = await fetchWithTimeout(`${API_BASE}/health`, {}, TIMEOUTS.HEALTH_CHECK);
    const isHealthy = response.ok;
    
    healthCache = { isHealthy, timestamp: now };
    return isHealthy;
  } catch (error) {
    healthCache = { isHealthy: false, timestamp: now };
    return false;
  }
}

// Create classified API error
function createApiError(
  type: ApiError["type"],
  message: string,
  details?: string,
  operation?: string
): ApiError {
  return {
    type,
    message,
    details,
    retryable: type === "server" || type === "timeout" || type === "network" || type === "connection",
    timestamp: new Date().toISOString(),
    operation,
  };
}

// Classify error based on error object and response
function classifyError(error: unknown, response?: Response, operation?: string): ApiError {
  // Handle already classified errors
  if (error && typeof error === 'object' && 'type' in error && 'timestamp' in error) {
    return error as ApiError;
  }

  const errorMessage = error instanceof Error ? error.message : String(error);
  
  // Connection errors - cannot establish connection
  if (errorMessage.includes("Failed to fetch") || 
      errorMessage.includes("NetworkError") ||
      errorMessage.includes("ECONNREFUSED") ||
      errorMessage.includes("ENOTFOUND") ||
      errorMessage.includes("Health check failed")) {
    return createApiError(
      "connection",
      "Cannot connect to server. Please ensure the backend is running.",
      errorMessage,
      operation
    );
  }
  
  // Timeout errors
  if (errorMessage.includes("timeout") || 
      errorMessage.includes("AbortError") ||
      (error instanceof Error && error.name === "AbortError")) {
    return createApiError(
      "timeout",
      "Request timed out. The server may be overloaded.",
      errorMessage,
      operation
    );
  }
  
  // Server errors (5xx) - if we have a response
  if (response && response.status >= 500) {
    return createApiError(
      "server",
      "Server error occurred. Please try again later.",
      errorMessage,
      operation
    );
  }
  
  // Client errors (4xx) - if we have a response
  if (response && response.status >= 400 && response.status < 500) {
    return createApiError(
      "client",
      errorMessage || "Invalid request. Please check your input.",
      undefined,
      operation
    );
  }
  
  // Network errors - general network issues
  if (errorMessage.includes("network") || 
      errorMessage.includes("DNS") ||
      errorMessage.includes("ETIMEDOUT") ||
      (error instanceof TypeError && errorMessage.includes("fetch"))) {
    return createApiError(
      "network",
      "Network error. Please check your connection.",
      errorMessage,
      operation
    );
  }
  
  // Default to network error for unknown errors
  return createApiError(
    "network",
    "An unexpected error occurred.",
    errorMessage,
    operation
  );
}

// Retry logic with exponential backoff
const fetchWithRetry = async (
  url: string, 
  options: RequestInit = {}, 
  timeout = 30000,
  maxRetries = 3,
  retryDelay = 1000,
  operation?: string
): Promise<Response> => {
  let lastError: Error | null = null;
  let lastResponse: Response | null = null;
  
  for (let attempt = 0; attempt < maxRetries; attempt++) {
    try {
      const response = await fetchWithTimeout(url, options, timeout);
      
      // Client errors (4xx) should NOT be retried
      if (response.status >= 400 && response.status < 500) {
        console.log(`[${operation}] Client error ${response.status}, not retrying (attempt ${attempt + 1}/${maxRetries})`);
        return response;
      }
      
      // Server errors (5xx) should be retried
      if (response.status >= 500) {
        lastResponse = response;
        if (attempt < maxRetries - 1) {
          const delay = retryDelay * Math.pow(2, attempt);
          console.warn(`[${operation}] Server error ${response.status}, retrying in ${delay}ms (attempt ${attempt + 1}/${maxRetries})`);
          await new Promise(resolve => setTimeout(resolve, delay));
          continue;
        } else {
          // Last attempt, return the response with error
          console.error(`[${operation}] Server error ${response.status} after ${maxRetries} attempts`);
          return response;
        }
      }
      
      // Success response
      return response;
    } catch (error) {
      lastError = error as Error;
      
      // Network errors should be retried
      const isNetworkError = error instanceof Error && (
        error.message.includes("fetch") ||
        error.message.includes("network") ||
        error.message.includes("timeout") ||
        error.name === "AbortError" ||
        error.name === "TypeError"
      );
      
      if (isNetworkError && attempt < maxRetries - 1) {
        const delay = retryDelay * Math.pow(2, attempt);
        const errorMsg = error instanceof Error ? error.message : String(error);
        console.warn(`[${operation}] Network error, retrying in ${delay}ms (attempt ${attempt + 1}/${maxRetries}): ${errorMsg}`);
        await new Promise(resolve => setTimeout(resolve, delay));
        continue;
      } else if (attempt === maxRetries - 1) {
        // Last attempt, throw error with context
        const errorMsg = error instanceof Error ? error.message : String(error);
        console.error(`[${operation}] Request failed after ${maxRetries} attempts: ${errorMsg}`);
        const enhancedError = new Error(`${operation || 'Request'} failed after ${maxRetries} attempts: ${errorMsg}`);
        enhancedError.cause = error;
        throw enhancedError;
      } else {
        // Non-retryable error, throw immediately
        throw error;
      }
    }
  }
  
  // If we exhausted retries with server errors, throw with last error info
  if (lastResponse) {
    const errorText = await lastResponse.text().catch(() => 'Unknown error');
    throw new Error(`${operation || 'Request'} failed with status ${lastResponse.status} after ${maxRetries} attempts: ${errorText}`);
  }
  
  throw lastError || new Error(`${operation || 'Request'} failed after ${maxRetries} retries`);
};

// Fetch with health check integration
async function fetchWithHealthCheck(
  url: string,
  options: RequestInit = {},
  timeout: number = 30000,
  operation?: string
): Promise<Response> {
  // Check health first
  const isHealthy = await checkHealthWithCache();
  
  if (!isHealthy) {
    throw createApiError(
      "connection",
      "Cannot connect to server. Please ensure the backend is running.",
      "Health check failed",
      operation
    );
  }
  
  // Proceed with request
  try {
    const response = await fetchWithRetry(url, options, timeout, 3, 1000, operation);
    return response;
  } catch (error) {
    // Classify and throw error
    throw classifyError(error, undefined, operation);
  }
}

export async function getAgents(): Promise<Agent[]> {
  try {
    const res = await fetchWithHealthCheck(`${API_BASE}/agents`, {}, TIMEOUTS.AGENT_OPERATIONS, "getAgents");
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: "Failed to fetch agents" }));
      throw classifyError(new Error(error.detail || "Failed to fetch agents"), res, "getAgents");
    }
    return res.json();
  } catch (error) {
    throw classifyError(error, undefined, "getAgents");
  }
}

export async function getAgent(id: string): Promise<Agent> {
  try {
    const res = await fetchWithHealthCheck(`${API_BASE}/agents/${id}`, {}, TIMEOUTS.AGENT_OPERATIONS, "getAgent");
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: "Failed to fetch agent" }));
      throw classifyError(new Error(error.detail || "Failed to fetch agent"), res, "getAgent");
    }
    return res.json();
  } catch (error) {
    throw classifyError(error, undefined, "getAgent");
  }
}

export async function createAgent(data: {
  name: string;
  description?: string;
}): Promise<Agent> {
  try {
    const res = await fetchWithHealthCheck(`${API_BASE}/agents`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }, TIMEOUTS.AGENT_OPERATIONS, "createAgent");
    
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: "Failed to create agent" }));
      throw classifyError(new Error(error.detail || "Failed to create agent"), res, "createAgent");
    }
    return res.json();
  } catch (error) {
    throw classifyError(error, undefined, "createAgent");
  }
}

export async function deleteAgent(id: string): Promise<void> {
  try {
    const res = await fetchWithHealthCheck(`${API_BASE}/agents/${id}`, { method: "DELETE" }, TIMEOUTS.AGENT_OPERATIONS, "deleteAgent");
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: "Failed to delete agent" }));
      throw classifyError(new Error(error.detail || "Failed to delete agent"), res, "deleteAgent");
    }
  } catch (error) {
    throw classifyError(error, undefined, "deleteAgent");
  }
}

export async function sendMessage(
  question: string,
  agentId: string,
  modelSelection: string = "Meta Llama 3.1",
  maxHistory: number = 5,
  verbosity: string = "medium"
): Promise<QueryResponse> {
  try {
    const res = await fetchWithHealthCheck(`${API_BASE}/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        agent_id: agentId,
        model_selection: modelSelection,
        max_history: maxHistory,
        verbosity: verbosity,
      }),
    }, TIMEOUTS.CHAT_QUERY, "sendMessage"); // 90s timeout for chat
    
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: "Failed to send message" }));
      throw classifyError(new Error(error.detail || "Failed to send message"), res, "sendMessage");
    }
    return res.json();
  } catch (error) {
    throw classifyError(error, undefined, "sendMessage");
  }
}

// Document Management
export async function getAgentDocuments(agentId: string): Promise<Document[]> {
  try {
    const res = await fetchWithHealthCheck(`${API_BASE}/agents/${agentId}/documents`, {}, TIMEOUTS.AGENT_OPERATIONS, "getAgentDocuments");
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: "Failed to fetch documents" }));
      throw classifyError(new Error(error.detail || "Failed to fetch documents"), res, "getAgentDocuments");
    }
    return res.json();
  } catch (error) {
    throw classifyError(error, undefined, "getAgentDocuments");
  }
}

export async function uploadDocuments(
  agentId: string,
  files: File[]
): Promise<void> {
  try {
    const formData = new FormData();
    files.forEach((file) => {
      formData.append("files", file);
    });

    const res = await fetchWithHealthCheck(`${API_BASE}/agents/${agentId}/documents`, {
      method: "POST",
      body: formData,
    }, TIMEOUTS.DOCUMENT_UPLOAD, "uploadDocuments"); // 30 second timeout
    
    if (!res.ok) {
      const error = await res.text();
      throw classifyError(new Error(`Failed to upload documents: ${error}`), res, "uploadDocuments");
    }
  } catch (error) {
    throw classifyError(error, undefined, "uploadDocuments");
  }
}

export async function uploadDocumentsAsText(
  agentId: string,
  documents: Array<{ filename: string; text: string }>
): Promise<void> {
  try {
    // Send each document as text
    for (const doc of documents) {
      const formData = new FormData();
      formData.append("text", doc.text);
      
      const res = await fetchWithHealthCheck(`${API_BASE}/agents/${agentId}/documents`, {
        method: "POST",
        body: formData,
      }, TIMEOUTS.DOCUMENT_UPLOAD, "uploadDocumentsAsText"); // 30 second timeout
      
      if (!res.ok) {
        const error = await res.text();
        throw classifyError(new Error(`Failed to upload ${doc.filename}: ${error}`), res, "uploadDocumentsAsText");
      }
    }
  } catch (error) {
    throw classifyError(error, undefined, "uploadDocumentsAsText");
  }
}

export async function deleteDocument(docId: number): Promise<void> {
  try {
    const res = await fetchWithHealthCheck(`${API_BASE}/documents/${docId}`, {
      method: "DELETE"
    }, TIMEOUTS.AGENT_OPERATIONS, "deleteDocument");
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: "Failed to delete document" }));
      throw classifyError(new Error(error.detail || "Failed to delete document"), res, "deleteDocument");
    }
  } catch (error) {
    throw classifyError(error, undefined, "deleteDocument");
  }
}

export async function sendVoice(
  agentId: string,
  audioBlob: Blob
): Promise<{ transcription: string; response: string }> {
  try {
    const formData = new FormData();
    formData.append("audio", audioBlob, "recording.wav");
    formData.append("agent_id", agentId);

    const res = await fetchWithHealthCheck(`${API_BASE}/voice/chat`, {
      method: "POST",
      body: formData,
    }, TIMEOUTS.CHAT_QUERY, "sendVoice"); // Use chat timeout for voice processing
    
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: "Failed to process voice" }));
      throw classifyError(new Error(error.detail || "Failed to process voice"), res, "sendVoice");
    }
    return res.json();
  } catch (error) {
    throw classifyError(error, undefined, "sendVoice");
  }
}

// Usage Stats
export async function getUsageStats(limit: number = 100) {
  try {
    const res = await fetchWithHealthCheck(`${API_BASE}/stats/agents?limit=${limit}`, {}, TIMEOUTS.AGENT_OPERATIONS, "getUsageStats");
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: "Failed to fetch stats" }));
      throw classifyError(new Error(error.detail || "Failed to fetch stats"), res, "getUsageStats");
    }
    return res.json();
  } catch (error) {
    throw classifyError(error, undefined, "getUsageStats");
  }
}

// Conversation History
export async function getConversationHistory(agentId: string, limit: number = 50): Promise<ChatMessage[]> {
  try {
    const res = await fetchWithHealthCheck(
      `${API_BASE}/agents/${agentId}/history?limit=${limit}`,
      {},
      TIMEOUTS.AGENT_OPERATIONS,
      "getConversationHistory"
    );
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: "Failed to fetch history" }));
      throw classifyError(new Error(error.detail || "Failed to fetch history"), res, "getConversationHistory");
    }
    return res.json();
  } catch (error) {
    throw classifyError(error, undefined, "getConversationHistory");
  }
}

// Health check
export async function checkHealth(): Promise<HealthResponse> {
  try {
    const res = await fetchWithTimeout(`${API_BASE}/health`, {}, TIMEOUTS.HEALTH_CHECK);
    if (!res.ok) {
      throw new Error(`Health check failed with status ${res.status}`);
    }
    return res.json();
  } catch (error) {
    throw classifyError(error, undefined, "checkHealth");
  }
}

// Check if backend is healthy (simple boolean check)
export async function isBackendHealthy(): Promise<boolean> {
  return checkHealthWithCache();
}

// Check if Ollama is running and model is loaded
export async function checkOllamaHealth(): Promise<{ healthy: boolean; message: string }> {
  try {
    const health = await checkHealth();
    const ollamaService = health.services.ollama;
    
    if (ollamaService.status === "up" && ollamaService.model_loaded) {
      return { healthy: true, message: "All systems operational" };
    }
    
    if (ollamaService.status === "down") {
      return { healthy: false, message: "Ollama is not running. Start with: ollama serve" };
    }
    
    if (!ollamaService.model_loaded) {
      return { healthy: false, message: "Model not loaded. Run: ollama pull llama3.2:3b" };
    }
    
    return { healthy: false, message: "Unknown Ollama status" };
  } catch (error) {
    return { 
      healthy: false, 
      message: error instanceof Error ? error.message : "Connection failed" 
    };
  }
}
