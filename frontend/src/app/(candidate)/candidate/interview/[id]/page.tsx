"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import { useTTS } from "@/hooks/useTTS";
import { useMediaRecorder } from "@/hooks/useMediaRecorder";
import { useVoiceInput } from "@/hooks/useVoiceInput";
import { useFaceDetection } from "@/hooks/useFaceDetection";
import { candidateApi, interviewApi } from "@/lib/api";
import type { InterviewDetail, InterviewMessage } from "@/lib/types";

const REPORT_POLL_INTERVAL_MS = 1500;
const REPORT_POLL_TIMEOUT_MS = 120000;

export default function InterviewPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { loading: authLoading } = useAuth();

  const [interview, setInterview] = useState<InterviewDetail | null>(null);
  const [messages, setMessages] = useState<InterviewMessage[]>([]);
  const [questionCount, setQuestionCount] = useState(0);
  const [maxQuestions, setMaxQuestions] = useState(8);
  const [currentQuestion, setCurrentQuestion] = useState<string | null>(null);
  const [canFinish, setCanFinish] = useState(false);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [waitingForReport, setWaitingForReport] = useState(false);
  const [error, setError] = useState("");
  const [answerMode, setAnswerMode] = useState<"text" | "voice">("text");
  const [latestTranscript, setLatestTranscript] = useState("");
  const [recordingUploadState, setRecordingUploadState] = useState<"idle" | "uploading" | "uploaded" | "failed" | "skipped">("idle");
  const bottomRef = useRef<HTMLDivElement>(null);
  const autoRecordingAttemptedRef = useRef(false);

  // Behavioral signals tracking (Feature 7)
  const pasteCountRef = useRef(0);
  const tabSwitchCountRef = useRef(0);
  const questionStartTimeRef = useRef<number>(Date.now());
  const responseTimes = useRef<{ q: number; seconds: number }[]>([]);
  const currentQNumRef = useRef(1);

  // Resume panel
  const [resumeText, setResumeText] = useState<string | null>(null);
  const [resumeOpen, setResumeOpen] = useState(false);

  // Recording is mandatory for interview flow.
  const [recordingConsent, setRecordingConsent] = useState(false);

  // Language is loaded from interview, default "ru" until loaded
  const [interviewLanguage, setInterviewLanguage] = useState<string>("ru");
  const { enabled: ttsEnabled, speaking, speak, stop, toggle: toggleTTS } = useTTS(interviewLanguage);
  const {
    isRecording,
    isScreenSharing,
    previewRef,
    startRecording,
    stopRecording,
    getBlob,
    clearRecording,
    errorMessage: recordingError,
  } = useMediaRecorder();
  const { faceAwayPct, isModelLoaded: faceModelLoaded } = useFaceDetection(previewRef, recordingConsent);
  const { state: voiceState, start: startVoice, stop: stopVoice, errorMessage: voiceError, clearError: clearVoiceError } = useVoiceInput({
    onTranscript: (text) => {
      setLatestTranscript(text);
      setInput((prev) => (prev ? `${prev} ${text}` : text));
    },
  });

  // Load interview on mount
  useEffect(() => {
    if (!id || authLoading) return;
    interviewApi
      .getDetail(id)
      .then((data) => {
        setInterview(data);
        setMessages(data.messages.filter((m) => m.role !== "system"));
        setQuestionCount(data.question_count);
        setMaxQuestions(data.max_questions);
        if (data.language) setInterviewLanguage(data.language);

        if (data.status === "report_generated" && data.report_id) {
          router.replace(`/candidate/reports/${data.report_id}`);
          return;
        }

        const lastAssistant = [...data.messages]
          .reverse()
          .find((m) => m.role === "assistant");
        const lastMsg = data.messages[data.messages.length - 1];
        const waitingForAnswer = lastMsg?.role === "assistant";

        if (
          data.question_count >= data.max_questions &&
          lastMsg?.role === "candidate"
        ) {
          setCanFinish(true);
          setCurrentQuestion(null);
        } else if (waitingForAnswer && lastAssistant) {
          setCurrentQuestion(lastAssistant.content);
          speak(lastAssistant.content, data.language ?? "ru");
        }
      })
      .catch(() => setError("Could not load interview"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, authLoading]);

  // Load resume text
  useEffect(() => {
    if (!id || authLoading) return;
    candidateApi.getResumeText().then((r) => setResumeText(r.raw_text)).catch(() => null);
  }, [id, authLoading]);

  // Track behavioral signals
  useEffect(() => {
    function onVisibilityChange() {
      if (document.hidden) tabSwitchCountRef.current++;
    }
    function onBlur() {
      tabSwitchCountRef.current++;
    }
    document.addEventListener("visibilitychange", onVisibilityChange);
    window.addEventListener("blur", onBlur);
    return () => {
      document.removeEventListener("visibilitychange", onVisibilityChange);
      window.removeEventListener("blur", onBlur);
    };
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    if (!interview || interview.status !== "in_progress") return;
    if (recordingConsent || autoRecordingAttemptedRef.current) return;
    autoRecordingAttemptedRef.current = true;

    void startRecording().then((ok) => {
      setRecordingConsent(ok);
    });
  }, [interview, recordingConsent, startRecording]);

  useEffect(() => {
    if (interview && interview.status !== "in_progress") {
      stopRecording();
    }
  }, [interview, stopRecording]);

  async function waitForReport(interviewId: string): Promise<string> {
    const deadline = Date.now() + REPORT_POLL_TIMEOUT_MS;
    while (Date.now() < deadline) {
      try {
        const detail = await interviewApi.getDetail(interviewId);
        if (detail.status === "report_generated" && detail.report_id) {
          return detail.report_id;
        }
        if (detail.status === "failed") {
          throw new Error("Report generation failed. Please retry finishing the interview.");
        }
      } catch (err: unknown) {
        if (err instanceof Error && err.message.includes("Report generation failed")) {
          throw err;
        }
      }
      await new Promise((resolve) => setTimeout(resolve, REPORT_POLL_INTERVAL_MS));
    }
    throw new Error("Report is taking too long. Please refresh this page in a few moments.");
  }

  async function handleSend() {
    if (!recordingConsent || !input.trim() || sending || !id) return;
    const text = input.trim();

    // Record response time for this question
    const elapsed = (Date.now() - questionStartTimeRef.current) / 1000;
    responseTimes.current.push({ q: currentQNumRef.current, seconds: Math.round(elapsed) });
    questionStartTimeRef.current = Date.now();

    setInput("");
    setLatestTranscript("");
    setSending(true);
    setError("");
    stop();
    clearVoiceError();

    const optimistic: InterviewMessage = {
      role: "candidate",
      content: text,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, optimistic]);

    try {
      const res = await interviewApi.sendMessage(id, { message: text });
      setQuestionCount(res.question_count);
      setCurrentQuestion(res.current_question);

      if (res.current_question) {
        currentQNumRef.current = res.question_count;
        questionStartTimeRef.current = Date.now();
        const aiMsg: InterviewMessage = {
          role: "assistant",
          content: res.current_question,
          created_at: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, aiMsg]);
        setCanFinish(false);
        speak(res.current_question, interviewLanguage);
      } else {
        setCanFinish(true);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to send message");
      setMessages((prev) => prev.slice(0, -1));
      setInput(text);
    } finally {
      setSending(false);
    }
  }

  async function handleFinish() {
    if (!id || finishing) return;
    stop();
    stopRecording();
    setFinishing(true);
    setWaitingForReport(false);
    setError("");
    try {
      let recordingNotice: string | null = null;
      // Ensure MediaRecorder has time to flush its last chunk.
      await new Promise((resolve) => setTimeout(resolve, 300));
      const recordingBlob = getBlob();
      if (recordingBlob && recordingBlob.size > 0) {
        setRecordingUploadState("uploading");
        try {
          await interviewApi.uploadRecording(id, recordingBlob);
          setRecordingUploadState("uploaded");
          clearRecording();
        } catch (uploadErr: unknown) {
          setRecordingUploadState("failed");
          setError(uploadErr instanceof Error ? uploadErr.message : "Recording upload failed");
          recordingNotice = "recording_failed";
        }
      } else {
        setRecordingUploadState("skipped");
        recordingNotice = "recording_skipped";
      }
      // Submit behavioral signals before finishing
      await interviewApi.submitSignals(id, {
        response_times: responseTimes.current,
        paste_count: pasteCountRef.current,
        tab_switches: tabSwitchCountRef.current,
        face_away_pct: faceAwayPct,
      }).catch(() => null);

      const res = await interviewApi.finish(id);
      let reportId: string | null = null;
      if (res.status === "report_generated" && res.report_id) {
        reportId = res.report_id;
      } else {
        setWaitingForReport(true);
        reportId = await waitForReport(id);
      }
      const suffix = recordingNotice ? `?notice=${recordingNotice}` : "";
      router.push(`/candidate/reports/${reportId}${suffix}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to finish interview");
    } finally {
      setWaitingForReport(false);
      setFinishing(false);
    }
  }

  async function handleConsentAndRecord() {
    const ok = await startRecording();
    setRecordingConsent(ok);
  }

  if (authLoading || !interview) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="text-slate-400">{error || "Loading interview…"}</div>
      </div>
    );
  }

  const roleLabel = interview.target_role.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  const progress = Math.round((questionCount / maxQuestions) * 100);
  const voiceMode = answerMode === "voice";
  const uploadStatusLabel =
    recordingUploadState === "uploading"
      ? "Uploading recording…"
      : recordingUploadState === "uploaded"
      ? "Recording uploaded"
      : recordingUploadState === "failed"
      ? "Recording upload failed"
      : recordingUploadState === "skipped"
      ? "Interview finished without recording upload"
      : null;

  return (
    <div className="min-h-screen bg-slate-900 flex flex-col">
      {/* Header */}
      <header className="border-b border-slate-800 px-6 py-4 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-4">
          <Link href="/candidate/reports" className="text-slate-500 hover:text-slate-300 text-sm transition-colors">
            ←
          </Link>
          <div>
            <span className="text-white font-semibold">{roleLabel} Interview</span>
            <span className="text-slate-400 text-sm ml-3">
              Question {questionCount} of {maxQuestions}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {/* Webcam preview */}
          {isRecording && (
            <video
              ref={previewRef}
              muted
              autoPlay
              playsInline
              className="w-[120px] h-[90px] rounded-lg object-cover border border-slate-700"
            />
          )}
          {/* REC + eye tracking indicator */}
          {isRecording && (
            <span className="flex items-center gap-2">
              <span className="flex items-center gap-1 text-red-400 text-xs font-semibold">
                <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
                REC
              </span>
              <span
                className={`text-xs font-medium ${
                  isScreenSharing ? "text-emerald-400" : "text-yellow-400"
                }`}
                title={isScreenSharing ? "Screen is being recorded" : "Screen sharing inactive"}
              >
                {isScreenSharing ? "🖥️ Screen on" : "🖥️ Screen off"}
              </span>
              {faceModelLoaded && (
                <span
                  className={`text-xs font-medium ${
                    faceAwayPct !== null && faceAwayPct > 0.3
                      ? "text-orange-400"
                      : "text-green-400"
                  }`}
                  title={`Face detection: ${faceAwayPct !== null ? Math.round(faceAwayPct * 100) + "% away" : "detecting…"}`}
                >
                  {faceAwayPct !== null && faceAwayPct > 0.3 ? "👁️‍🗨️ Look at camera" : "👁️"}
                </span>
              )}
            </span>
          )}
          {!recordingConsent && interview.status === "in_progress" && (
            <span className="text-xs px-3 py-1.5 rounded-lg border border-yellow-500/40 bg-yellow-500/10 text-yellow-300">
              Recording required
            </span>
          )}
          {/* Resume panel toggle */}
          {resumeText && (
            <button
              onClick={() => setResumeOpen((v) => !v)}
              title="Toggle resume panel"
              className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${
                resumeOpen
                  ? "bg-purple-500/15 border-purple-500/30 text-purple-400"
                  : "bg-slate-700/50 border-slate-600 text-slate-400 hover:text-slate-300"
              }`}
            >
              Резюме
            </button>
          )}
          {/* TTS toggle */}
          <button
            onClick={toggleTTS}
            title={ttsEnabled ? "Mute voice" : "Enable voice"}
            className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border transition-colors ${
              ttsEnabled
                ? "bg-blue-500/15 border-blue-500/30 text-blue-400 hover:bg-blue-500/25"
                : "bg-slate-700/50 border-slate-600 text-slate-500 hover:text-slate-400"
            }`}
          >
            {speaking ? (
              <span className="flex gap-0.5 items-end h-3">
                <span className="w-0.5 bg-current rounded-full animate-[soundbar_0.8s_ease-in-out_infinite]" style={{ height: "40%" }} />
                <span className="w-0.5 bg-current rounded-full animate-[soundbar_0.8s_ease-in-out_0.2s_infinite]" style={{ height: "100%" }} />
                <span className="w-0.5 bg-current rounded-full animate-[soundbar_0.8s_ease-in-out_0.4s_infinite]" style={{ height: "60%" }} />
              </span>
            ) : (
              <span>{ttsEnabled ? "🔊" : "🔇"}</span>
            )}
            {ttsEnabled ? "Voice on" : "Voice off"}
          </button>
          {/* Progress bar */}
          <div className="w-24 h-1.5 bg-slate-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-500 rounded-full transition-all"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
      </header>

      {/* Body */}
      <div className="flex flex-1 overflow-hidden relative">
        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-6 space-y-4 max-w-2xl w-full mx-auto">
          {messages.map((msg, i) => (
            <MessageBubble
              key={i}
              msg={msg}
              onReplay={msg.role === "assistant" ? () => speak(msg.content, interviewLanguage) : undefined}
              speaking={speaking}
            />
          ))}
          <div ref={bottomRef} />
        </div>

        {/* Resume panel */}
        {resumeOpen && resumeText && (
          <aside className="fixed right-0 top-0 h-full w-80 bg-slate-800 border-l border-slate-700 overflow-y-auto p-4 z-10">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-white font-semibold text-sm">Резюме</h3>
              <button
                onClick={() => setResumeOpen(false)}
                className="text-slate-400 hover:text-white text-lg leading-none"
              >
                ✕
              </button>
            </div>
            <pre className="text-slate-300 text-xs whitespace-pre-wrap leading-relaxed font-sans">
              {resumeText}
            </pre>
          </aside>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="max-w-2xl w-full mx-auto px-4">
          <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg px-4 py-3 mb-3">
            {error}
          </div>
        </div>
      )}

      {!recordingConsent && interview.status === "in_progress" && (
        <div className="max-w-2xl w-full mx-auto px-4 pb-4">
          <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-xl p-5">
            <div className="text-yellow-300 font-semibold mb-1">Recording required</div>
            <div className="text-slate-300 text-sm mb-4">
              To continue the interview, enable screen, camera, and microphone recording.
            </div>
            <button
              onClick={handleConsentAndRecord}
              className="bg-yellow-500/80 hover:bg-yellow-500 text-slate-900 font-semibold px-4 py-2 rounded-lg transition-colors"
            >
              Enable recording
            </button>
          </div>
        </div>
      )}

      {/* Finish CTA */}
      {canFinish && (
        <div className="max-w-2xl w-full mx-auto px-4 pb-4">
          <div className="bg-blue-500/10 border border-blue-500/30 rounded-xl p-5 text-center">
            <div className="text-white font-semibold mb-1">Interview complete!</div>
            <div className="text-slate-400 text-sm mb-4">
              You&apos;ve answered all {maxQuestions} questions. Generate your assessment report now.
            </div>
            {uploadStatusLabel && (
              <div className={`mb-4 text-sm ${recordingUploadState === "failed" ? "text-red-400" : "text-slate-300"}`}>
                {uploadStatusLabel}
              </div>
            )}
            <button
              onClick={handleFinish}
              disabled={finishing}
              className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white font-semibold px-8 py-2.5 rounded-lg transition-colors"
            >
              {finishing ? (waitingForReport ? "Waiting for report…" : "Generating report…") : "Finish & Get Report"}
            </button>
          </div>
        </div>
      )}

      {/* Input */}
      {!canFinish && interview.status === "in_progress" && recordingConsent && (
        <div className="border-t border-slate-800 px-4 py-4 shrink-0">
          <div className="max-w-2xl mx-auto space-y-3">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setAnswerMode("text")}
                  className={`rounded-lg border px-3 py-1.5 text-xs transition-colors ${
                    !voiceMode
                      ? "border-blue-500/30 bg-blue-500/10 text-blue-300"
                      : "border-slate-700 text-slate-400 hover:text-slate-200"
                  }`}
                >
                  Text mode
                </button>
                <button
                  onClick={() => setAnswerMode("voice")}
                  className={`rounded-lg border px-3 py-1.5 text-xs transition-colors ${
                    voiceMode
                      ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                      : "border-slate-700 text-slate-400 hover:text-slate-200"
                  }`}
                >
                  Voice mode
                </button>
              </div>
              {voiceMode && (
                <p className="text-xs text-slate-500">
                  Hold the mic, then review the transcript before sending.
                </p>
              )}
            </div>

            {(voiceMode || voiceError || recordingError || latestTranscript) && (
              <div className="rounded-xl border border-slate-800 bg-slate-800/60 px-4 py-3 text-sm">
                {latestTranscript && (
                  <p className="text-slate-300">
                    Latest transcript captured. Edit the draft below before sending.
                  </p>
                )}
                {voiceError && <p className="text-red-400 mt-1">{voiceError}</p>}
                {recordingError && <p className="text-yellow-400 mt-1">{recordingError}</p>}
              </div>
            )}

            <div className="flex gap-3">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onPaste={() => { pasteCountRef.current++; }}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              placeholder={
                voiceMode && voiceState === "recording"
                  ? "🎙 Listening…"
                  : voiceMode && voiceState === "transcribing"
                  ? "⏳ Transcribing…"
                  : voiceMode
                  ? "Transcript preview. Edit before sending…"
                  : "Type your answer… (Enter to send, Shift+Enter for new line)"
              }
              rows={2}
              className="flex-1 bg-slate-800 border border-slate-700 text-white rounded-xl px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder-slate-500 resize-none"
            />
            {voiceMode && (
              <button
                onMouseDown={startVoice}
                onMouseUp={stopVoice}
                onTouchStart={startVoice}
                onTouchEnd={stopVoice}
                disabled={sending || voiceState === "transcribing"}
                title="Hold to speak"
                className={`px-4 rounded-xl transition-colors font-medium border select-none ${
                  voiceState === "recording"
                    ? "bg-red-500/20 border-red-500/50 text-red-400 animate-pulse"
                    : voiceState === "transcribing"
                    ? "bg-slate-700 border-slate-600 text-slate-400 opacity-60"
                    : voiceState === "error"
                    ? "bg-red-500/10 border-red-500/30 text-red-400"
                    : "bg-slate-700 border-slate-600 text-slate-300 hover:border-slate-500"
                }`}
              >
                {voiceState === "recording" ? "🔴" : voiceState === "transcribing" ? "⏳" : "🎙"}
              </button>
            )}
            <button
              onClick={handleSend}
              disabled={!input.trim() || sending}
              className="bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white px-5 rounded-xl transition-colors font-medium"
            >
              {sending ? "…" : "Send"}
            </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function MessageBubble({
  msg,
  onReplay,
  speaking,
}: {
  msg: InterviewMessage;
  onReplay?: () => void;
  speaking: boolean;
}) {
  const isAI = msg.role === "assistant";
  return (
    <div className={`flex ${isAI ? "justify-start" : "justify-end"}`}>
      <div className="group relative max-w-[80%]">
        <div
          className={`rounded-2xl px-4 py-3 text-sm leading-relaxed ${
            isAI
              ? "bg-slate-800 border border-slate-700 text-slate-100 rounded-bl-sm"
              : "bg-blue-600 text-white rounded-br-sm"
          }`}
        >
          {isAI && (
            <div className="text-blue-400 text-xs font-medium mb-1 uppercase tracking-wide">
              AI Interviewer
            </div>
          )}
          {msg.content}
        </div>
        {/* Replay button — shown on hover for AI messages */}
        {isAI && onReplay && (
          <button
            onClick={onReplay}
            title="Replay question"
            className="absolute -bottom-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity bg-slate-700 hover:bg-slate-600 text-slate-300 text-xs rounded-full w-6 h-6 flex items-center justify-center"
          >
            {speaking ? "■" : "▶"}
          </button>
        )}
      </div>
    </div>
  );
}
