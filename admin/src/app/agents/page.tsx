"use client";

import { useEffect, useState, useRef } from "react";
import { motion } from "framer-motion";
import { Plus, Search, Upload, X } from "lucide-react";
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
import { getAgents, createAgent, deleteAgent, uploadDocuments, type Agent } from "@/lib/api";

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  
  // Create Modal State
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [newAgentName, setNewAgentName] = useState("");
  const [newAgentDescription, setNewAgentDescription] = useState("");
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [creating, setCreating] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    loadAgents();
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

  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    if (e.target.files) {
      setSelectedFiles(Array.from(e.target.files));
    }
  }

  function removeFile(index: number) {
    setSelectedFiles(prev => prev.filter((_, i) => i !== index));
  }

  async function handleCreate() {
    if (!newAgentName.trim()) return;

    setCreating(true);
    try {
      // 1. Create Agent
      const agent = await createAgent({
        name: newAgentName.trim(),
        description: newAgentDescription.trim(),
      });

      // 2. Upload Files if selected
      if (selectedFiles.length > 0) {
        await uploadDocuments(agent.id, selectedFiles);
      }

      // Reset
      setNewAgentName("");
      setNewAgentDescription("");
      setSelectedFiles([]);
      setIsCreateOpen(false);
      
      // Refresh
      loadAgents();
    } catch (error) {
      console.error("Failed to create agent:", error);
      alert("Failed to create agent. Check console for details.");
    } finally {
      setCreating(false);
    }
  }

  async function handleDelete(id: string) {
    if (!confirm("Are you sure you want to delete this agent?")) return;

    try {
      await deleteAgent(id);
      loadAgents();
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
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white mb-2">Agents</h1>
          <p className="text-neutral-400">
            Create and manage your AI agents
          </p>
        </div>

        <Dialog open={isCreateOpen} onOpenChange={setIsCreateOpen}>
          <DialogTrigger asChild>
            <Button className="bg-blue-600 hover:bg-blue-500">
              <Plus className="w-4 h-4 mr-2" />
              Create Agent
            </Button>
          </DialogTrigger>
          <DialogContent className="bg-neutral-900 border-neutral-800">
            <DialogHeader>
              <DialogTitle className="text-white">Create New Agent</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 mt-4">
              {/* Name Input */}
              <div>
                <label className="text-sm text-neutral-400 mb-1.5 block">
                  Agent Name
                </label>
                <Input
                  value={newAgentName}
                  onChange={(e) => setNewAgentName(e.target.value)}
                  placeholder="e.g., Customer Support Bot"
                  className="bg-neutral-800 border-neutral-700 text-white"
                />
              </div>
              
              {/* Description Input */}
              <div>
                <label className="text-sm text-neutral-400 mb-1.5 block">
                  Description
                </label>
                <Input
                  value={newAgentDescription}
                  onChange={(e) => setNewAgentDescription(e.target.value)}
                  placeholder="What does this agent do?"
                  className="bg-neutral-800 border-neutral-700 text-white"
                />
              </div>

              {/* File Upload */}
              <div>
                <label className="text-sm text-neutral-400 mb-1.5 block">
                  Knowledge Base (Optional)
                </label>
                <div 
                  onClick={() => fileInputRef.current?.click()}
                  className="border-2 border-dashed border-neutral-700 bg-neutral-800/50 rounded-lg p-4 cursor-pointer hover:border-blue-500/50 transition-colors text-center"
                >
                  <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    accept=".pdf,.txt,.docx"
                    className="hidden"
                    onChange={handleFileSelect}
                  />
                  <Upload className="w-6 h-6 text-neutral-500 mx-auto mb-2" />
                  <p className="text-sm text-neutral-400">Click to upload documents</p>
                  <p className="text-xs text-neutral-600 mt-1">PDF, TXT, DOCX supported</p>
                </div>

                {/* Selected File List */}
                {selectedFiles.length > 0 && (
                  <div className="mt-3 space-y-2">
                    {selectedFiles.map((file, idx) => (
                      <div key={idx} className="flex items-center justify-between text-sm bg-neutral-800 text-neutral-300 p-2 rounded border border-neutral-700">
                        <span className="truncate max-w-[200px]">{file.name}</span>
                        <button onClick={() => removeFile(idx)} className="text-neutral-500 hover:text-red-400">
                          <X size={14} />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="flex justify-end gap-3 pt-4">
                <Button
                  variant="outline"
                  onClick={() => setIsCreateOpen(false)}
                  className="border-neutral-700 text-neutral-300 hover:bg-neutral-800"
                >
                  Cancel
                </Button>
                <Button
                  onClick={handleCreate}
                  disabled={!newAgentName.trim() || creating}
                  className="bg-blue-600 hover:bg-blue-500"
                >
                  {creating ? "Creating & Ingesting..." : "Create Agent"}
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      {/* Search */}
      <div className="relative max-w-md">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-neutral-500" />
        <Input
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search agents..."
          className="pl-10 bg-neutral-900 border-neutral-800 text-white"
        />
      </div>

      {/* Agent Grid */}
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
