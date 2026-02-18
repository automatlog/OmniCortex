"use client";

import {
  FC,
  MutableRefObject,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { useModelParams } from "./hooks/useModelParams";
import { useSystemTheme } from "./hooks/useSystemTheme";
import { prewarmDecoderWorker } from "@/lib/voice/decoder/decoderWorker";
import { VoiceConversation } from "./VoiceConversation";

// VoiceQueue is the entry point for the Voice AI feature.
// It handles microphone access, AudioContext initialization,
// and either shows the setup UI or the active conversation.
export const VoiceQueue: FC = () => {
  const audioContext = useRef<AudioContext | null>(null);
  const worklet = useRef<AudioWorkletNode | null>(null);
  const [hasMicrophoneAccess, setHasMicrophoneAccess] = useState(false);
  const [showMicrophoneAccessMessage, setShowMicrophoneAccessMessage] =
    useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const theme = useSystemTheme();
  const modelParams = useModelParams();

  // The Moshi WebSocket URL — proxied through api.py
  const moshiWsUrl =
    typeof window !== "undefined"
      ? (() => {
          const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
          const wsUrl = apiUrl.replace(/^http/, "ws");
          return `${wsUrl}/voice/ws`;
        })()
      : "";

  const getMicrophoneAccess = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
        },
      });
      // Stop preview tracks — we just needed permission
      stream.getTracks().forEach((track) => track.stop());
      setHasMicrophoneAccess(true);
      setShowMicrophoneAccessMessage(false);
      return true;
    } catch (err) {
      console.error("Microphone access denied:", err);
      setShowMicrophoneAccessMessage(true);
      return false;
    }
  }, []);

  const startProcessor = useCallback(async () => {
    try {
      setIsLoading(true);
      const ctx = new AudioContext({ sampleRate: 24000 });
      await ctx.audioWorklet.addModule("/moshi-processor.js");
      const node = new AudioWorkletNode(ctx, "moshi-processor");
      node.connect(ctx.destination);
      audioContext.current = ctx;
      worklet.current = node;
      // Prewarm the Opus decoder in parallel
      prewarmDecoderWorker(ctx.sampleRate);
      setIsLoading(false);
    } catch (err) {
      console.error("Failed to start audio processor:", err);
      setError("Failed to initialize audio processor");
      setIsLoading(false);
    }
  }, []);

  const startConnection = useCallback(async () => {
    await startProcessor();
    const hasAccess = await getMicrophoneAccess();
    if (!hasAccess) {
      setError("Microphone access is required for Voice AI");
    }
  }, [startProcessor, getMicrophoneAccess]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      worklet.current?.disconnect();
      audioContext.current?.close();
    };
  }, []);

  // If we have mic access and worklet is ready, show the conversation
  if (hasMicrophoneAccess && audioContext.current && worklet.current) {
    return (
      <VoiceConversation
        workerAddr={moshiWsUrl}
        audioContext={audioContext as MutableRefObject<AudioContext>}
        worklet={worklet as MutableRefObject<AudioWorkletNode>}
        theme={theme}
        startConnection={startConnection}
        {...modelParams}
      />
    );
  }

  // Otherwise show the setup / connect UI
  return (
    <div className="flex flex-col items-center justify-center min-h-[50vh] gap-6">
      <div className="text-center space-y-4 max-w-lg">
        {/* Pulsing microphone icon */}
        <div className="relative mx-auto w-24 h-24">
          <div className="absolute inset-0 rounded-full bg-green-500/20 animate-ping" />
          <div className="relative flex items-center justify-center w-24 h-24 rounded-full bg-gradient-to-br from-green-500 to-emerald-600 shadow-lg shadow-green-500/25">
            <svg
              className="w-10 h-10 text-white"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4M12 15a3 3 0 003-3V5a3 3 0 00-6 0v7a3 3 0 003 3z"
              />
            </svg>
          </div>
        </div>

        <h2 className="text-2xl font-semibold text-white">
          Start Voice Conversation
        </h2>
        <p className="text-neutral-400 text-sm leading-relaxed">
          Talk naturally with the AI using full-duplex voice. The system processes
          your speech in real-time and responds with synthesized voice.
        </p>

        {error && (
          <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
            {error}
          </div>
        )}

        {showMicrophoneAccessMessage && (
          <div className="p-3 rounded-lg bg-yellow-500/10 border border-yellow-500/20 text-yellow-400 text-sm">
            Please allow microphone access in your browser to continue
          </div>
        )}

        <button
          onClick={startConnection}
          disabled={isLoading}
          className="px-8 py-3 rounded-xl bg-gradient-to-r from-green-500 to-emerald-600 text-white font-medium text-lg shadow-lg shadow-green-500/25 hover:shadow-green-500/40 transition-all duration-200 hover:scale-105 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100"
        >
          {isLoading ? (
            <span className="flex items-center gap-2">
              <span className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              Initializing...
            </span>
          ) : (
            "Connect"
          )}
        </button>

        {/* System prompt textarea */}
        <div className="text-left space-y-2 pt-4">
          <label className="text-sm text-neutral-400 block">
            System Prompt (optional)
          </label>
          <textarea
            className="w-full p-3 rounded-lg bg-neutral-800/50 border border-neutral-700/50 text-white text-sm resize-none focus:outline-none focus:ring-2 focus:ring-green-500/30"
            rows={3}
            value={modelParams.textPrompt}
            onChange={(e) => modelParams.setTextPrompt(e.target.value)}
            placeholder="You are a helpful assistant..."
          />
        </div>
      </div>
    </div>
  );
};
