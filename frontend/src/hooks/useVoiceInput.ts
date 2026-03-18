"use client";

import { useCallback, useRef, useState } from "react";
import { sttApi } from "@/lib/api";

export type VoiceInputState = "idle" | "recording" | "transcribing" | "error";

/**
 * useVoiceInput — records a short audio clip and transcribes it via Groq Whisper.
 *
 * Usage:
 *   const { state, start, stop } = useVoiceInput({ onTranscript });
 *   <button onMouseDown={start} onMouseUp={stop} />
 */
export function useVoiceInput({ onTranscript }: { onTranscript: (text: string) => void }) {
  const [state, setState] = useState<VoiceInputState>("idle");
  const [errorMessage, setErrorMessage] = useState("");
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  const start = useCallback(async () => {
    if (state !== "idle") return;
    chunksRef.current = [];
    setErrorMessage("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = MediaRecorder.isTypeSupported("audio/webm")
        ? "audio/webm"
        : MediaRecorder.isTypeSupported("audio/mp4")
        ? "audio/mp4"
        : "";
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      recorderRef.current = recorder;

      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) chunksRef.current.push(e.data);
      };

      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        if (chunksRef.current.length === 0) {
          setState("idle");
          return;
        }
        setState("transcribing");
        const blob = new Blob(chunksRef.current, { type: mimeType || "audio/webm" });
        try {
          const { text } = await sttApi.transcribe(blob);
          if (text.trim()) onTranscript(text.trim());
          setState("idle");
        } catch (err: unknown) {
          setState("error");
          setErrorMessage(err instanceof Error ? err.message : "Voice transcription failed");
          setTimeout(() => setState("idle"), 2000);
        }
      };

      recorder.start();
      setState("recording");
    } catch {
      setState("error");
      setErrorMessage("Microphone permission denied or unavailable");
      setTimeout(() => setState("idle"), 2000);
    }
  }, [state, onTranscript]);

  const stop = useCallback(() => {
    if (recorderRef.current && recorderRef.current.state === "recording") {
      recorderRef.current.stop();
    }
  }, []);

  const clearError = useCallback(() => setErrorMessage(""), []);

  return { state, start, stop, errorMessage, clearError };
}
