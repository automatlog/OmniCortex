"use client";

import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/lib/utils";
import { Send, Mic, MicOff, Plus, Loader2 } from "lucide-react";
import { sendMessage, type ChatMessage } from "@/lib/api";

interface ChatInterfaceProps {
  agentId: string;
  agentName?: string;
  modelSelection?: string;
}

export function ChatInterface({
  agentId,
  agentName = "Agent",
  modelSelection = "Meta Llama 3.1",
}: ChatInterfaceProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [selectedModel, setSelectedModel] = useState(modelSelection);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const models = ["Meta Llama 3.1", "Nemotron"];

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSend = async () => {
    if (!input.trim() || isLoading) return;

    const userMessage: ChatMessage = {
      role: "user",
      content: input.trim(),
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsLoading(true);

    try {
      const response = await sendMessage(
        userMessage.content,
        agentId,
        selectedModel
      );

      const assistantMessage: ChatMessage = {
        role: "assistant",
        content: response.answer,
        timestamp: new Date().toISOString(),
      };

      setMessages((prev) => [...prev, assistantMessage]);
    } catch (error) {
      console.error("Failed to send message:", error);
      const errorMessage: ChatMessage = {
        role: "assistant",
        content: "Sorry, I encountered an error. Please try again.",
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const toggleRecording = () => {
    setIsRecording(!isRecording);
    // TODO: Implement voice recording
  };

  return (
    <div className="flex flex-col h-full bg-neutral-950 rounded-xl border border-neutral-800">
      {/* Model Selector */}
      <div className="p-4 border-b border-neutral-800">
        <p className="text-sm text-neutral-400 mb-2">Choose your AI Model:</p>
        <div className="flex gap-4">
          {models.map((model) => (
            <label
              key={model}
              className="flex items-center gap-2 cursor-pointer"
            >
              <input
                type="radio"
                name="model"
                value={model}
                checked={selectedModel === model}
                onChange={(e) => setSelectedModel(e.target.value)}
                className="w-4 h-4 text-blue-500 bg-neutral-800 border-neutral-600 focus:ring-blue-500"
              />
              <span
                className={cn(
                  "text-sm",
                  selectedModel === model ? "text-white" : "text-neutral-400"
                )}
              >
                {model}
              </span>
            </label>
          ))}
        </div>
      </div>

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
              <p className="text-sm whitespace-pre-wrap">{message.content}</p>
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
            placeholder={isRecording ? "Listening..." : "Ask anything..."}
            disabled={isLoading || isRecording}
            className="flex-1 bg-transparent text-white placeholder-neutral-500 focus:outline-none text-sm"
          />

          <button
            onClick={toggleRecording}
            className={cn(
              "p-2 rounded-full transition-colors",
              isRecording
                ? "bg-red-500/20 text-red-400"
                : "text-neutral-400 hover:text-white"
            )}
          >
            {isRecording ? <MicOff size={18} /> : <Mic size={18} />}
          </button>

          <AnimatePresence mode="wait">
            {isRecording ? (
              <motion.button
                key="end"
                initial={{ scale: 0.8, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.8, opacity: 0 }}
                onClick={toggleRecording}
                className="px-4 py-1.5 bg-blue-600 text-white text-sm font-medium rounded-full hover:bg-blue-500 transition-colors"
              >
                End
              </motion.button>
            ) : (
              <motion.button
                key="send"
                initial={{ scale: 0.8, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.8, opacity: 0 }}
                onClick={handleSend}
                disabled={!input.trim() || isLoading}
                className={cn(
                  "p-2 rounded-full transition-colors",
                  input.trim() && !isLoading
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
            )}
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}
