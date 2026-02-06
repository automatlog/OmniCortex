"use client";

import { motion } from "framer-motion";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { MessageSquare, FileText, Trash2, ExternalLink } from "lucide-react";
import type { Agent } from "@/lib/api";

interface AgentCardProps {
  agent: Agent;
  onDelete?: (id: string) => void;
}

export function AgentCard({ agent, onDelete }: AgentCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      whileHover={{ y: -4 }}
      className={cn(
        "relative group",
        "bg-neutral-900 border border-neutral-800 rounded-xl p-5",
        "hover:border-blue-500/50 transition-all duration-300"
      )}
    >
      {/* Gradient glow on hover */}
      <div className="absolute inset-0 rounded-xl bg-gradient-to-br from-blue-500/10 to-purple-500/10 opacity-0 group-hover:opacity-100 transition-opacity" />

      <div className="relative">
        {/* Header */}
        <div className="flex items-start justify-between mb-3">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center">
              <span className="text-lg">🤖</span>
            </div>
            <div>
              <h3 className="font-semibold text-white">{agent.name}</h3>
              <p className="text-xs text-neutral-500">
                Created {new Date(agent.created_at).toLocaleDateString()}
              </p>
            </div>
          </div>

          {/* Actions */}
          <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
            <button
              onClick={() => onDelete?.(agent.id)}
              className="p-1.5 rounded-lg hover:bg-red-500/20 text-neutral-400 hover:text-red-400 transition-colors"
            >
              <Trash2 size={16} />
            </button>
          </div>
        </div>

        {/* Description */}
        <p className="text-sm text-neutral-400 mb-4 line-clamp-2">
          {agent.description || "No description provided"}
        </p>

        {/* Stats */}
        <div className="flex items-center gap-4 mb-4">
          <div className="flex items-center gap-1.5 text-neutral-500">
            <FileText size={14} />
            <span className="text-xs">{agent.document_count || 0} docs</span>
          </div>
          {agent.webhook_url && (
            <div className="flex items-center gap-1.5 text-neutral-500">
              <ExternalLink size={14} />
              <span className="text-xs">Webhook</span>
            </div>
          )}
        </div>

        {/* Actions Footer */}
        <div className="flex gap-2">
          <Link
            href={`/agents/${agent.id}/chat`}
            className={cn(
              "flex-1 flex items-center justify-center gap-2",
              "bg-blue-600/10 hover:bg-blue-600/20 text-blue-400",
              "py-2.5 rounded-lg font-medium text-sm",
              "transition-colors"
            )}
          >
            <MessageSquare size={16} />
            Chat
          </Link>
          
          <Link
            href={`/agents/${agent.id}/documents`}
            className={cn(
              "flex-1 flex items-center justify-center gap-2",
              "bg-purple-600/10 hover:bg-purple-600/20 text-purple-400",
              "py-2.5 rounded-lg font-medium text-sm",
              "transition-colors"
            )}
          >
            <FileText size={16} />
            Docs
          </Link>
        </div>
      </div>
    </motion.div>
  );
}

// Grid component for multiple agents
interface AgentGridProps {
  agents: Agent[];
  onDelete?: (id: string) => void;
}

export function AgentGrid({ agents, onDelete }: AgentGridProps) {
  if (agents.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-neutral-500">
        <div className="w-20 h-20 rounded-full bg-neutral-800 flex items-center justify-center mb-4">
          <span className="text-4xl">🤖</span>
        </div>
        <p className="text-lg font-medium mb-2">No agents yet</p>
        <p className="text-sm">Create your first agent to get started</p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {agents.map((agent, index) => (
        <motion.div
          key={agent.id}
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: index * 0.1 }}
        >
          <AgentCard agent={agent} onDelete={onDelete} />
        </motion.div>
      ))}
    </div>
  );
}
