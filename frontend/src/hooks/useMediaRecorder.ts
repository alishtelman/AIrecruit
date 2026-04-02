"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { consumePreparedInterviewMedia } from "@/lib/interviewMediaSession";

/**
 * useMediaRecorder — captures screen + microphone via MediaRecorder,
 * while keeping a webcam preview for the candidate.
 *
 * - Recording is best-effort (interview continues even if permissions are denied)
 * - Prefers video/webm; falls back to video/mp4 for Safari
 * - Returns a webcam preview ref to attach to a <video> element
 */
export function useMediaRecorder() {
  const [isRecording, setIsRecording] = useState(false);
  const [isScreenSharing, setIsScreenSharing] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const webcamStreamRef = useRef<MediaStream | null>(null);
  const screenStreamRef = useRef<MediaStream | null>(null);
  const recordingStreamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const previewRef = useRef<HTMLVideoElement | null>(null);

  const cleanupStreams = useCallback(() => {
    if (recordingStreamRef.current) {
      recordingStreamRef.current.getTracks().forEach((t) => t.stop());
      recordingStreamRef.current = null;
    }
    if (screenStreamRef.current) {
      screenStreamRef.current.getTracks().forEach((t) => t.stop());
      screenStreamRef.current = null;
    }
    if (webcamStreamRef.current) {
      webcamStreamRef.current.getTracks().forEach((t) => t.stop());
      webcamStreamRef.current = null;
    }
    if (previewRef.current) {
      previewRef.current.srcObject = null;
    }
    setIsRecording(false);
    setIsScreenSharing(false);
  }, []);

  const startRecording = useCallback(async (): Promise<boolean> => {
    setErrorMessage("");
    try {
      const prepared = consumePreparedInterviewMedia();
      const screenStream = prepared
        ? prepared.screenStream
        : await navigator.mediaDevices.getDisplayMedia({
            video: { frameRate: { ideal: 15, max: 30 } },
            audio: false,
          });
      const screenVideoTrack = screenStream.getVideoTracks()[0];
      if (!screenVideoTrack || screenVideoTrack.readyState === "ended") {
        throw new Error("Screen capture stream is unavailable");
      }
      screenStreamRef.current = screenStream;
      setIsScreenSharing(true);

      const webcamStream = prepared
        ? prepared.webcamStream
        : await navigator.mediaDevices.getUserMedia({
            video: true,
            audio: true,
          });
      webcamStreamRef.current = webcamStream;

      if (previewRef.current) {
        previewRef.current.srcObject = webcamStream;
      }

      const recordingTracks: MediaStreamTrack[] = [];
      if (screenVideoTrack) {
        recordingTracks.push(screenVideoTrack);
      }
      recordingTracks.push(...webcamStream.getAudioTracks());
      const recordingStream = new MediaStream(recordingTracks);
      recordingStreamRef.current = recordingStream;

      screenVideoTrack?.addEventListener("ended", () => {
        setErrorMessage("Screen sharing was stopped. Recording ended.");
        if (recorderRef.current && recorderRef.current.state !== "inactive") {
          recorderRef.current.stop();
        }
        cleanupStreams();
      });

      const mimeType = MediaRecorder.isTypeSupported("video/webm")
        ? "video/webm"
        : MediaRecorder.isTypeSupported("video/mp4")
        ? "video/mp4"
        : "";

      const recorder = new MediaRecorder(recordingStream, mimeType ? { mimeType } : undefined);
      recorderRef.current = recorder;
      chunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) {
          chunksRef.current.push(e.data);
        }
      };

      recorder.start(1000); // collect chunks every second
      setIsRecording(true);
      return true;
    } catch {
      setErrorMessage(
        "Screen, camera, or microphone permission denied. Interview will continue without recording.",
      );
      cleanupStreams();
      return false;
    }
  }, [cleanupStreams]);

  const stopRecording = useCallback(() => {
    if (recorderRef.current && recorderRef.current.state !== "inactive") {
      recorderRef.current.stop();
    }
    cleanupStreams();
  }, [cleanupStreams]);

  const getBlob = useCallback((): Blob | null => {
    if (chunksRef.current.length === 0) return null;
    const mimeType = recorderRef.current?.mimeType ?? "video/webm";
    return new Blob(chunksRef.current, { type: mimeType });
  }, []);

  const clearRecording = useCallback(() => {
    chunksRef.current = [];
  }, []);

  useEffect(() => {
    return () => {
      cleanupStreams();
    };
  }, [cleanupStreams]);

  useEffect(() => {
    if (!isRecording) return;
    const preview = previewRef.current;
    const webcamStream = webcamStreamRef.current;
    if (!preview || !webcamStream) return;

    if (preview.srcObject !== webcamStream) {
      preview.srcObject = webcamStream;
    }
    preview.muted = true;
    preview.playsInline = true;
    void preview.play().catch(() => {
      setErrorMessage("Camera preview could not start automatically.");
    });
  }, [isRecording]);

  return {
    isRecording,
    isScreenSharing,
    previewRef,
    startRecording,
    stopRecording,
    getBlob,
    clearRecording,
    errorMessage,
  };
}
