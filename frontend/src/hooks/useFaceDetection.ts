"use client";

import { useEffect, useRef, useState } from "react";

interface FaceDetectionResult {
  faceAwayPct: number | null;
  isModelLoaded: boolean;
}

const MODEL_URL = "https://cdn.jsdelivr.net/npm/face-api.js@0.22.2/weights";
const SAMPLE_INTERVAL_MS = 2000;

/**
 * Periodically samples the given video element for face presence.
 * Returns the percentage of samples where no face was detected.
 * Only runs when `active` is true (i.e. recording consent given).
 */
export function useFaceDetection(
  videoRef: React.RefObject<HTMLVideoElement>,
  active: boolean,
): FaceDetectionResult {
  const [isModelLoaded, setIsModelLoaded] = useState(false);
  const [faceAwayPct, setFaceAwayPct] = useState<number | null>(null);

  const totalSamples = useRef(0);
  const noFaceSamples = useRef(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  // Load face-api.js models once on mount
  useEffect(() => {
    if (typeof window === "undefined") return;

    let cancelled = false;

    async function loadModels() {
      try {
        // Dynamic import to avoid SSR issues
        const faceapi = await import("face-api.js");
        await faceapi.nets.tinyFaceDetector.loadFromUri(MODEL_URL);
        if (!cancelled) setIsModelLoaded(true);
      } catch (err) {
        console.warn("face-api.js model load failed:", err);
      }
    }

    loadModels();
    return () => { cancelled = true; };
  }, []);

  // Start/stop sampling when active changes
  useEffect(() => {
    if (!active || !isModelLoaded) return;

    // Create off-screen canvas for frame capture
    if (!canvasRef.current) {
      canvasRef.current = document.createElement("canvas");
    }

    async function sample() {
      const video = videoRef.current;
      const canvas = canvasRef.current;
      if (!video || !canvas || video.readyState < 2) return;

      try {
        const faceapi = await import("face-api.js");
        canvas.width = video.videoWidth || 320;
        canvas.height = video.videoHeight || 240;
        const ctx = canvas.getContext("2d");
        if (!ctx) return;
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

        const detection = await faceapi.detectSingleFace(
          canvas,
          new faceapi.TinyFaceDetectorOptions({ inputSize: 160, scoreThreshold: 0.4 }),
        );

        totalSamples.current += 1;
        if (!detection) {
          noFaceSamples.current += 1;
        }

        if (totalSamples.current > 0) {
          setFaceAwayPct(
            Math.round((noFaceSamples.current / totalSamples.current) * 100) / 100,
          );
        }
      } catch {
        // silently ignore per-frame errors
      }
    }

    intervalRef.current = setInterval(sample, SAMPLE_INTERVAL_MS);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [active, isModelLoaded, videoRef]);

  return { faceAwayPct, isModelLoaded };
}
