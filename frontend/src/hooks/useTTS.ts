"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getToken } from "@/lib/auth";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * useTTS — text-to-speech hook.
 *
 * Priority:
 *   1. Groq TTS via backend /api/v1/tts  (high quality)
 *   2. Browser SpeechSynthesis            (fallback, no API key)
 */
export function useTTS(language?: string) {
  const [enabled, setEnabled] = useState(true);
  const [speaking, setSpeaking] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null);

  // Clean up on unmount
  useEffect(() => {
    return () => {
      stopCurrent();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function stopCurrent() {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = "";
      audioRef.current = null;
    }
    if (typeof window !== "undefined" && window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }
    utteranceRef.current = null;
    setSpeaking(false);
  }

  const speak = useCallback(
    async (text: string) => {
      if (!enabled || !text.trim()) return;
      stopCurrent();
      setSpeaking(true);

      // Try Groq TTS first
      const token = getToken();
      if (token) {
        try {
          const res = await fetch(`${BASE_URL}/api/v1/tts`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${token}`,
            },
            body: JSON.stringify({ text }),
          });

          if (res.ok) {
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            const audio = new Audio(url);
            audioRef.current = audio;

            audio.onended = () => {
              URL.revokeObjectURL(url);
              audioRef.current = null;
              setSpeaking(false);
            };
            audio.onerror = () => {
              URL.revokeObjectURL(url);
              audioRef.current = null;
              setSpeaking(false);
            };

            await audio.play();
            return;
          }
        } catch {
          // Fall through to browser TTS
        }
      }

      // Fallback: browser SpeechSynthesis
      if (typeof window !== "undefined" && "speechSynthesis" in window) {
        const utter = new SpeechSynthesisUtterance(text);
        utter.lang = language === "en" ? "en-US" : "ru-RU";
        utter.rate = 0.95;
        utter.onend = () => setSpeaking(false);
        utter.onerror = () => setSpeaking(false);
        utteranceRef.current = utter;
        window.speechSynthesis.speak(utter);
      } else {
        setSpeaking(false);
      }
    },
    [enabled, language]
  );

  const stop = useCallback(() => {
    stopCurrent();
  }, []);

  const toggle = useCallback(() => {
    setEnabled((prev) => {
      if (prev) stopCurrent();
      return !prev;
    });
  }, []);

  return { enabled, speaking, speak, stop, toggle };
}
