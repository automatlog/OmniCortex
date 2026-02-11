"use client";

import {
  FC,
  MutableRefObject,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { SocketContext } from "./SocketContext";
import { MediaContext } from "./MediaContext";
import { useSocket } from "./hooks/useSocket";
import { useModelParams } from "./hooks/useModelParams";
import { type ThemeType } from "./hooks/useSystemTheme";
import { ServerAudio } from "./components/ServerAudio/ServerAudio";
import { UserAudio } from "./components/UserAudio/UserAudio";
import { TextDisplay } from "./components/TextDisplay/TextDisplay";
import { AudioStats } from "./hooks/useServerAudio";

// Build the WebSocket URL for the Moshi server
const buildURL = ({
  workerAddr,
  params,
}: {
  workerAddr: string;
  params: ReturnType<typeof useModelParams>;
}) => {
  const url = new URL(workerAddr);
  url.searchParams.set("text_temperature", params.textTemperature.toString());
  url.searchParams.set("text_topk", params.textTopk.toString());
  url.searchParams.set("audio_temperature", params.audioTemperature.toString());
  url.searchParams.set("audio_topk", params.audioTopk.toString());
  url.searchParams.set("pad_mult", params.padMult.toString());
  url.searchParams.set("repetition_penalty", params.repetitionPenalty.toString());
  url.searchParams.set(
    "repetition_penalty_context",
    params.repetitionPenaltyContext.toString()
  );
  if (params.textPrompt) {
    url.searchParams.set("text_prompt", params.textPrompt);
  }
  if (params.voicePrompt) {
    url.searchParams.set("voice_prompt", params.voicePrompt);
  }
  return url.toString();
};

type VoiceConversationProps = {
  workerAddr: string;
  audioContext: MutableRefObject<AudioContext>;
  worklet: MutableRefObject<AudioWorkletNode>;
  theme: ThemeType;
  startConnection: () => Promise<void>;
} & ReturnType<typeof useModelParams>;

export const VoiceConversation: FC<VoiceConversationProps> = ({
  workerAddr,
  audioContext,
  worklet,
  theme,
  startConnection,
  ...modelParams
}) => {
  const textContainerRef = useRef<HTMLDivElement>(null);
  const getAudioStats = useRef<() => AudioStats>(() => ({
    playedAudioDuration: 0,
    missedAudioDuration: 0,
    totalAudioMessages: 0,
    delay: 0,
    minPlaybackDelay: 0,
    maxPlaybackDelay: 0,
  }));

  const WSURL = buildURL({ workerAddr, params: modelParams });

  const micDuration = useRef(0);
  const actualAudioPlayed = useRef(0);

  const audioStreamDestination = useRef(
    audioContext.current.createMediaStreamDestination()
  );
  const stereoMerger = useRef(audioContext.current.createChannelMerger(2));
  stereoMerger.current.connect(audioStreamDestination.current);

  // Media recording
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);

  const startRecording = useCallback(() => {
    try {
      const recorder = new MediaRecorder(audioStreamDestination.current.stream, {
        mimeType: "audio/webm",
      });
      recorder.start();
      mediaRecorderRef.current = recorder;
    } catch (err) {
      console.warn("Recording not supported:", err);
    }
  }, []);

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current?.state === "recording") {
      mediaRecorderRef.current.stop();
    }
  }, []);

  const onDisconnect = useCallback(() => {
    console.log("WebSocket disconnected");
  }, []);

  const { socketStatus, sendMessage, socket, start, stop } = useSocket({
    uri: WSURL,
    onDisconnect,
  });

  // Auto-start the WebSocket connection
  useEffect(() => {
    start();
    return () => {
      stop();
    };
  }, [start, stop]);

  const setGetAudioStats = useCallback(
    (fn: () => AudioStats) => {
      getAudioStats.current = fn;
    },
    []
  );

  return (
    <SocketContext.Provider value={{ socketStatus, socket, sendMessage }}>
      <MediaContext.Provider
        value={{
          startRecording,
          stopRecording,
          audioContext,
          audioStreamDestination,
          worklet,
          micDuration,
          actualAudioPlayed,
          stereoMerger,
        }}
      >
        <div className="flex flex-col gap-4">
          {/* Status bar */}
          <div className="flex items-center gap-3 p-3 rounded-xl bg-neutral-800/50 border border-neutral-700/40">
            <div
              className={`w-3 h-3 rounded-full ${
                socketStatus === "connected"
                  ? "bg-green-500 shadow-green-500/50 shadow-sm"
                  : socketStatus === "connecting"
                    ? "bg-yellow-500 animate-pulse"
                    : "bg-red-500"
              }`}
            />
            <span className="text-sm text-neutral-300">
              {socketStatus === "connected"
                ? "Connected — Speak naturally"
                : socketStatus === "connecting"
                  ? "Connecting to voice server..."
                  : "Disconnected"}
            </span>
            {socketStatus === "disconnected" && (
              <button
                onClick={startConnection}
                className="ml-auto px-3 py-1 rounded-lg bg-green-600 hover:bg-green-500 text-white text-sm transition-colors"
              >
                Reconnect
              </button>
            )}
            {socketStatus === "connected" && (
              <button
                onClick={stop}
                className="ml-auto px-3 py-1 rounded-lg bg-red-600 hover:bg-red-500 text-white text-sm transition-colors"
              >
                Disconnect
              </button>
            )}
          </div>

          {/* Main conversation area */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {/* Server Audio (center) */}
            <div className="lg:col-span-1 flex flex-col items-center justify-center p-6 rounded-xl bg-neutral-800/30 border border-neutral-700/30">
              <h3 className="text-sm font-medium text-neutral-400 mb-4">AI Voice</h3>
              <ServerAudio setGetAudioStats={setGetAudioStats} theme={theme} />
            </div>

            {/* Text display */}
            <div className="lg:col-span-1 flex flex-col rounded-xl bg-neutral-800/30 border border-neutral-700/30 overflow-hidden">
              <div className="p-3 border-b border-neutral-700/30">
                <h3 className="text-sm font-medium text-neutral-400">Transcript</h3>
              </div>
              <div
                ref={textContainerRef}
                className="flex-1 overflow-y-auto max-h-80 p-4 text-sm text-neutral-200 leading-relaxed"
              >
                <TextDisplay containerRef={textContainerRef as React.RefObject<HTMLDivElement>} />
              </div>
            </div>

            {/* User Audio */}
            <div className="lg:col-span-1 flex flex-col items-center justify-center p-6 rounded-xl bg-neutral-800/30 border border-neutral-700/30">
              <h3 className="text-sm font-medium text-neutral-400 mb-4">Your Voice</h3>
              <UserAudio theme={theme} />
            </div>
          </div>
        </div>
      </MediaContext.Provider>
    </SocketContext.Provider>
  );
};
