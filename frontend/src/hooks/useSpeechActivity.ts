"use client";

import { useEffect, useRef, useState } from "react";

interface SpeechActivityResult {
  speechActivityPct: number | null;
  silencePct: number | null;
  longSilenceCount: number;
  speechSegmentCount: number;
  isSpeechActive: boolean;
  isMonitoringSupported: boolean;
}

const SAMPLE_INTERVAL_MS = 500;
const SPEECH_RMS_THRESHOLD = 0.018;
const LONG_SILENCE_MS = 12000;

type AudioContextCtor = typeof AudioContext;

function getAudioContextCtor(): AudioContextCtor | null {
  if (typeof window === "undefined") return null;
  const win = window as Window & typeof globalThis & { webkitAudioContext?: AudioContextCtor };
  return win.AudioContext ?? win.webkitAudioContext ?? null;
}

export function useSpeechActivity(
  getStream: () => MediaStream | null,
  active: boolean,
): SpeechActivityResult {
  const [speechActivityPct, setSpeechActivityPct] = useState<number | null>(null);
  const [silencePct, setSilencePct] = useState<number | null>(null);
  const [longSilenceCount, setLongSilenceCount] = useState(0);
  const [speechSegmentCount, setSpeechSegmentCount] = useState(0);
  const [isSpeechActive, setIsSpeechActive] = useState(false);
  const [isMonitoringSupported, setIsMonitoringSupported] = useState(() => Boolean(getAudioContextCtor()));

  const totalSamplesRef = useRef(0);
  const speechSamplesRef = useRef(0);
  const longSilenceCountRef = useRef(0);
  const speechSegmentCountRef = useRef(0);
  const previousSpeechActiveRef = useRef(false);
  const currentSilenceMsRef = useRef(0);
  const longSilenceRegisteredRef = useRef(false);

  useEffect(() => {
    const AudioContextClass = getAudioContextCtor();
    setIsMonitoringSupported(Boolean(AudioContextClass));
    if (!active || !AudioContextClass) {
      return;
    }

    const stream = getStream();
    const hasAudioTrack = Boolean(stream?.getAudioTracks().some((track) => track.readyState === "live"));
    if (!stream || !hasAudioTrack) {
      setIsSpeechActive(false);
      return;
    }

    totalSamplesRef.current = 0;
    speechSamplesRef.current = 0;
    longSilenceCountRef.current = 0;
    speechSegmentCountRef.current = 0;
    previousSpeechActiveRef.current = false;
    currentSilenceMsRef.current = 0;
    longSilenceRegisteredRef.current = false;
    setSpeechActivityPct(null);
    setSilencePct(null);
    setLongSilenceCount(0);
    setSpeechSegmentCount(0);
    setIsSpeechActive(false);

    const audioContext = new AudioContextClass();
    const analyser = audioContext.createAnalyser();
    analyser.fftSize = 512;
    analyser.smoothingTimeConstant = 0.2;

    const source = audioContext.createMediaStreamSource(stream);
    source.connect(analyser);
    const waveform = new Float32Array(analyser.fftSize);

    const intervalId = window.setInterval(() => {
      analyser.getFloatTimeDomainData(waveform);
      let squaredSum = 0;
      for (let idx = 0; idx < waveform.length; idx += 1) {
        squaredSum += waveform[idx] * waveform[idx];
      }
      const rms = Math.sqrt(squaredSum / waveform.length);
      const detectedSpeech = rms >= SPEECH_RMS_THRESHOLD;

      totalSamplesRef.current += 1;
      if (detectedSpeech) {
        speechSamplesRef.current += 1;
      }

      if (detectedSpeech && !previousSpeechActiveRef.current) {
        speechSegmentCountRef.current += 1;
        setSpeechSegmentCount(speechSegmentCountRef.current);
      }

      if (detectedSpeech) {
        currentSilenceMsRef.current = 0;
        longSilenceRegisteredRef.current = false;
      } else {
        currentSilenceMsRef.current += SAMPLE_INTERVAL_MS;
        if (
          currentSilenceMsRef.current >= LONG_SILENCE_MS
          && !longSilenceRegisteredRef.current
        ) {
          longSilenceCountRef.current += 1;
          longSilenceRegisteredRef.current = true;
          setLongSilenceCount(longSilenceCountRef.current);
        }
      }

      previousSpeechActiveRef.current = detectedSpeech;
      setIsSpeechActive(detectedSpeech);

      const activity = speechSamplesRef.current / totalSamplesRef.current;
      setSpeechActivityPct(Math.round(activity * 100) / 100);
      setSilencePct(Math.round((1 - activity) * 100) / 100);
    }, SAMPLE_INTERVAL_MS);

    return () => {
      window.clearInterval(intervalId);
      source.disconnect();
      analyser.disconnect();
      void audioContext.close().catch(() => undefined);
    };
  }, [active, getStream]);

  return {
    speechActivityPct,
    silencePct,
    longSilenceCount,
    speechSegmentCount,
    isSpeechActive,
    isMonitoringSupported,
  };
}
