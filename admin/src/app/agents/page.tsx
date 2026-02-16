"use client";

import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Briefcase, Plus, Search, Sparkles, Upload, User, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { AgentGrid } from "@/components/AgentCard";
import { createAgent, deleteAgent, getAgents, uploadDocuments, type Agent } from "@/lib/api";

type AgentType = "Blank" | "Personal" | "Business";
type FileStatus = "Processing" | "Processed";

type UploadedFile = {
  id: number;
  file: File;
  status: FileStatus;
};

const PERSONAL_ROLES = [
  "Personal Assistant",
  "Learning Companion",
  "Creative Helper",
  "Health Wellness Companion",
];

const BUSINESS_INDUSTRIES = [
  "Retail Commerce Assistant",
  "Healthcare Assistant",
  "Finance Banking Assistant",
  "Real Estate Sales Assistant",
  "Education Enrollment Assistant",
  "Hospitality Concierge",
  "Automotive Service Assistant",
  "Professional Services Consultant",
  "Tech Support Assistant",
  "Public Services Assistant (Government)",
  "Food Service Assistant",
  "Manufacturing Support Assistant",
  "Fitness Wellness Assistant",
  "Legal Services Coordinator",
  "Non-Profit Outreach Assistant",
  "Entertainment Services Assistant",
];

function splitList(text: string): string[] {
  return text
    .split(/\r?\n|,/g)
    .map((item) => item.trim())
    .filter(Boolean);
}

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");

  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [agentType, setAgentType] = useState<AgentType>("Blank");

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [personalRole, setPersonalRole] = useState(PERSONAL_ROLES[0]);
  const [businessIndustry, setBusinessIndustry] = useState(BUSINESS_INDUSTRIES[0]);
  const [urlsText, setUrlsText] = useState("");
  const [conversationStartersText, setConversationStartersText] = useState("");
  const [imageUrlsText, setImageUrlsText] = useState("");
  const [videoUrlsText, setVideoUrlsText] = useState("");
  const [scrapedUrl, setScrapedUrl] = useState("");
  const [scrapedText, setScrapedText] = useState("");
  const [manualDocumentName, setManualDocumentName] = useState("knowledge.txt");
  const [manualDocumentText, setManualDocumentText] = useState("");

  const [uploadedFiles, setUploadedFiles] = useState<UploadedFile[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const uploadWrapperRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void loadAgents();
  }, []);

  async function loadAgents() {
    try {
      const data = await getAgents();
      setAgents(data);
    } catch (error) {
      console.error("Failed to load agents:", error);
    } finally {
      setLoading(false);
    }
  }

  function resetCreateForm() {
    setAgentType("Blank");
    setName("");
    setDescription("");
    setSystemPrompt("");
    setPersonalRole(PERSONAL_ROLES[0]);
    setBusinessIndustry(BUSINESS_INDUSTRIES[0]);
    setUrlsText("");
    setConversationStartersText("");
    setImageUrlsText("");
    setVideoUrlsText("");
    setScrapedUrl("");
    setScrapedText("");
    setManualDocumentName("knowledge.txt");
    setManualDocumentText("");
    setUploadedFiles([]);
  }

  function markProcessed(fileId: number) {
    setUploadedFiles((prev) =>
      prev.map((item) => (item.id === fileId ? { ...item, status: "Processed" } : item))
    );
  }

  function handleFiles(files: File[]) {
    if (!files.length) return;
    const items: UploadedFile[] = files.map((file) => ({
      id: Date.now() + Math.floor(Math.random() * 100000),
      file,
      status: "Processing",
    }));

    setUploadedFiles((prev) => [...prev, ...items]);
    for (const item of items) {
      setTimeout(() => markProcessed(item.id), 1200);
    }
  }

  function removeFile(fileId: number) {
    setUploadedFiles((prev) => prev.filter((item) => item.id !== fileId));
  }

  function clearFiles() {
    setUploadedFiles([]);
  }

  function handleFileInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    if (!e.target.files) return;
    handleFiles(Array.from(e.target.files));
    e.target.value = "";
  }

  function handleDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    uploadWrapperRef.current?.classList.remove("border-blue-500");
    handleFiles(Array.from(e.dataTransfer.files));
  }

  function handleDragOver(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    uploadWrapperRef.current?.classList.add("border-blue-500");
  }

  function handleDragLeave() {
    uploadWrapperRef.current?.classList.remove("border-blue-500");
  }

  async function handleCreate() {
    if (!name.trim()) return;
    setCreating(true);

    try {
      const roleType = agentType === "Business" ? "business" : agentType === "Personal" ? "personal" : "knowledge";

      const payload: {
        name: string;
        description?: string;
        system_prompt?: string;
        role_type?: "personal" | "business" | "knowledge";
        industry?: string;
        urls?: string[];
        conversation_starters?: string[];
        image_urls?: string[];
        video_urls?: string[];
        documents_text?: Array<{ filename: string; text: string }>;
        scraped_data?: Array<{ url?: string; text: string }>;
      } = {
        name: name.trim(),
        description: description.trim(),
        system_prompt: systemPrompt.trim() || undefined,
        role_type: roleType,
        urls: splitList(urlsText),
        conversation_starters: splitList(conversationStartersText),
        image_urls: splitList(imageUrlsText),
        video_urls: splitList(videoUrlsText),
      };
        // Add personal_role if agentType is Personal and personalRole is set
        if (agentType === "Personal" && personalRole) {
          payload.personal_role = personalRole;
        }
      if (agentType === "Business") {
        payload.industry = businessIndustry;
      }

      if (manualDocumentText.trim()) {
        payload.documents_text = [
          {
            filename: manualDocumentName.trim() || "knowledge.txt",
            text: manualDocumentText.trim(),
          },
        ];
      }

      if (scrapedText.trim()) {
        payload.scraped_data = [
          {
            url: scrapedUrl.trim() || undefined,
            text: scrapedText.trim(),
          },
        ];
      }

      const agent = await createAgent(payload);
        let uploadError = null;
        if (uploadedFiles.length > 0) {
          try {
            await uploadDocuments(
              agent.id,
              uploadedFiles.map((item) => item.file)
            );
          } catch (err) {
            uploadError = err;
          }
        }

        resetCreateForm();
        setIsCreateOpen(false);
        await loadAgents();

        if (uploadError) {
          alert("Agent created but document upload failed. You can retry upload from agent details.");
          // Optionally: store agent.id for retry
          console.error("Document upload failed for agent", agent.id, uploadError);
        }
    } catch (error) {
      console.error("Failed to create agent:", error);
      alert("Failed to create agent. Check API key and backend logs.");
    } finally {
      setCreating(false);
    }
  }

  async function handleDelete(id: string) {
    if (!confirm("Are you sure you want to delete this agent?")) return;
    try {
      await deleteAgent(id);
      await loadAgents();
    } catch (error) {
      console.error("Failed to delete agent:", error);
    }
  }

  const filteredAgents = agents.filter(
    (agent) =>
      agent.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      agent.description?.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white mb-2">Agents</h1>
          <p className="text-neutral-400">Create and manage your AI agents</p>
        </div>

        <Dialog
          open={isCreateOpen}
          onOpenChange={(open) => {
            setIsCreateOpen(open);
            if (!open) resetCreateForm();
          }}
        >
          <DialogTrigger asChild>
            <Button className="bg-blue-600 hover:bg-blue-500">
              <Plus className="w-4 h-4 mr-2" />
              Create Agent
            </Button>
          </DialogTrigger>
          <DialogContent className="bg-neutral-900 border-neutral-800 max-h-[88vh] overflow-y-auto">
            <DialogHeader>
              <DialogTitle className="text-white">Create New Agent</DialogTitle>
            </DialogHeader>

            <div className="space-y-5 mt-2">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                {[
                  { type: "Blank" as AgentType, label: "Blank", icon: <Sparkles className="w-4 h-4" /> },
                  { type: "Personal" as AgentType, label: "Personal", icon: <User className="w-4 h-4" /> },
                  { type: "Business" as AgentType, label: "Business", icon: <Briefcase className="w-4 h-4" /> },
                ].map((card) => {
                  const selected = agentType === card.type;
                  return (
                    <button
                      key={card.type}
                      type="button"
                      onClick={() => setAgentType(card.type)}
                      className={`relative rounded-lg border p-3 text-left transition ${
                        selected
                          ? "border-blue-500 bg-blue-500/10"
                          : "border-neutral-700 bg-neutral-800/60 hover:border-neutral-500"
                      }`}
                    >
                      <div className="flex items-center gap-2 text-white text-sm font-medium">
                        {card.icon}
                        {card.label}
                      </div>
                      <div className="text-xs text-neutral-400 mt-1">
                        {card.type === "Blank" && "Knowledge-first setup"}
                        {card.type === "Personal" && "Assistant persona setup"}
                        {card.type === "Business" && "Industry-specific setup"}
                      </div>
                      {selected && (
                        <span className="absolute top-2 right-2 text-[10px] px-2 py-0.5 rounded bg-blue-600 text-white">
                          Selected
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>

              <div className="space-y-4 rounded-lg border border-neutral-800 bg-neutral-900/60 p-4">
                <div>
                  <label className="text-sm text-neutral-400 mb-1.5 block">Agent Name</label>
                  <Input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="e.g., Omni Retail Assistant"
                    className="bg-neutral-800 border-neutral-700 text-white"
                  />
                </div>

                <div>
                  <label className="text-sm text-neutral-400 mb-1.5 block">Description</label>
                  <Input
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="What does this agent do?"
                    className="bg-neutral-800 border-neutral-700 text-white"
                  />
                </div>

                {agentType === "Personal" && (
                  <div>
                    <label className="text-sm text-neutral-400 mb-1.5 block">Personal Role</label>
                    <select
                      value={personalRole}
                      onChange={(e) => setPersonalRole(e.target.value)}
                      className="w-full rounded-md border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-white"
                    >
                      {PERSONAL_ROLES.map((role) => (
                        <option key={role} value={role}>
                          {role}
                        </option>
                      ))}
                    </select>
                  </div>
                )}

                {agentType === "Business" && (
                  <div>
                    <label className="text-sm text-neutral-400 mb-1.5 block">Industry</label>
                    <select
                      value={businessIndustry}
                      onChange={(e) => setBusinessIndustry(e.target.value)}
                      className="w-full rounded-md border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-white"
                    >
                      {BUSINESS_INDUSTRIES.map((industry) => (
                        <option key={industry} value={industry}>
                          {industry}
                        </option>
                      ))}
                    </select>
                  </div>
                )}

                <div>
                  <label className="text-sm text-neutral-400 mb-1.5 block">System Prompt</label>
                  <textarea
                    value={systemPrompt}
                    onChange={(e) => setSystemPrompt(e.target.value)}
                    placeholder="Instructions, logic, behavior..."
                    className="w-full min-h-[84px] rounded-md border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-white"
                  />
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div>
                    <label className="text-sm text-neutral-400 mb-1.5 block">Web URLs (comma/newline)</label>
                    <textarea
                      value={urlsText}
                      onChange={(e) => setUrlsText(e.target.value)}
                      placeholder="https://example.com"
                      className="w-full min-h-[74px] rounded-md border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-white"
                    />
                  </div>
                  <div>
                    <label className="text-sm text-neutral-400 mb-1.5 block">Conversation Starters</label>
                    <textarea
                      value={conversationStartersText}
                      onChange={(e) => setConversationStartersText(e.target.value)}
                      placeholder="Hello, how can I help?"
                      className="w-full min-h-[74px] rounded-md border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-white"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div>
                    <label className="text-sm text-neutral-400 mb-1.5 block">Image URLs</label>
                    <textarea
                      value={imageUrlsText}
                      onChange={(e) => setImageUrlsText(e.target.value)}
                      placeholder="https://cdn.site/image.jpg"
                      className="w-full min-h-[74px] rounded-md border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-white"
                    />
                  </div>
                  <div>
                    <label className="text-sm text-neutral-400 mb-1.5 block">Video URLs</label>
                    <textarea
                      value={videoUrlsText}
                      onChange={(e) => setVideoUrlsText(e.target.value)}
                      placeholder="https://cdn.site/video.mp4"
                      className="w-full min-h-[74px] rounded-md border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-white"
                    />
                  </div>
                </div>

                <div className="space-y-2">
                  <label className="text-sm text-neutral-400 block">Pre-scraped Data</label>
                  <Input
                    value={scrapedUrl}
                    onChange={(e) => setScrapedUrl(e.target.value)}
                    placeholder="Source URL (optional)"
                    className="bg-neutral-800 border-neutral-700 text-white"
                  />
                  <textarea
                    value={scrapedText}
                    onChange={(e) => setScrapedText(e.target.value)}
                    placeholder="Paste scraped page text here..."
                    className="w-full min-h-[84px] rounded-md border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-white"
                  />
                </div>

                <div className="space-y-2">
                  <label className="text-sm text-neutral-400 block">Manual Document Text</label>
                  <Input
                    value={manualDocumentName}
                    onChange={(e) => setManualDocumentName(e.target.value)}
                    placeholder="knowledge.txt"
                    className="bg-neutral-800 border-neutral-700 text-white"
                  />
                  <textarea
                    value={manualDocumentText}
                    onChange={(e) => setManualDocumentText(e.target.value)}
                    placeholder="Paste full extracted document text..."
                    className="w-full min-h-[90px] rounded-md border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-white"
                  />
                </div>

                <div className="space-y-2">
                  <label className="text-sm text-neutral-400 block">Knowledge Files (optional)</label>
                  <div
                    ref={uploadWrapperRef}
                    onClick={() => fileInputRef.current?.click()}
                    onDrop={handleDrop}
                    onDragOver={handleDragOver}
                    onDragLeave={handleDragLeave}
                    className="border-2 border-dashed border-neutral-700 bg-neutral-800/50 rounded-lg p-4 cursor-pointer hover:border-blue-500/50 transition-colors text-center"
                  >
                    <input
                      ref={fileInputRef}
                      type="file"
                      multiple
                      accept=".pdf,.txt,.docx,.csv"
                      className="hidden"
                      onChange={handleFileInputChange}
                    />
                    <Upload className="w-6 h-6 text-neutral-500 mx-auto mb-2" />
                    <p className="text-sm text-neutral-300">Drop files here or click to upload</p>
                    <p className="text-xs text-neutral-500 mt-1">PDF, TXT, DOCX, CSV</p>
                  </div>

                  {uploadedFiles.length > 0 && (
                    <div className="space-y-2">
                      {uploadedFiles.map((item) => (
                        <div
                          key={item.id}
                          className="flex items-center justify-between rounded border border-neutral-700 bg-neutral-800 p-2"
                        >
                          <div className="min-w-0">
                            <div className="truncate text-sm text-neutral-200">{item.file.name}</div>
                            <div className="text-xs text-neutral-500">
                              {(item.file.size / 1024).toFixed(1)} KB
                            </div>
                          </div>
                          <div className="flex items-center gap-3">
                            <span
                              className={`text-xs ${
                                item.status === "Processed" ? "text-emerald-400" : "text-blue-400"
                              }`}
                            >
                              {item.status}
                            </span>
                            <button
                              type="button"
                              onClick={() => removeFile(item.id)}
                              className="text-neutral-500 hover:text-red-400"
                            >
                              <X size={14} />
                            </button>
                          </div>
                        </div>
                      ))}
                      <Button
                        type="button"
                        variant="outline"
                        onClick={clearFiles}
                        className="border-neutral-700 text-neutral-300 hover:bg-neutral-800"
                      >
                        Clear Files
                      </Button>
                    </div>
                  )}
                </div>
              </div>

              <div className="flex justify-end gap-3">
                <Button
                  variant="outline"
                  onClick={() => setIsCreateOpen(false)}
                  className="border-neutral-700 text-neutral-300 hover:bg-neutral-800"
                >
                  Cancel
                </Button>
                <Button
                  onClick={handleCreate}
                  disabled={!name.trim() || creating}
                  className="bg-blue-600 hover:bg-blue-500"
                >
                  {creating ? "Creating..." : "Create Agent"}
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      <div className="relative max-w-md">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-neutral-500" />
        <Input
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search agents..."
          className="pl-10 bg-neutral-900 border-neutral-800 text-white"
        />
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <motion.div
            animate={{ rotate: 360 }}
            transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
            className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full"
          />
        </div>
      ) : (
        <AgentGrid agents={filteredAgents} onDelete={handleDelete} />
      )}
    </div>
  );
}
