"use client";

import dynamic from "next/dynamic";

// Dynamic import with SSR disabled — all voice components use browser-only APIs
// (AudioContext, WebSocket, MediaRecorder, AudioWorklet)
const VoiceQueue = dynamic(
  () => import("@/components/voice/VoiceQueue").then((m) => m.VoiceQueue),
  {
    ssr: false,
    loading: () => (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center space-y-4">
          <div className="w-12 h-12 border-4 border-blue-500/30 border-t-blue-500 rounded-full animate-spin mx-auto" />
          <p className="text-neutral-400 text-sm">Loading Voice AI...</p>
        </div>
      </div>
    ),
  }
);

export default function VoicePage() {
  return (
    <div>
      <div className="mb-6">
        <h1 className="text-3xl font-bold text-white">
          Voice AI
        </h1>
        <p className="text-neutral-400 mt-1">
          Full-duplex voice conversation powered by PersonaPlex / Moshi
        </p>
      </div>
      <VoiceQueue />
    </div>
  );
}
