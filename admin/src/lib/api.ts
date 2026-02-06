// OmniCortex API Client - UPDATED
// Connects to FastAPI backend at localhost:8000

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://jj8s2oaqa396jo-8000.proxy.runpod.net";

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

// API Functions
export async function getAgents(): Promise<Agent[]> {
  const res = await fetch(`${API_BASE}/agents`);
  if (!res.ok) throw new Error("Failed to fetch agents");
  return res.json();
}

export async function getAgent(id: string): Promise<Agent> {
  const res = await fetch(`${API_BASE}/agents/${id}`);
  if (!res.ok) throw new Error("Failed to fetch agent");
  return res.json();
}

export async function createAgent(data: {
  name: string;
  description?: string;
}): Promise<Agent> {
  const res = await fetch(`${API_BASE}/agents`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("Failed to create agent");
  return res.json();
}

export async function deleteAgent(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/agents/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to delete agent");
}

export async function sendMessage(
  question: string,
  agentId: string,
  modelSelection: string = "Meta Llama 3.1",
  maxHistory: number = 5,
  verbosity: string = "medium"
): Promise<QueryResponse> {
  const res = await fetch(`${API_BASE}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      agent_id: agentId,
      model_selection: modelSelection,
      max_history: maxHistory,
      verbosity: verbosity,
    }),
  });
  if (!res.ok) throw new Error("Failed to send message");
  return res.json();
}

// Document Management
export async function getAgentDocuments(agentId: string): Promise<Document[]> {
  const res = await fetch(`${API_BASE}/agents/${agentId}/documents`);
  if (!res.ok) throw new Error("Failed to fetch documents");
  return res.json();
}

export async function uploadDocuments(
  agentId: string,
  files: File[]
): Promise<void> {
  const formData = new FormData();
  files.forEach((file) => {
    formData.append("files", file);
  });

  const res = await fetch(`${API_BASE}/agents/${agentId}/documents`, {
    method: "POST",
    body: formData,
  });
  
  if (!res.ok) {
    const error = await res.text();
    throw new Error(`Failed to upload documents: ${error}`);
  }
}

export async function deleteDocument(docId: number): Promise<void> {
  const res = await fetch(`${API_BASE}/documents/${docId}`, {
    method: "DELETE"
  });
  if (!res.ok) throw new Error("Failed to delete document");
}

export async function sendVoice(
  agentId: string,
  audioBlob: Blob
): Promise<{ transcription: string; response: string }> {
  const formData = new FormData();
  formData.append("audio", audioBlob, "recording.wav");
  formData.append("agent_id", agentId);

  const res = await fetch(`${API_BASE}/voice/chat`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) throw new Error("Failed to process voice");
  return res.json();
}

// Usage Stats
export async function getUsageStats(limit: number = 100) {
  const res = await fetch(`${API_BASE}/stats/agents?limit=${limit}`);
  if (!res.ok) throw new Error("Failed to fetch stats");
  return res.json();
}

// Health check
export async function checkHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/`);
    return res.ok;
  } catch {
    return false;
  }
}
