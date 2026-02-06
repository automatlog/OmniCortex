"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { ArrowLeft, Upload } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { ChatInterface } from "@/components/ChatInterface";
import { getAgent, type Agent } from "@/lib/api";

export default function AgentChatPage() {
  const params = useParams();
  const agentId = params.id as string;
  const [agent, setAgent] = useState<Agent | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadAgent() {
      try {
        const data = await getAgent(agentId);
        setAgent(data);
      } catch (error) {
        console.error("Failed to load agent:", error);
      } finally {
        setLoading(false);
      }
    }
    loadAgent();
  }, [agentId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-[80vh]">
        <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!agent) {
    return (
      <div className="flex flex-col items-center justify-center h-[80vh] text-neutral-500">
        <p className="text-lg mb-4">Agent not found</p>
        <Link href="/agents" className="text-blue-400 hover:underline">
          ← Back to Agents
        </Link>
      </div>
    );
  }

  return (
    <div className="h-[calc(100vh-48px)] flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-4">
          <Link
            href="/agents"
            className="p-2 rounded-lg hover:bg-neutral-800 text-neutral-400 hover:text-white transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div>
            <h1 className="text-xl font-bold text-white flex items-center gap-2">
              <span className="text-2xl">🤖</span>
              {agent.name}
            </h1>
            <p className="text-sm text-neutral-400">
              {agent.document_count || 0} documents • Test your agent
            </p>
          </div>
        </div>

        <Button
          variant="outline"
          className="border-neutral-700 text-neutral-300 hover:bg-neutral-800"
        >
          <Upload className="w-4 h-4 mr-2" />
          Upload Document
        </Button>
      </div>

      {/* Chat Interface */}
      <div className="flex-1">
        <ChatInterface agentId={agentId} agentName={agent.name} />
      </div>
    </div>
  );
}
