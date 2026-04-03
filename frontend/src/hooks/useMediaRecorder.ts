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
  type RecorderErrorCode =
    | "none"
    | "screen_permission_denied"
    | "camera_permission_denied"
    | "microphone_permission_denied"
    | "screen_stream_unavailable"
    | "camera_stream_unavailable"
    | "microphone_stream_unavailable"
    | "screen_share_stopped"
    | "camera_stream_lost"
    | "preview_start_failed"
    | "recording_error";

  const [isRecording, setIsRecording] = useState(false);
  const [isScreenSharing, setIsScreenSharing] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [errorCode, setErrorCode] = useState<RecorderErrorCode>("none");
  const [cameraPreviewReady, setCameraPreviewReady] = useState(false);
  const webcamStreamRef = useRef<MediaStream | null>(null);
  const screenStreamRef = useRef<MediaStream | null>(null);
  const recordingStreamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const previewRef = useRef<HTMLVideoElement | null>(null);

  const setRecorderError = useCallback((code: RecorderErrorCode, message: string) => {
    setErrorCode(code);
    setErrorMessage(message);
  }, []);

  const bindPreview = useCallback((webcamStream: MediaStream) => {
    const preview = previewRef.current;
    if (!preview) return;
    if (preview.srcObject !== webcamStream) {
      preview.srcObject = webcamStream;
    }
    preview.muted = true;
    preview.playsInline = true;
    preview.autoplay = true;

    const tryPlay = () => {
      void preview.play()
        .then(() => {
          setCameraPreviewReady(true);
        })
        .catch(() => {
          setCameraPreviewReady(false);
          setRecorderError("preview_start_failed", "Camera preview could not start automatically.");
        });
    };

    if (preview.readyState >= 2) {
      tryPlay();
      return;
    }
    const onLoaded = () => {
      preview.removeEventListener("loadedmetadata", onLoaded);
      tryPlay();
    };
    preview.addEventListener("loadedmetadata", onLoaded);
  }, [setRecorderError]);

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
    setCameraPreviewReady(false);
    setIsRecording(false);
    setIsScreenSharing(false);
  }, []);

  const mapPermissionError = useCallback((error: unknown): { code: RecorderErrorCode; message: string } => {
    const err = error instanceof Error ? error : null;
    const normalizedName = err?.name?.toLowerCase() ?? "";
    const normalizedMessage = err?.message?.toLowerCase() ?? "";

    if (normalizedName.includes("notallowed") || normalizedName.includes("permission")) {
      if (normalizedMessage.includes("microphone") || normalizedMessage.includes("audio")) {
        return {
          code: "microphone_permission_denied",
          message: "Microphone permission denied. Interview will continue without recording.",
        };
      }
      if (normalizedMessage.includes("camera") || normalizedMessage.includes("video")) {
        return {
          code: "camera_permission_denied",
          message: "Camera permission denied. Interview will continue without recording.",
        };
      }
      return {
        code: "screen_permission_denied",
        message: "Screen permission denied. Interview will continue without recording.",
      };
    }

    if (normalizedName.includes("notfound") || normalizedName.includes("devicesnotfound")) {
      if (normalizedMessage.includes("microphone") || normalizedMessage.includes("audio")) {
        return {
          code: "microphone_stream_unavailable",
          message: "Microphone is unavailable. Interview will continue without recording.",
        };
      }
      if (normalizedMessage.includes("camera") || normalizedMessage.includes("video")) {
        return {
          code: "camera_stream_unavailable",
          message: "Camera is unavailable. Interview will continue without recording.",
        };
      }
      return {
        code: "screen_stream_unavailable",
        message: "Screen capture is unavailable. Interview will continue without recording.",
      };
    }

    return {
      code: "recording_error",
      message: "Screen, camera, or microphone permission denied. Interview will continue without recording.",
    };
  }, []);

  const startRecording = useCallback(async (): Promise<boolean> => {
    setErrorMessage("");
    setErrorCode("none");
    setCameraPreviewReady(false);
    try {
      const prepared = consumePreparedInterviewMedia();
      let screenStream: MediaStream;
      if (prepared) {
        screenStream = prepared.screenStream;
      } else {
        try {
          screenStream = await navigator.mediaDevices.getDisplayMedia({
            video: { frameRate: { ideal: 15, max: 30 } },
            audio: false,
          });
        } catch (error: unknown) {
          const mapped = mapPermissionError(error);
          const code =
            mapped.code === "recording_error"
              ? "screen_permission_denied"
              : mapped.code;
          const message =
            mapped.code === "recording_error"
              ? "Screen permission denied. Interview will continue without recording."
              : mapped.message;
          setRecorderError(code, message);
          cleanupStreams();
          return false;
        }
      }
      const screenVideoTrack = screenStream.getVideoTracks()[0];
      if (!screenVideoTrack || screenVideoTrack.readyState === "ended") {
        setRecorderError("screen_stream_unavailable", "Screen capture stream is unavailable.");
        cleanupStreams();
        return false;
      }
      screenStreamRef.current = screenStream;
      setIsScreenSharing(true);

      let webcamStream: MediaStream;
      if (prepared) {
        webcamStream = prepared.webcamStream;
      } else {
        try {
          webcamStream = await navigator.mediaDevices.getUserMedia({
            video: true,
            audio: true,
          });
        } catch (error: unknown) {
          const mapped = mapPermissionError(error);
          const code =
            mapped.code === "screen_permission_denied"
              ? "camera_permission_denied"
              : mapped.code;
          const message =
            mapped.code === "screen_permission_denied"
              ? "Camera or microphone permission denied. Interview will continue without recording."
              : mapped.message;
          setRecorderError(code, message);
          cleanupStreams();
          return false;
        }
      }
      webcamStreamRef.current = webcamStream;

      const webcamVideoTrack = webcamStream.getVideoTracks()[0];
      if (!webcamVideoTrack || webcamVideoTrack.readyState === "ended") {
        setRecorderError("camera_stream_unavailable", "Camera stream is unavailable.");
        cleanupStreams();
        return false;
      }
      const microphoneTrack = webcamStream.getAudioTracks()[0];
      if (!microphoneTrack || microphoneTrack.readyState === "ended") {
        setRecorderError("microphone_stream_unavailable", "Microphone stream is unavailable.");
        cleanupStreams();
        return false;
      }

      bindPreview(webcamStream);

      const recordingTracks: MediaStreamTrack[] = [];
      if (screenVideoTrack) {
        recordingTracks.push(screenVideoTrack);
      }
      recordingTracks.push(...webcamStream.getAudioTracks());
      const recordingStream = new MediaStream(recordingTracks);
      recordingStreamRef.current = recordingStream;

      screenVideoTrack?.addEventListener("ended", () => {
        setRecorderError("screen_share_stopped", "Screen sharing was stopped. Recording ended.");
        if (recorderRef.current && recorderRef.current.state !== "inactive") {
          recorderRef.current.stop();
        }
        cleanupStreams();
      });
      webcamVideoTrack?.addEventListener("ended", () => {
        setRecorderError("camera_stream_lost", "Camera stream was stopped. Recording ended.");
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
    } catch (error: unknown) {
      const mapped = mapPermissionError(error);
      setRecorderError(mapped.code, mapped.message);
      cleanupStreams();
      return false;
    }
  }, [bindPreview, cleanupStreams, mapPermissionError, setRecorderError]);

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
    const webcamStream = webcamStreamRef.current;
    if (!webcamStream) return;
    bindPreview(webcamStream);
  }, [bindPreview, isRecording]);

  useEffect(() => {
    const handlePageHide = () => {
      cleanupStreams();
    };
    window.addEventListener("pagehide", handlePageHide);
    return () => {
      window.removeEventListener("pagehide", handlePageHide);
    };
  }, [cleanupStreams]);

  return {
    isRecording,
    isScreenSharing,
    cameraPreviewReady,
    previewRef,
    startRecording,
    stopRecording,
    getBlob,
    clearRecording,
    errorMessage,
    errorCode,
  };
}
