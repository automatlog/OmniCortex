// OmniCortex API Client
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
  maxHistory: number = 5
): Promise<QueryResponse> {
  const res = await fetch(`${API_BASE}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      agent_id: agentId,
      model_selection: modelSelection,
      max_history: maxHistory,
    }),
  });
  if (!res.ok) throw new Error("Failed to send message");
  return res.json();
}

// Updated for FastAPI endpoint: /agents/{agentId}/documents
export async function uploadDocuments(
  agentId: string,
  files: File[]
): Promise<void> {
  const formData = new FormData();
  files.forEach((file) => {
    formData.append("files", file); // Key must match FastAPI: files: List[UploadFile]
  });

  // Note: /agents/{id}/documents expects 'files' in form data
  const res = await fetch(`${API_BASE}/agents/${agentId}/documents`, {
    method: "POST",
    body: formData,
  });
  
  if (!res.ok) {
    const error = await res.text();
    throw new Error(`Failed to upload documents: ${error}`);
  }
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

// Health check
export async function checkHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/`);
    return res.ok;
  } catch {
    return false;
  }
}
