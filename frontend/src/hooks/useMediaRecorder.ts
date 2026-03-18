"use client";

import { useCallback, useRef, useState } from "react";

/**
 * useMediaRecorder — captures video + audio via MediaRecorder.
 *
 * - Silent fail if permissions denied (interview continues unaffected)
 * - Prefers video/webm; falls back to video/mp4 for Safari
 * - Returns a preview ref to attach to a <video> element
 */
export function useMediaRecorder() {
  const [isRecording, setIsRecording] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const previewRef = useRef<HTMLVideoElement | null>(null);

  const startRecording = useCallback(async () => {
    setErrorMessage("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
      streamRef.current = stream;

      if (previewRef.current) {
        previewRef.current.srcObject = stream;
      }

      const mimeType = MediaRecorder.isTypeSupported("video/webm")
        ? "video/webm"
        : MediaRecorder.isTypeSupported("video/mp4")
        ? "video/mp4"
        : "";

      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      recorderRef.current = recorder;
      chunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) {
          chunksRef.current.push(e.data);
        }
      };

      recorder.start(1000); // collect chunks every second
      setIsRecording(true);
    } catch {
      setErrorMessage("Camera or microphone permission denied. Interview will continue without recording.");
      setIsRecording(false);
    }
  }, []);

  const stopRecording = useCallback(() => {
    if (recorderRef.current && recorderRef.current.state !== "inactive") {
      recorderRef.current.stop();
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    if (previewRef.current) {
      previewRef.current.srcObject = null;
    }
    setIsRecording(false);
  }, []);

  const getBlob = useCallback((): Blob | null => {
    if (chunksRef.current.length === 0) return null;
    const mimeType = recorderRef.current?.mimeType ?? "video/webm";
    return new Blob(chunksRef.current, { type: mimeType });
  }, []);

  const clearRecording = useCallback(() => {
    chunksRef.current = [];
  }, []);

  return { isRecording, previewRef, startRecording, stopRecording, getBlob, clearRecording, errorMessage };
}
