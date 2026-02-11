"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  MessageSquare,
  Bot,
  User,
  Clock,
  ChevronRight,
  Search,
  RefreshCw,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  getAgents,
  getConversationHistory,
  type Agent,
  type ChatMessage,
} from "@/lib/api";

export default function ConversationsPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  useEffect(() => {
    async function loadAgents() {
      try {
        const agentList = await getAgents();
        setAgents(agentList);
        if (agentList.length > 0) {
          selectAgent(agentList[0]);
        }
      } catch (error) {
        console.error("Failed to load agents:", error);
      } finally {
        setLoading(false);
      }
    }
    loadAgents();
  }, []);

  async function selectAgent(agent: Agent) {
    setSelectedAgent(agent);
    setMessagesLoading(true);
    try {
      const history = await getConversationHistory(agent.id, 100);
      setMessages(history);
    } catch (error) {
      console.error("Failed to load history:", error);
      setMessages([]);
    } finally {
      setMessagesLoading(false);
    }
  }

  async function refreshMessages() {
    if (!selectedAgent) return;
    setMessagesLoading(true);
    try {
      const history = await getConversationHistory(selectedAgent.id, 100);
      setMessages(history);
    } catch (error) {
      console.error("Failed to refresh:", error);
    } finally {
      setMessagesLoading(false);
    }
  }

  const filteredMessages = messages.filter((msg) =>
    msg.content.toLowerCase().includes(searchQuery.toLowerCase())
  );

  function formatTime(timestamp?: string) {
    if (!timestamp) return "";
    const date = new Date(timestamp);
    return date.toLocaleString("en-IN", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white mb-2">Conversations</h1>
          <p className="text-neutral-400">
            View chat history across all your agents.
          </p>
        </div>
        <Button
          onClick={refreshMessages}
          variant="outline"
          className="border-neutral-700 text-neutral-300 hover:bg-neutral-800"
          disabled={messagesLoading}
        >
          <RefreshCw
            className={`w-4 h-4 mr-2 ${messagesLoading ? "animate-spin" : ""}`}
          />
          Refresh
        </Button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6 h-[calc(100vh-200px)]">
        {/* Agent List (left panel) */}
        <Card className="bg-neutral-900 border-neutral-800 lg:col-span-1 overflow-hidden flex flex-col">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium text-neutral-400 flex items-center gap-2">
              <Bot className="w-4 h-4" />
              Agents ({agents.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="flex-1 overflow-y-auto space-y-1 p-3 pt-0">
            {loading ? (
              <div className="flex items-center justify-center py-8">
                <div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
              </div>
            ) : agents.length === 0 ? (
              <p className="text-neutral-500 text-sm text-center py-8">
                No agents yet
              </p>
            ) : (
              agents.map((agent) => (
                <button
                  key={agent.id}
                  onClick={() => selectAgent(agent)}
                  className={`w-full flex items-center gap-3 p-3 rounded-lg transition-all text-left ${
                    selectedAgent?.id === agent.id
                      ? "bg-blue-600/20 border border-blue-500/30 text-blue-400"
                      : "hover:bg-neutral-800/50 text-neutral-300"
                  }`}
                >
                  <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center flex-shrink-0">
                    <span className="text-sm">🤖</span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{agent.name}</p>
                    <p className="text-xs text-neutral-500">
                      {agent.document_count || 0} docs
                    </p>
                  </div>
                  <ChevronRight className="w-4 h-4 text-neutral-600 flex-shrink-0" />
                </button>
              ))
            )}
          </CardContent>
        </Card>

        {/* Messages (right panel) */}
        <Card className="bg-neutral-900 border-neutral-800 lg:col-span-3 overflow-hidden flex flex-col">
          <CardHeader className="pb-3 border-b border-neutral-800">
            <div className="flex items-center justify-between">
              <CardTitle className="text-lg text-white flex items-center gap-2">
                <MessageSquare className="w-5 h-5" />
                {selectedAgent
                  ? `${selectedAgent.name} — History`
                  : "Select an agent"}
              </CardTitle>
              <span className="text-xs text-neutral-500">
                {filteredMessages.length} messages
              </span>
            </div>
            {/* Search */}
            {selectedAgent && (
              <div className="relative mt-3">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-neutral-500" />
                <input
                  type="text"
                  placeholder="Search messages..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full pl-10 pr-4 py-2 bg-neutral-800 border border-neutral-700 rounded-lg text-sm text-white placeholder-neutral-500 focus:outline-none focus:border-blue-500 transition-colors"
                />
              </div>
            )}
          </CardHeader>

          <CardContent className="flex-1 overflow-y-auto p-4 space-y-3">
            {!selectedAgent ? (
              <div className="flex flex-col items-center justify-center h-full text-neutral-500">
                <MessageSquare className="w-12 h-12 mb-3 opacity-30" />
                <p>Select an agent to view conversation history</p>
              </div>
            ) : messagesLoading ? (
              <div className="flex items-center justify-center h-full">
                <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
              </div>
            ) : filteredMessages.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full text-neutral-500">
                <MessageSquare className="w-12 h-12 mb-3 opacity-30" />
                <p>
                  {searchQuery
                    ? "No messages match your search"
                    : "No conversations yet"}
                </p>
              </div>
            ) : (
              filteredMessages.map((msg, index) => (
                <motion.div
                  key={index}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: Math.min(index * 0.02, 0.5) }}
                  className={`flex gap-3 ${
                    msg.role === "user" ? "justify-end" : "justify-start"
                  }`}
                >
                  {msg.role === "assistant" && (
                    <div className="w-7 h-7 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center flex-shrink-0 mt-1">
                      <Bot className="w-4 h-4 text-white" />
                    </div>
                  )}
                  <div
                    className={`max-w-[75%] rounded-xl px-4 py-2.5 ${
                      msg.role === "user"
                        ? "bg-blue-600 text-white"
                        : "bg-neutral-800 text-neutral-200"
                    }`}
                  >
                    <p className="text-sm whitespace-pre-wrap">{msg.content}</p>
                    {msg.timestamp && (
                      <p
                        className={`text-[10px] mt-1 flex items-center gap-1 ${
                          msg.role === "user"
                            ? "text-blue-200/60"
                            : "text-neutral-500"
                        }`}
                      >
                        <Clock className="w-3 h-3" />
                        {formatTime(msg.timestamp)}
                      </p>
                    )}
                  </div>
                  {msg.role === "user" && (
                    <div className="w-7 h-7 rounded-full bg-neutral-700 flex items-center justify-center flex-shrink-0 mt-1">
                      <User className="w-4 h-4 text-neutral-300" />
                    </div>
                  )}
                </motion.div>
              ))
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
