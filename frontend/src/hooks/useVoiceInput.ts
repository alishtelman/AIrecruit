"use client";

import { useCallback, useRef, useState } from "react";
import { sttApi } from "@/lib/api";

export type VoiceInputState =
  | "idle"
  | "listening"
  | "transcribing"
  | "review"
  | "submitted"
  | "microphone_error"
  | "silence_timeout"
  | "error";

export type VoiceTranscriptMeta = {
  audio_size_bytes: number;
  duration_ms: number;
  transcript_quality: "good" | "low" | "empty";
};

/**
 * useVoiceInput — records an answer, transcribes it via STT, then pauses in
 * review state so the candidate can confirm or re-record before submission.
 */
export function useVoiceInput({
  onTranscript,
}: {
  onTranscript: (text: string, meta: VoiceTranscriptMeta) => void;
}) {
  const [state, setState] = useState<VoiceInputState>("idle");
  const [errorMessage, setErrorMessage] = useState("");
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const startedAtRef = useRef(0);
  const silenceTimerRef = useRef<number | null>(null);
  const mimeTypeRef = useRef("audio/webm");

  const clearSilenceTimer = useCallback(() => {
    if (silenceTimerRef.current != null) {
      window.clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
  }, []);

  const stopStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  const resetRecorder = useCallback(() => {
    clearSilenceTimer();
    stopStream();
    recorderRef.current = null;
    chunksRef.current = [];
    startedAtRef.current = 0;
  }, [clearSilenceTimer, stopStream]);

  const canStart = useCallback((nextState: VoiceInputState) => {
    return ["idle", "review", "submitted", "microphone_error", "silence_timeout", "error"].includes(nextState);
  }, []);

  const start = useCallback(async () => {
    if (!canStart(state)) return;
    resetRecorder();
    chunksRef.current = [];
    setErrorMessage("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mimeType = MediaRecorder.isTypeSupported("audio/webm")
        ? "audio/webm"
        : MediaRecorder.isTypeSupported("audio/mp4")
        ? "audio/mp4"
        : "";
      mimeTypeRef.current = mimeType || "audio/webm";
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      recorderRef.current = recorder;
      startedAtRef.current = Date.now();

      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) chunksRef.current.push(e.data);
      };

      recorder.onstop = async () => {
        clearSilenceTimer();
        stopStream();
        const durationMs = Math.max(0, Date.now() - startedAtRef.current);
        if (chunksRef.current.length === 0 || durationMs < 800) {
          setState("silence_timeout");
          setErrorMessage("Не услышал ответ. Попробуйте записать ещё раз.");
          return;
        }
        setState("transcribing");
        const blob = new Blob(chunksRef.current, { type: mimeTypeRef.current });
        if (blob.size < 1200) {
          setState("silence_timeout");
          setErrorMessage("Запись слишком тихая или короткая. Попробуйте ещё раз.");
          return;
        }
        try {
          const { text } = await sttApi.transcribe(blob);
          const transcript = text.trim();
          if (!transcript) {
            setState("silence_timeout");
            setErrorMessage("Речь не распознана. Запишите ответ ещё раз или используйте текстовый fallback.");
            return;
          }
          const wordCount = transcript.split(/\s+/).filter(Boolean).length;
          onTranscript(transcript, {
            audio_size_bytes: blob.size,
            duration_ms: durationMs,
            transcript_quality: wordCount >= 4 ? "good" : "low",
          });
          setState("review");
        } catch (err: unknown) {
          setState("error");
          setErrorMessage(err instanceof Error ? err.message : "Voice transcription failed");
        }
      };

      recorder.start(250);
      silenceTimerRef.current = window.setTimeout(() => {
        if (recorderRef.current?.state === "recording" && chunksRef.current.length === 0) {
          recorderRef.current.stop();
        }
      }, 12000);
      setState("listening");
    } catch {
      resetRecorder();
      setState("microphone_error");
      setErrorMessage("Microphone permission denied or unavailable");
    }
  }, [canStart, clearSilenceTimer, onTranscript, resetRecorder, state, stopStream]);

  const stop = useCallback(() => {
    if (recorderRef.current && recorderRef.current.state === "recording") {
      recorderRef.current.stop();
    }
  }, []);

  const reset = useCallback(() => {
    resetRecorder();
    setErrorMessage("");
    setState("idle");
  }, [resetRecorder]);

  const markSubmitted = useCallback(() => {
    setErrorMessage("");
    setState("submitted");
  }, []);

  const clearError = useCallback(() => setErrorMessage(""), []);

  return { state, start, stop, reset, markSubmitted, errorMessage, clearError };
}
