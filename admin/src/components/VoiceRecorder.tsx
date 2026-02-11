"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { Mic, MicOff, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

interface VoiceRecorderProps {
  onRecordingComplete: (audioBlob: Blob) => void;
  onRecordingStart?: () => void;
  onRecordingStop?: () => void;
  isProcessing?: boolean;
  className?: string;
}

export function VoiceRecorder({
  onRecordingComplete,
  onRecordingStart,
  onRecordingStop,
  isProcessing = false,
  className,
}: VoiceRecorderProps) {
  const [isRecording, setIsRecording] = useState(false);
  const [audioLevel, setAudioLevel] = useState(0);
  const [error, setError] = useState<string | null>(null);
  
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  // Cleanup function
  const cleanup = useCallback(() => {
    if (animationFrameRef.current) {
      cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
    }
    
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop());
      streamRef.current = null;
    }
    
    if (audioContextRef.current?.state !== 'closed') {
      audioContextRef.current?.close();
      audioContextRef.current = null;
    }
    
    analyserRef.current = null;
    setAudioLevel(0);
  }, []);

  // Visualize audio levels
  const visualizeAudio = useCallback(() => {
    if (!analyserRef.current) return;

    const dataArray = new Uint8Array(analyserRef.current.frequencyBinCount);
    analyserRef.current.getByteFrequencyData(dataArray);
    
    // Calculate average volume
    const average = dataArray.reduce((a, b) => a + b) / dataArray.length;
    setAudioLevel(average / 255); // Normalize to 0-1

    animationFrameRef.current = requestAnimationFrame(visualizeAudio);
  }, []);

  // Start recording
  const startRecording = useCallback(async () => {
    try {
      setError(null);
      audioChunksRef.current = [];

      // Request microphone access
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
          sampleRate: 24000,
        },
      });

      streamRef.current = stream;

      // Setup audio context for visualization
      audioContextRef.current = new AudioContext();
      analyserRef.current = audioContextRef.current.createAnalyser();
      analyserRef.current.fftSize = 256;
      
      const source = audioContextRef.current.createMediaStreamSource(stream);
      source.connect(analyserRef.current);

      // Start visualization
      visualizeAudio();

      // Setup MediaRecorder
      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : 'audio/webm';
      
      mediaRecorderRef.current = new MediaRecorder(stream, {
        mimeType,
        audioBitsPerSecond: 128000,
      });

      mediaRecorderRef.current.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      mediaRecorderRef.current.onstop = () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: mimeType });
        onRecordingComplete(audioBlob);
        cleanup();
        onRecordingStop?.();
      };

      mediaRecorderRef.current.start(100); // Collect data every 100ms
      setIsRecording(true);
      onRecordingStart?.();

    } catch (err) {
      console.error('Error starting recording:', err);
      setError('Microphone access denied or not available');
      cleanup();
    }
  }, [onRecordingComplete, onRecordingStart, onRecordingStop, cleanup, visualizeAudio]);

  // Stop recording
  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
    }
  }, [isRecording]);

  // Toggle recording
  const toggleRecording = useCallback(() => {
    if (isRecording) {
      stopRecording();
    } else {
      startRecording();
    }
  }, [isRecording, startRecording, stopRecording]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      cleanup();
    };
  }, [cleanup]);

  return (
    <div className={cn("relative", className)}>
      <button
        onClick={toggleRecording}
        disabled={isProcessing}
        className={cn(
          "relative p-3 rounded-full transition-all duration-200",
          isRecording
            ? "bg-red-500/20 text-red-400 hover:bg-red-500/30"
            : "text-neutral-400 hover:text-white hover:bg-neutral-800",
          isProcessing && "opacity-50 cursor-not-allowed"
        )}
        title={isRecording ? "Stop recording" : "Start recording"}
      >
        {isProcessing ? (
          <Loader2 size={20} className="animate-spin" />
        ) : isRecording ? (
          <MicOff size={20} />
        ) : (
          <Mic size={20} />
        )}
        
        {/* Audio level indicator */}
        {isRecording && (
          <div className="absolute inset-0 rounded-full pointer-events-none">
            <div
              className="absolute inset-0 rounded-full bg-red-500/30 animate-pulse"
              style={{
                transform: `scale(${1 + audioLevel * 0.5})`,
                transition: 'transform 0.1s ease-out',
              }}
            />
          </div>
        )}
      </button>

      {/* Error message */}
      {error && (
        <div className="absolute top-full mt-2 left-1/2 -translate-x-1/2 whitespace-nowrap">
          <p className="text-xs text-red-400 bg-red-500/10 px-2 py-1 rounded">
            {error}
          </p>
        </div>
      )}

      {/* Recording indicator */}
      {isRecording && (
        <div className="absolute -top-1 -right-1">
          <div className="w-3 h-3 bg-red-500 rounded-full animate-pulse" />
        </div>
      )}
    </div>
  );
}
