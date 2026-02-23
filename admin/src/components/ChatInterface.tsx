"use client";

import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/lib/utils";
import { Send, Plus, Loader2, Settings } from "lucide-react";
import { sendMessage, sendVoice, type ApiError, type ChatMessage } from "@/lib/api";
import { VoiceRecorder } from "./VoiceRecorder";
import { MessageContent } from "./MessageContent";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

interface ChatInterfaceProps {
  agentId: string;
  agentName?: string;
}

export function ChatInterface({
  agentId,
  agentName = "Agent",
}: ChatInterfaceProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isProcessingVoice, setIsProcessingVoice] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryCount, setRetryCount] = useState(0);
  
  // Settings
  const [selectedModel, setSelectedModel] = useState("Meta Llama 3.1");
  const [verbosity, setVerbosity] = useState("medium");
  const [settingsOpen, setSettingsOpen] = useState(false);
  
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const models = ["Meta Llama 3.1", "Llama 4 Maverick"];
  const verbosityOptions = [
    { value: "short", label: "⚡ Short (5s)", desc: "Quick responses" },
    { value: "medium", label: "⚖️ Balanced", desc: "Standard detail" },
    { value: "detailed", label: "📚 Detailed", desc: "Comprehensive" }
  ];

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const sendUserMessage = async (text: string) => {
    const content = text.trim();
    if (!content || isLoading) return;

    const userMessage: ChatMessage = {
      role: "user",
      content,
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsLoading(true);
    setError(null);
    setRetryCount(0);

    try {
      const response = await sendMessage(
        userMessage.content,
        agentId,
        selectedModel,
        5,
        verbosity
      );

      const assistantMessage: ChatMessage = {
        role: "assistant",
        content: response.answer,
        timestamp: new Date().toISOString(),
      };

      setMessages((prev) => [...prev, assistantMessage]);
    } catch (error) {
      const apiError = error as Partial<ApiError>;
      const errorMsg =
        apiError?.message ||
        (error instanceof Error ? error.message : String(error));
      const errorDetails = apiError?.details;
      console.error("Failed to send message:", errorMsg, errorDetails || "");
      setError(errorDetails ? `${errorMsg} (${errorDetails})` : errorMsg);
      
      // Provide helpful error message based on error type
      let userFriendlyMsg = "Sorry, I encountered an error. ";
      
      if (errorMsg.includes("timeout")) {
        userFriendlyMsg += "The request took too long. The model might be loading or busy. Please try again.";
      } else if (errorMsg.includes("Connection") || errorMsg.includes("Failed to fetch")) {
        userFriendlyMsg += "Cannot connect to the server. Please check if the API is running.";
      } else if (errorMsg.includes("Server error") || apiError?.type === "server") {
        userFriendlyMsg += errorDetails || errorMsg;
      } else {
        userFriendlyMsg += "Please try again.";
      }
      
      const errorMessage: ChatMessage = {
        role: "assistant",
        content: userFriendlyMsg,
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSend = async () => {
    await sendUserMessage(input);
  };

  const handleSuggestionClick = async (suggestion: string) => {
    if (isLoading || isProcessingVoice) return;
    await sendUserMessage(suggestion);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleVoiceRecording = async (audioBlob: Blob) => {
    setIsProcessingVoice(true);
    setError(null);

    try {
      // Send voice to API
      const response = await sendVoice(agentId, audioBlob);
      
      // Add transcription as user message
      const userMessage: ChatMessage = {
        role: "user",
        content: response.transcription || "[Voice message]",
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, userMessage]);

      // Add response as assistant message
      const assistantMessage: ChatMessage = {
        role: "assistant",
        content: response.response || "I received your voice message.",
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, assistantMessage]);

    } catch (error) {
      console.error("Failed to process voice:", error);
      
      const errorMsg = error instanceof Error ? error.message : "Unknown error";
      setError(errorMsg);
      
      const errorMessage: ChatMessage = {
        role: "assistant",
        content: "Sorry, I couldn't process your voice message. Please try again or type your message.",
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setIsProcessingVoice(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-neutral-950 rounded-xl border border-neutral-800">
      {/* Settings Header */}
      <div className="p-4 border-b border-neutral-800 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div>
            <p className="text-sm text-neutral-400 mb-1">Model</p>
            <select
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
              className="bg-neutral-800 text-white text-sm rounded px-3 py-1.5 border border-neutral-700 focus:border-blue-500 focus:outline-none"
            >
              {models.map((model) => (
                <option key={model} value={model}>
                  {model}
                </option>
              ))}
            </select>
          </div>

          <div>
            <p className="text-sm text-neutral-400 mb-1">Response Length</p>
            <select
              value={verbosity}
              onChange={(e) => setVerbosity(e.target.value)}
              className="bg-neutral-800 text-white text-sm rounded px-3 py-1.5 border border-neutral-700 focus:border-blue-500 focus:outline-none"
            >
              {verbosityOptions.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}>
          <DialogTrigger asChild>
            <button className="p-2 rounded-lg hover:bg-neutral-800 text-neutral-400 hover:text-white transition-colors">
              <Settings className="w-5 h-5" />
            </button>
          </DialogTrigger>
          <DialogContent className="bg-neutral-900 border-neutral-800">
            <DialogHeader>
              <DialogTitle className="text-white">Chat Settings</DialogTitle>
            </DialogHeader>
            <div className="space-y-4">
              <div>
                <label className="text-sm text-neutral-400 block mb-2">
                  Response Style
                </label>
                <div className="space-y-2">
                  {verbosityOptions.map((opt) => (
                    <button
                      key={opt.value}
                      onClick={() => setVerbosity(opt.value)}
                      className={cn(
                        "w-full text-left p-3 rounded-lg border transition-colors",
                        verbosity === opt.value
                          ? "border-blue-500 bg-blue-500/10"
                          : "border-neutral-700 hover:border-neutral-600"
                      )}
                    >
                      <div className="text-white font-medium">{opt.label}</div>
                      <div className="text-xs text-neutral-400">{opt.desc}</div>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      {/* Error Banner */}
      {error && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="mx-4 mt-4 p-3 bg-red-500/10 border border-red-500/20 rounded-lg"
        >
          <div className="flex items-start gap-2">
            <span className="text-red-400 text-sm">⚠️</span>
            <div className="flex-1">
              <p className="text-red-400 text-sm font-medium">Connection Issue</p>
              <p className="text-red-300 text-xs mt-1">{error}</p>
            </div>
            <button
              onClick={() => setError(null)}
              className="text-red-400 hover:text-red-300 text-xs"
            >
              ✕
            </button>
          </div>
        </motion.div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-neutral-500">
            <div className="w-16 h-16 rounded-full bg-neutral-800 flex items-center justify-center mb-4">
              <span className="text-3xl">🤖</span>
            </div>
            <p className="text-lg font-medium">Start chatting with {agentName}</p>
            <p className="text-sm">Ask anything about the knowledge base</p>
          </div>
        )}

        {messages.map((message, index) => (
          <motion.div
            key={index}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className={cn(
              "flex gap-3",
              message.role === "user" ? "justify-end" : "justify-start"
            )}
          >
            {message.role === "assistant" && (
              <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center flex-shrink-0">
                <span className="text-sm">🤖</span>
              </div>
            )}
            <div
              className={cn(
                "max-w-[70%] rounded-2xl px-4 py-2.5",
                message.role === "user"
                  ? "bg-blue-600 text-white"
                  : "bg-neutral-800 text-neutral-100"
              )}
            >
              <MessageContent
                content={message.content}
                onSuggestionClick={message.role === "assistant" ? handleSuggestionClick : undefined}
              />
            </div>
            {message.role === "user" && (
              <div className="w-8 h-8 rounded-full bg-gradient-to-br from-orange-400 to-pink-500 flex items-center justify-center flex-shrink-0">
                <span className="text-sm">😎</span>
              </div>
            )}
          </motion.div>
        ))}

        {isLoading && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="flex gap-3"
          >
            <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center">
              <span className="text-sm">🤖</span>
            </div>
            <div className="bg-neutral-800 rounded-2xl px-4 py-3">
              <div className="flex gap-1">
                <motion.div
                  animate={{ opacity: [0.4, 1, 0.4] }}
                  transition={{ duration: 1, repeat: Infinity, delay: 0 }}
                  className="w-2 h-2 bg-neutral-400 rounded-full"
                />
                <motion.div
                  animate={{ opacity: [0.4, 1, 0.4] }}
                  transition={{ duration: 1, repeat: Infinity, delay: 0.2 }}
                  className="w-2 h-2 bg-neutral-400 rounded-full"
                />
                <motion.div
                  animate={{ opacity: [0.4, 1, 0.4] }}
                  transition={{ duration: 1, repeat: Infinity, delay: 0.4 }}
                  className="w-2 h-2 bg-neutral-400 rounded-full"
                />
              </div>
            </div>
          </motion.div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input Bar */}
      <div className="p-4 border-t border-neutral-800">
        <div className="flex items-center gap-2 bg-neutral-900 rounded-full px-4 py-2 border border-neutral-700 focus-within:border-blue-500 transition-colors">
          <button className="text-neutral-400 hover:text-white transition-colors">
            <Plus size={20} />
          </button>

          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={isProcessingVoice ? "Processing voice..." : "Ask anything..."}
            disabled={isLoading || isProcessingVoice}
            className="flex-1 bg-transparent text-white placeholder-neutral-500 focus:outline-none text-sm"
          />

          <VoiceRecorder
            onRecordingComplete={handleVoiceRecording}
            isProcessing={isProcessingVoice || isLoading}
          />

          <motion.button
            onClick={handleSend}
            disabled={!input.trim() || isLoading || isProcessingVoice}
            className={cn(
              "p-2 rounded-full transition-colors",
              input.trim() && !isLoading && !isProcessingVoice
                ? "bg-blue-600 text-white hover:bg-blue-500"
                : "bg-neutral-800 text-neutral-500"
            )}
          >
            {isLoading ? (
              <Loader2 size={18} className="animate-spin" />
            ) : (
              <Send size={18} />
            )}
          </motion.button>
        </div>
      </div>
    </div>
  );
}
