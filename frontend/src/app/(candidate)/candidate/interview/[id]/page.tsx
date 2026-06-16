"use client";

import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { LocaleSwitcher } from "@/components/locale-switcher";
import { Link, useRouter } from "@/i18n/navigation";
import { useAuth } from "@/hooks/useAuth";
import { useTTS } from "@/hooks/useTTS";
import { useMediaRecorder } from "@/hooks/useMediaRecorder";
import { useVoiceInput } from "@/hooks/useVoiceInput";
import { useFaceDetection } from "@/hooks/useFaceDetection";
import { useSpeechActivity } from "@/hooks/useSpeechActivity";
import { candidateApi, interviewApi } from "@/lib/api";
import type {
  InterviewDetail,
  InterviewModuleSession,
  InterviewMessage,
  InterviewReportStatusResponse,
  InterviewStage,
  PracticalTask,
} from "@/lib/types";

const REPORT_POLL_INTERVAL_MS = 1500;
const REPORT_POLL_TIMEOUT_MS = 120000;
const REPORT_SOFT_REFRESH_CYCLES = 2;
const REPORT_SOFT_REFRESH_DELAY_MS = 1000;
const PROCTORING_POLICY_MODE =
  process.env.NEXT_PUBLIC_PROCTORING_POLICY_MODE === "strict_flagging"
    ? "strict_flagging"
    : "observe_only";

// Voice-first feature flags
// NEXT_PUBLIC_ENABLE_VOICE_INTERVIEW — set to "true" to enable the voice UI toggle
// NEXT_PUBLIC_DEFAULT_INTERVIEW_MODE — "voice" or "text" (default: "text" for safety)
// NEXT_PUBLIC_VOICE_AUTO_SEND — "true" to auto-send after STT without confirm (default: false)
const ENABLE_VOICE_INTERVIEW = process.env.NEXT_PUBLIC_ENABLE_VOICE_INTERVIEW === "true";
const ALLOW_TEXT_FALLBACK = process.env.NEXT_PUBLIC_ALLOW_TEXT_FALLBACK === "true";
const DEFAULT_INTERVIEW_MODE: "voice" | "text" = "voice";
const VOICE_AUTO_SEND = process.env.NEXT_PUBLIC_VOICE_AUTO_SEND === "true";

const CODING_TASK_LANGUAGES = ["python", "typescript", "javascript", "go", "java", "sql", "other"] as const;

function estimateInterviewDuration(maxQuestions: number) {
  const safeQuestions = Math.max(1, maxQuestions);
  const min = Math.max(8, Math.round(safeQuestions * 1.2));
  const max = Math.max(min + 2, Math.round(safeQuestions * 1.7));
  return { min, max };
}

function formatElapsedDuration(totalSeconds: number) {
  const safeSeconds = Math.max(0, totalSeconds);
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  const seconds = safeSeconds % 60;

  if (hours > 0) {
    return [hours, minutes, seconds].map((value) => String(value).padStart(2, "0")).join(":");
  }
  return [minutes, seconds].map((value) => String(value).padStart(2, "0")).join(":");
}

function parseApiTimestamp(value: string | null | undefined): number {
  if (!value) return Number.NaN;
  const hasZoneSuffix = /(?:[zZ]|[+-]\d{2}:\d{2})$/.test(value);
  return Date.parse(hasZoneSuffix ? value : `${value}Z`);
}

type StageRailItem = {
  key: string;
  label: string;
  state: "done" | "current" | "upcoming";
};

type ProctoringEvent = {
  event_type: string;
  severity?: "info" | "medium" | "high";
  occurred_at?: string;
  source?: string;
  details?: Record<string, unknown>;
};

type AssessmentProgressLike = {
  assessment_progress?: {
    has_remaining_modules: boolean;
    invite_token: string;
  } | null;
};

export default function InterviewPage() {
  const t = useTranslations("interview");
  const startT = useTranslations("interviewStart");
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { loading: authLoading } = useAuth({ allowedRoles: ["candidate"] });

  const [interview, setInterview] = useState<InterviewDetail | null>(null);
  const [messages, setMessages] = useState<InterviewMessage[]>([]);
  const [questionCount, setQuestionCount] = useState(0);
  const [maxQuestions, setMaxQuestions] = useState(8);
  const [currentQuestion, setCurrentQuestion] = useState<string | null>(null);
  const [canFinish, setCanFinish] = useState(false);
  const [isFollowup, setIsFollowup] = useState(false);
  const [questionType, setQuestionType] = useState("main");
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [reportRetrying, setReportRetrying] = useState(false);
  const [waitingForReport, setWaitingForReport] = useState(false);
  const [reportStatus, setReportStatus] = useState<InterviewReportStatusResponse | null>(null);
  const [retryCountdownSeconds, setRetryCountdownSeconds] = useState<number | null>(null);
  const [pollRefreshCycle, setPollRefreshCycle] = useState(0);
  const [error, setError] = useState("");
  const [answerMode, setAnswerMode] = useState<"text" | "voice">(DEFAULT_INTERVIEW_MODE);
  const answerModeRef = useRef<"text" | "voice">(DEFAULT_INTERVIEW_MODE);
  const [showTranscript, setShowTranscript] = useState(false);
  // transcriptPending: STT finished but candidate hasn't confirmed yet (VOICE_AUTO_SEND=false)
  const [transcriptPending, setTranscriptPending] = useState(false);
  const [practicalTask, setPracticalTask] = useState<PracticalTask | null>(null);
  const [practicalModalOpen, setPracticalModalOpen] = useState(false);
  const [practicalAnswer, setPracticalAnswer] = useState("");
  const [practicalError, setPracticalError] = useState("");
  const [practicalSubmitting, setPracticalSubmitting] = useState(false);
  const [practicalStartTime, setPracticalStartTime] = useState<number | null>(null);
  const [latestTranscript, setLatestTranscript] = useState("");
  const [recordingUploadState, setRecordingUploadState] = useState<"idle" | "uploading" | "uploaded" | "failed" | "skipped">("idle");
  const [moduleSession, setModuleSession] = useState<InterviewModuleSession | null>(null);
  const [interviewStage, setInterviewStage] = useState<InterviewStage | null>(null);
  const [codingTaskDraft, setCodingTaskDraft] = useState("");
  const [codingTaskLanguage, setCodingTaskLanguage] = useState<string>("python");
  const [codingTaskSaveState, setCodingTaskSaveState] = useState<"idle" | "saving" | "saved" | "failed">("idle");
  const [codingTaskSavedAt, setCodingTaskSavedAt] = useState<string | null>(null);
  const [codingTaskDirty, setCodingTaskDirty] = useState(false);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const bottomRef = useRef<HTMLDivElement>(null);
  const autoRecordingAttemptedRef = useRef(false);

  // Behavioral signals tracking (Feature 7)
  const pasteCountRef = useRef(0);
  const tabSwitchCountRef = useRef(0);
  const questionStartTimeRef = useRef<number>(Date.now());
  const responseTimes = useRef<{ q: number; seconds: number }[]>([]);
  const currentQNumRef = useRef(1);
  const proctoringEventsRef = useRef<ProctoringEvent[]>([]);
  const faceAwayLoggedRef = useRef(false);
  const loggedLongSilenceCountRef = useRef(0);

  // Resume panel
  const [resumeText, setResumeText] = useState<string | null>(null);
  const [resumeOpen, setResumeOpen] = useState(false);
  const [cameraPanelOpen, setCameraPanelOpen] = useState(true);
  const reportGenerationFailedMessage = t("reportGenerationFailed");

  // Language is loaded from interview, default "ru" until loaded
  const [interviewLanguage, setInterviewLanguage] = useState<string>("ru");
  const { enabled: ttsEnabled, speaking, speak, stop, toggle: toggleTTS } = useTTS(interviewLanguage);
  const {
    isRecording,
    isScreenSharing,
    cameraPreviewReady,
    previewRef,
    startRecording,
    stopRecording,
    getBlob,
    clearRecording,
    getWebcamStream,
    errorMessage: recordingError,
    errorCode: recordingErrorCode,
  } = useMediaRecorder();
  const { faceAwayPct, isModelLoaded: faceModelLoaded } = useFaceDetection(previewRef, isRecording);
  const {
    speechActivityPct,
    silencePct,
    longSilenceCount,
    speechSegmentCount,
    isSpeechActive,
    isMonitoringSupported: speechMonitoringSupported,
  } = useSpeechActivity(getWebcamStream, isRecording);
  // Keep ref in sync with state so voice callback always has current value
  useEffect(() => { answerModeRef.current = answerMode; }, [answerMode]);

  const { state: voiceState, start: startVoice, stop: stopVoice, errorMessage: voiceError, clearError: clearVoiceError } = useVoiceInput({
    onTranscript: (text) => {
      setLatestTranscript(text);
      // In voice mode, replace input entirely (one answer per recording session)
      if (answerModeRef.current === "voice") {
        setInput(text);
      } else {
        setInput((prev) => (prev ? `${prev} ${text}` : text));
      }
    },
  });

  function trackProctoringEvent(event: ProctoringEvent) {
    const normalized: ProctoringEvent = {
      event_type: event.event_type,
      severity: event.severity ?? "info",
      occurred_at: event.occurred_at ?? new Date().toISOString(),
      source: event.source ?? "client",
      details: event.details ?? {},
    };
    proctoringEventsRef.current = [...proctoringEventsRef.current, normalized].slice(-200);
  }

  function getAssessmentHubPath(payload: AssessmentProgressLike | null | undefined): string | null {
    const progress = payload?.assessment_progress;
    if (!progress?.has_remaining_modules) {
      return null;
    }
    return `/employee/invite/${progress.invite_token}`;
  }

  const taskWorkspaceModuleType =
    moduleSession?.module_type === "coding_task" ||
    moduleSession?.module_type === "sql_live" ||
    moduleSession?.module_type === "written_communication"
      ? moduleSession.module_type
      : null;
  const isSqlLive = taskWorkspaceModuleType === "sql_live";
  const isWrittenCommunication = taskWorkspaceModuleType === "written_communication";
  const preferredTaskLanguage = isSqlLive ? moduleSession?.preferred_language ?? "sql" : moduleSession?.preferred_language ?? "python";

  async function saveCodingTaskDraftArtifact(force = false): Promise<boolean> {
    if (!id || !taskWorkspaceModuleType) {
      return true;
    }
    if (!codingTaskDraft.trim()) {
      setCodingTaskSaveState("idle");
      setCodingTaskSavedAt(null);
      setCodingTaskDirty(false);
      return true;
    }
    if (!force && !codingTaskDirty) {
      return true;
    }

    setCodingTaskSaveState("saving");
    try {
      if (isWrittenCommunication) {
        const saved = await interviewApi.saveWrittenArtifact(id, {
          content: codingTaskDraft,
        });
        setCodingTaskDraft(saved.content);
        setCodingTaskSavedAt(saved.updated_at ?? null);
      } else {
        const saved = await interviewApi.saveCodingTaskArtifact(id, {
          language: isSqlLive ? "sql" : codingTaskLanguage,
          code: codingTaskDraft,
        });
        setCodingTaskDraft(saved.code);
        setCodingTaskLanguage(saved.language ?? (isSqlLive ? "sql" : "python"));
        setCodingTaskSavedAt(saved.updated_at ?? null);
      }
      setCodingTaskDirty(false);
      setCodingTaskSaveState("saved");
      return true;
    } catch (err: unknown) {
      setCodingTaskSaveState("failed");
      setError(
        err instanceof Error
          ? err.message
          : isWrittenCommunication
          ? t("writtenWorkspace.saveFailed")
          : isSqlLive
          ? t("sqlWorkspace.saveFailed")
          : t("codingWorkspace.saveFailed"),
      );
      return false;
    }
  }

  // Load interview on mount
  useEffect(() => {
    if (!id || authLoading) return;
    interviewApi
      .getDetail(id)
      .then((data) => {
        setInterview(data);
        setMessages(data.messages.filter((m) => m.role !== "system" && m.role !== "practical_submission"));
        setQuestionCount(data.question_count);
        setMaxQuestions(data.max_questions);
        setModuleSession(data.module_session ?? null);
        setInterviewStage(data.interview_stage ?? null);
        if (data.module_session?.preferred_language) {
          setCodingTaskLanguage(data.module_session.preferred_language);
        }
        if (data.language) setInterviewLanguage(data.language);

        const hubPath = getAssessmentHubPath(data);
        if (hubPath && data.status !== "in_progress") {
          router.replace(hubPath);
          return;
        }

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
      .catch(() => setError(t("loadFailed")));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, authLoading]);

  useEffect(() => {
    if (!practicalModalOpen || practicalSubmitting) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setPracticalModalOpen(false);
        setPracticalError("");
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [practicalModalOpen, practicalSubmitting]);

  // Load resume text
  useEffect(() => {
    if (!id || authLoading) return;
    candidateApi.getResumeText().then((r) => setResumeText(r.raw_text)).catch(() => null);
  }, [id, authLoading]);

  useEffect(() => {
    if (!id || !taskWorkspaceModuleType) {
      setCodingTaskDraft("");
      setCodingTaskLanguage(preferredTaskLanguage);
      setCodingTaskSavedAt(null);
      setCodingTaskSaveState("idle");
      setCodingTaskDirty(false);
      return;
    }

    let cancelled = false;
    if (isWrittenCommunication) {
      interviewApi
        .getWrittenArtifact(id)
        .then((artifact) => {
          if (cancelled) return;
          setCodingTaskDraft(artifact.content ?? "");
          setCodingTaskSavedAt(artifact.updated_at ?? null);
          setCodingTaskSaveState(artifact.content ? "saved" : "idle");
          setCodingTaskDirty(false);
        })
        .catch(() => {
          if (cancelled) return;
          setCodingTaskDraft("");
          setCodingTaskLanguage(preferredTaskLanguage);
          setCodingTaskSavedAt(null);
          setCodingTaskSaveState("idle");
          setCodingTaskDirty(false);
        });
    } else {
      interviewApi
        .getCodingTaskArtifact(id)
        .then((artifact) => {
          if (cancelled) return;
          setCodingTaskDraft(artifact.code ?? "");
          setCodingTaskLanguage(artifact.language ?? preferredTaskLanguage);
          setCodingTaskSavedAt(artifact.updated_at ?? null);
          setCodingTaskSaveState(artifact.code ? "saved" : "idle");
          setCodingTaskDirty(false);
        })
        .catch(() => {
          if (cancelled) return;
          setCodingTaskDraft("");
          setCodingTaskLanguage(preferredTaskLanguage);
          setCodingTaskSavedAt(null);
          setCodingTaskSaveState("idle");
          setCodingTaskDirty(false);
        });
    }

    return () => {
      cancelled = true;
    };
  }, [id, isWrittenCommunication, preferredTaskLanguage, taskWorkspaceModuleType]);

  // Track behavioral signals
  useEffect(() => {
    function onVisibilityChange() {
      if (document.hidden) {
        tabSwitchCountRef.current++;
        trackProctoringEvent({
          event_type: "tab_switch",
          severity: PROCTORING_POLICY_MODE === "strict_flagging" ? "medium" : "info",
          details: { source: "visibilitychange" },
        });
      }
    }
    function onBlur() {
      tabSwitchCountRef.current++;
      trackProctoringEvent({
        event_type: "tab_switch",
        severity: PROCTORING_POLICY_MODE === "strict_flagging" ? "medium" : "info",
        details: { source: "window_blur" },
      });
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
  }, [messages, sending]);

  useEffect(() => {
    if (!interview || interview.status !== "in_progress") return;
    if (autoRecordingAttemptedRef.current) return;
    autoRecordingAttemptedRef.current = true;

    void startRecording().then((ok) => {
      if (ok) {
        trackProctoringEvent({
          event_type: "recording_started",
          severity: "info",
        });
      }
    });
  }, [interview, startRecording]);

  useEffect(() => {
    if (interview && interview.status !== "in_progress") {
      stopRecording();
    }
  }, [interview, stopRecording]);

  useEffect(() => {
    return () => {
      stopRecording();
      stop();
      stopVoice();
    };
  }, [stopRecording, stop, stopVoice]);

  useEffect(() => {
    if (!recordingError) return;
    const eventType =
      recordingErrorCode === "screen_share_stopped"
        ? "screen_share_stopped"
        : recordingErrorCode === "camera_stream_lost"
        ? "camera_stream_lost"
        : recordingErrorCode === "screen_permission_denied"
        ? "screen_permission_denied"
        : recordingErrorCode === "camera_permission_denied"
        ? "camera_permission_denied"
        : recordingErrorCode === "microphone_permission_denied"
        ? "microphone_permission_denied"
        : "recording_error";
    trackProctoringEvent({
      event_type: eventType,
      severity: PROCTORING_POLICY_MODE === "strict_flagging" ? "medium" : "info",
      details: { message: recordingError },
    });
  }, [recordingError, recordingErrorCode]);

  useEffect(() => {
    if (faceAwayPct === null) return;
    if (faceAwayPct > 0.35 && !faceAwayLoggedRef.current) {
      faceAwayLoggedRef.current = true;
      trackProctoringEvent({
        event_type: "face_away_high",
        severity: faceAwayPct >= 0.5 ? "high" : "medium",
        details: { face_away_pct: faceAwayPct },
      });
    }
    if (faceAwayPct <= 0.2) {
      faceAwayLoggedRef.current = false;
    }
  }, [faceAwayPct]);

  useEffect(() => {
    if (!isRecording) {
      loggedLongSilenceCountRef.current = 0;
    }
  }, [isRecording]);

  useEffect(() => {
    if (longSilenceCount <= loggedLongSilenceCountRef.current) return;
    loggedLongSilenceCountRef.current = longSilenceCount;
    trackProctoringEvent({
      event_type: "long_silence",
      severity:
        PROCTORING_POLICY_MODE === "strict_flagging" && longSilenceCount >= 2
          ? "medium"
          : "info",
      details: {
        count: longSilenceCount,
        silence_pct: silencePct,
      },
    });
  }, [longSilenceCount, silencePct]);

  function getReportFailureMessage(status: InterviewReportStatusResponse): string {
    const reason =
      status.failure_reason?.trim() ||
      status.diagnostics?.last_error?.trim() ||
      "";
    return reason || reportGenerationFailedMessage;
  }

  function getReportPhase(status: InterviewReportStatusResponse | null): "queued" | "assessing" | "retrying" | "finalizing" | "ready" | "failed" {
    if (!status) return "queued";
    if (status.processing_state === "ready") return "ready";
    if (status.processing_state === "failed") return "failed";

    const phase = (status.diagnostics?.last_phase || "").toLowerCase();
    if (phase === "manual_retry") return "retrying";
    if (phase.startsWith("async_worker_attempt_")) {
      return (status.diagnostics?.attempt_count ?? 0) > 1 ? "retrying" : "assessing";
    }
    if (phase === "report_saved" || phase === "status_poll" || phase === "async_existing_report") {
      return "finalizing";
    }
    if (phase === "assessing" || phase === "finish_sync") {
      return "assessing";
    }
    return "queued";
  }

  async function refreshReportSnapshot(interviewId: string): Promise<InterviewReportStatusResponse | null> {
    try {
      const [detail, status] = await Promise.all([
        interviewApi.getDetail(interviewId),
        interviewApi.getReportStatus(interviewId),
      ]);
      setInterview(detail);
      setModuleSession(detail.module_session ?? status.module_session ?? null);
      setInterviewStage(detail.interview_stage ?? status.interview_stage ?? null);
      setReportStatus(status);
      return status;
    } catch {
      return null;
    }
  }

  useEffect(() => {
    const nextRetryAtRaw = reportStatus?.diagnostics?.next_retry_at;
    if (!waitingForReport || !nextRetryAtRaw) {
      setRetryCountdownSeconds(null);
      return;
    }

    const nextRetryAtMs = Date.parse(nextRetryAtRaw);
    if (Number.isNaN(nextRetryAtMs)) {
      setRetryCountdownSeconds(null);
      return;
    }

    const tick = () => {
      const remaining = Math.max(0, Math.ceil((nextRetryAtMs - Date.now()) / 1000));
      setRetryCountdownSeconds(remaining);
    };
    tick();
    const timerId = window.setInterval(tick, 1000);
    return () => window.clearInterval(timerId);
  }, [waitingForReport, reportStatus?.diagnostics?.next_retry_at]);

  useEffect(() => {
    const startedAtMs = parseApiTimestamp(interview?.started_at);
    if (!interview || Number.isNaN(startedAtMs)) {
      setElapsedSeconds(0);
      return;
    }

    const completedAtMs = parseApiTimestamp(interview.completed_at);
    const tick = () => {
      const effectiveEnd = Number.isNaN(completedAtMs) ? Date.now() : completedAtMs;
      setElapsedSeconds(Math.max(0, Math.floor((effectiveEnd - startedAtMs) / 1000)));
    };

    tick();
    if (interview.status !== "in_progress" || !Number.isNaN(completedAtMs)) {
      return;
    }

    const timerId = window.setInterval(tick, 1000);
    return () => window.clearInterval(timerId);
  }, [interview]);

  async function waitForReport(interviewId: string): Promise<{ reportId: string | null; hubPath: string | null }> {
    let lastKnownFailure: string | null = null;
    for (let cycle = 0; cycle <= REPORT_SOFT_REFRESH_CYCLES; cycle += 1) {
      setPollRefreshCycle(cycle);
      const deadline = Date.now() + REPORT_POLL_TIMEOUT_MS;

      while (Date.now() < deadline) {
        try {
          const status = await interviewApi.getReportStatus(interviewId);
          setReportStatus(status);
          setModuleSession(status.module_session ?? null);
          setInterviewStage(status.interview_stage ?? null);
          const hubPath = getAssessmentHubPath(status);
          if (hubPath) {
            return { reportId: null, hubPath };
          }
          if (status.processing_state === "ready" && status.report_id) {
            return { reportId: status.report_id, hubPath: null };
          }
          if (status.processing_state === "failed") {
            throw new Error(getReportFailureMessage(status));
          }
          if (status.failure_reason?.trim()) lastKnownFailure = status.failure_reason.trim();
          if (status.diagnostics?.last_error?.trim()) {
            lastKnownFailure = status.diagnostics.last_error.trim();
          }
        } catch {
          // transient polling error, keep waiting until timeout
        }
        await new Promise((resolve) => setTimeout(resolve, REPORT_POLL_INTERVAL_MS));
      }

      const refreshed = await refreshReportSnapshot(interviewId);
      const hubPath = getAssessmentHubPath(refreshed);
      if (hubPath) {
        return { reportId: null, hubPath };
      }
      if (refreshed?.processing_state === "ready" && refreshed.report_id) {
        return { reportId: refreshed.report_id, hubPath: null };
      }
      if (refreshed?.processing_state === "failed") {
        throw new Error(getReportFailureMessage(refreshed));
      }
      if (cycle < REPORT_SOFT_REFRESH_CYCLES) {
        await new Promise((resolve) => setTimeout(resolve, REPORT_SOFT_REFRESH_DELAY_MS));
      }
    }
    if (lastKnownFailure) {
      throw new Error(lastKnownFailure);
    }
    throw new Error(t("reportDelayed"));
  }

  // Voice mode STT completion handling.
  // VOICE_AUTO_SEND=false (default): set transcriptPending=true so candidate can review.
  // VOICE_AUTO_SEND=true: fire handleSend immediately via ref (avoids stale closure).
  const handleSendRef = useRef<() => void>(() => {});
  const voiceAutoSendRef = useRef(false);

  // Keep handleSendRef pointing to the latest handleSend (updated every render)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { handleSendRef.current = () => { void handleSend(); }; });

  useEffect(() => {
    if (answerModeRef.current !== "voice") return;
    if (voiceState === "transcribing") {
      voiceAutoSendRef.current = true;
    }
    if (voiceState === "idle" && voiceAutoSendRef.current) {
      voiceAutoSendRef.current = false;
      if (VOICE_AUTO_SEND) {
        // Auto-send: small delay to let React flush the input state from the STT callback
        setTimeout(() => { if (answerModeRef.current === "voice") handleSendRef.current(); }, 50);
      } else {
        // Manual confirm: show the transcript preview and wait for the candidate to press Send
        setTranscriptPending(true);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [voiceState]);

  async function handlePracticalSubmit() {
    if (!practicalTask || !id || practicalSubmitting) return;
    if (!practicalAnswer.trim()) return;
    if (practicalTask.starter_code && practicalAnswer.trim() === practicalTask.starter_code.trim()) {
      setPracticalError("Добавьте собственное решение: boilerplate нельзя отправить без изменений.");
      return;
    }
    setPracticalSubmitting(true);
    setPracticalError("");
    setError("");
    try {
      const duration = practicalStartTime ? Math.round((Date.now() - practicalStartTime) / 1000) : null;
      const res = await interviewApi.submitPracticalTask(id, {
        task_id: practicalTask.task_id,
        task_type: practicalTask.task_type,
        answer: practicalAnswer,
        language: practicalTask.language,
        duration_seconds: duration,
      });
      setPracticalModalOpen(false);
      setPracticalTask(null);
      setPracticalAnswer("");
      setPracticalError("");
      setPracticalStartTime(null);
      setQuestionCount(res.question_count);
      setMaxQuestions(res.max_questions);
      setCurrentQuestion(res.current_question);
      setIsFollowup(res.is_followup ?? false);
      setQuestionType(res.question_type ?? "main");
      setModuleSession(res.module_session ?? null);
      setInterviewStage(res.interview_stage ?? null);
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
      setPracticalError(err instanceof Error ? err.message : "Ошибка отправки задания");
    } finally {
      setPracticalSubmitting(false);
    }
  }

  async function handleSend(overrideInput?: string) {
    const textToUse = overrideInput ?? input;
    if (!textToUse.trim() || sending || !id) return;
    const text = textToUse.trim();

    // Record response time for this question
    const elapsed = (Date.now() - questionStartTimeRef.current) / 1000;
    responseTimes.current.push({ q: currentQNumRef.current, seconds: Math.round(elapsed) });
    questionStartTimeRef.current = Date.now();

    setInput("");
    setLatestTranscript("");
    setTranscriptPending(false);
    setSending(true);
    setError("");
    stop();
    clearVoiceError();

    const optimistic: InterviewMessage = {
      role: "candidate",
      content: text,
      created_at: new Date().toISOString(),
    };
    if (!introPending) {
      setMessages((prev) => [...prev, optimistic]);
    }

    try {
      const res = await interviewApi.sendMessage(id, { message: text });
      setQuestionCount(res.question_count);
      setMaxQuestions(res.max_questions);
      setCurrentQuestion(res.current_question);
      setIsFollowup(res.is_followup ?? false);
      setQuestionType(res.question_type ?? "main");
      setModuleSession(res.module_session ?? null);
      setInterviewStage(res.interview_stage ?? null);

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
        // Practical task: open modal after AI speaks the intro
        if (res.question_delivery_type === "practical_task" && res.practical_task) {
          setPracticalTask(res.practical_task);
          setPracticalAnswer("");
          setPracticalStartTime(Date.now());
          // Delay opening modal until TTS finishes intro (2s safety buffer)
          setTimeout(() => setPracticalModalOpen(true), 2200);
        }
      } else {
        setCanFinish(true);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("sendFailed"));
      // The answer is persisted server-side even when generating the next
      // question fails, so do NOT drop the optimistic message (that made the
      // candidate's reply look deleted). Re-sync from the server instead: this
      // keeps the saved answer and picks up the next question if it was created.
      try {
        const data = await interviewApi.getDetail(id);
        setMessages(data.messages.filter((m) => m.role !== "system" && m.role !== "practical_submission"));
        setQuestionCount(data.question_count);
        setMaxQuestions(data.max_questions);
        const lastAssistant = [...data.messages]
          .reverse()
          .find((m) => m.role === "assistant");
        const lastMsg = data.messages[data.messages.length - 1];
        if (lastMsg?.role === "assistant" && lastAssistant) {
          setCurrentQuestion(lastAssistant.content);
        } else if (
          data.question_count >= data.max_questions &&
          lastMsg?.role === "candidate"
        ) {
          setCanFinish(true);
          setCurrentQuestion(null);
        }
      } catch {
        // If re-sync fails, keep the optimistic answer visible rather than
        // deleting it; the user can retry.
      }
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
    setReportStatus(null);
    setPollRefreshCycle(0);
    setError("");
    try {
      if (taskWorkspaceModuleType) {
        const artifactSaved = await saveCodingTaskDraftArtifact(true);
        if (!artifactSaved) {
          throw new Error(
            isWrittenCommunication
              ? t("writtenWorkspace.saveFailed")
              : isSqlLive
              ? t("sqlWorkspace.saveFailed")
              : t("codingWorkspace.saveFailed"),
          );
        }
      }
      let recordingNotice: string | null = null;
      // Ensure MediaRecorder has time to flush its last chunk.
      await new Promise((resolve) => setTimeout(resolve, 300));
      const recordingBlob = getBlob();
      if (recordingBlob && recordingBlob.size > 0) {
        setRecordingUploadState("uploading");
        try {
          await interviewApi.uploadRecording(id, recordingBlob);
          setRecordingUploadState("uploaded");
          trackProctoringEvent({
            event_type: "recording_uploaded",
            severity: "info",
          });
          clearRecording();
        } catch (uploadErr: unknown) {
          setRecordingUploadState("failed");
          setError(uploadErr instanceof Error ? uploadErr.message : t("recordingUploadFailed"));
          recordingNotice = "recording_failed";
          trackProctoringEvent({
            event_type: "recording_upload_failed",
            severity: PROCTORING_POLICY_MODE === "strict_flagging" ? "medium" : "info",
          });
        }
      } else {
        setRecordingUploadState("skipped");
        recordingNotice = "recording_skipped";
        trackProctoringEvent({
          event_type: "recording_skipped",
          severity: "info",
        });
      }
      // Submit behavioral signals before finishing
      await interviewApi.submitSignals(id, {
        response_times: responseTimes.current,
        paste_count: pasteCountRef.current,
        tab_switches: tabSwitchCountRef.current,
        face_away_pct: faceAwayPct,
        speech_activity_pct: speechActivityPct,
        silence_pct: silencePct,
        long_silence_count: longSilenceCount,
        speech_segment_count: speechSegmentCount,
        events: proctoringEventsRef.current,
        policy_mode: PROCTORING_POLICY_MODE,
      }).catch(() => null);

      const res = await interviewApi.finish(id);
      setModuleSession(res.module_session ?? null);
      setInterviewStage(res.interview_stage ?? null);
      const hubPath = getAssessmentHubPath(res);
      if (hubPath) {
        router.push(hubPath);
        return;
      }
      let reportId: string | null = null;
      if (res.status === "report_generated" && res.report_id) {
        reportId = res.report_id;
      } else {
        setWaitingForReport(true);
        const waitResult = await waitForReport(id);
        if (waitResult.hubPath) {
          router.push(waitResult.hubPath);
          return;
        }
        reportId = waitResult.reportId;
      }
      const suffix = recordingNotice ? `?notice=${recordingNotice}` : "";
      router.push(`/candidate/reports/${reportId}${suffix}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("finishFailed"));
    } finally {
      setWaitingForReport(false);
      setFinishing(false);
      setPollRefreshCycle(0);
    }
  }

  async function handleRetryReport() {
    if (!id || reportRetrying || finishing) return;
    setReportRetrying(true);
    setWaitingForReport(true);
    setReportStatus(null);
    setPollRefreshCycle(0);
    setError("");
    try {
      const retryStatus = await interviewApi.retryReport(id);
      setReportStatus(retryStatus);
      setModuleSession(retryStatus.module_session ?? null);
      setInterviewStage(retryStatus.interview_stage ?? null);
      const hubPath = getAssessmentHubPath(retryStatus);
      if (hubPath) {
        router.push(hubPath);
        return;
      }
      if (retryStatus.processing_state === "ready" && retryStatus.report_id) {
        router.push(`/candidate/reports/${retryStatus.report_id}`);
        return;
      }
      if (retryStatus.processing_state === "failed") {
        throw new Error(getReportFailureMessage(retryStatus));
      }
      const waitResult = await waitForReport(id);
      if (waitResult.hubPath) {
        router.push(waitResult.hubPath);
        return;
      }
      router.push(`/candidate/reports/${waitResult.reportId}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : reportGenerationFailedMessage);
    } finally {
      setWaitingForReport(false);
      setReportRetrying(false);
      setPollRefreshCycle(0);
    }
  }

  if (authLoading || !interview) {
    if (error) {
      return (
        <div className="min-h-screen bg-slate-900 flex items-center justify-center">
          <div className="text-red-400">{error}</div>
        </div>
      );
    }
    return (
      <div className="min-h-screen bg-slate-900 flex flex-col">
        <header className="border-b border-slate-800 px-6 py-4 flex items-center gap-4 shrink-0">
          <div className="h-4 w-4 bg-slate-700 rounded animate-pulse" />
          <div className="h-4 w-48 bg-slate-700 rounded animate-pulse" />
        </header>
        <div className="flex-1 px-4 py-6 max-w-2xl w-full mx-auto space-y-4">
          <div className="h-16 bg-slate-800 rounded-2xl animate-pulse" />
          <div className="h-10 bg-slate-800 rounded-2xl animate-pulse ml-auto w-3/4" />
          <div className="h-16 bg-slate-800 rounded-2xl animate-pulse" />
        </div>
      </div>
    );
  }

  const roleLabel = startT(`roles.${interview.target_role}.label`);
  const isIntroAssistantMessage = (content: string) => {
    const normalized = content.trim().toLowerCase();
    return (
      normalized.startsWith("здравствуйте! я ai hr-интервьюер") ||
      normalized.startsWith("hello! i’m your ai hr interviewer") ||
      normalized.startsWith("hello! i'm your ai hr interviewer")
    );
  };
  const assistantAskedCount = messages.filter((msg) => msg.role === "assistant" && !isIntroAssistantMessage(msg.content)).length;
  const candidateAnswerCount = messages.filter((msg) => msg.role === "candidate").length;
  const introPending = interview.status === "in_progress" && questionCount === 0;
  const visibleQuestionCount = Math.max(assistantAskedCount, questionCount);
  const visibleProgressPct = Math.round((visibleQuestionCount / Math.max(maxQuestions, 1)) * 100);
  const voiceMode = answerMode === "voice";
  // Derived voice status for UI indicators
  const voiceStatus: "ai_speaking" | "listening" | "processing" | "idle" =
    speaking ? "ai_speaking"
    : voiceState === "listening" ? "listening"
    : voiceState === "transcribing" || sending ? "processing"
    : "idle";
  const isVoiceError =
    voiceState === "error" ||
    voiceState === "microphone_error" ||
    voiceState === "silence_timeout";
  const practicalAnswerIsOnlyStarter =
    Boolean(practicalTask?.starter_code) &&
    practicalAnswer.trim() === practicalTask?.starter_code?.trim();
  const reportAttempts = reportStatus?.diagnostics?.attempt_count ?? 0;
  const reportMaxAttempts = reportStatus?.diagnostics?.max_attempts ?? 0;
  const reportLastError = reportStatus?.diagnostics?.last_error;
  const reportPhase = getReportPhase(reportStatus);
  const reportPhaseLabel = t(`reportPhase.${reportPhase}`);
  const reportPhaseToneClass =
    reportPhase === "ready"
      ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
      : reportPhase === "failed"
      ? "border-red-500/30 bg-red-500/10 text-red-300"
      : reportPhase === "retrying"
      ? "border-amber-500/30 bg-amber-500/10 text-amber-300"
      : "border-blue-500/30 bg-blue-500/10 text-blue-300";
  const uploadStatusLabel =
    recordingUploadState === "uploading"
      ? t("uploadStatus.uploading")
      : recordingUploadState === "uploaded"
      ? t("uploadStatus.uploaded")
      : recordingUploadState === "failed"
      ? t("uploadStatus.failed")
      : recordingUploadState === "skipped"
      ? t("uploadStatus.skipped")
      : null;
  const systemDesignSession = moduleSession?.module_type === "system_design" ? moduleSession : null;
  const behavioralInterviewSession = moduleSession?.module_type === "behavioral_interview" ? moduleSession : null;
  const codingTaskSession = moduleSession?.module_type === "coding_task" ? moduleSession : null;
  const sqlLiveSession = moduleSession?.module_type === "sql_live" ? moduleSession : null;
  const writtenCommunicationSession = moduleSession?.module_type === "written_communication" ? moduleSession : null;
  const taskWorkspaceSession = codingTaskSession || sqlLiveSession || writtenCommunicationSession;
  const overviewModuleSession = systemDesignSession || behavioralInterviewSession;
  const structuredInterviewStage = !overviewModuleSession && !taskWorkspaceSession ? interviewStage : null;
  const estimatedDuration = estimateInterviewDuration(maxQuestions);
  const structurePhaseLabel =
    structuredInterviewStage?.phase_key === "intro"
      ? t("structurePhases.intro")
      : structuredInterviewStage?.phase_key === "resume_followup"
      ? t("structurePhases.resume_followup")
      : structuredInterviewStage?.phase_key === "technical"
      ? t("structurePhases.technical")
      : structuredInterviewStage?.phase_key === "behavioral_closing"
      ? t("structurePhases.behavioral_closing")
      : structuredInterviewStage?.phase_title ?? null;
  const codingTaskSaveLabel =
    codingTaskSaveState === "saving"
      ? isWrittenCommunication
        ? t("writtenWorkspace.saving")
        : taskWorkspaceModuleType === "sql_live"
        ? t("sqlWorkspace.saving")
        : t("codingWorkspace.saving")
      : codingTaskSaveState === "saved"
      ? isWrittenCommunication
        ? t("writtenWorkspace.saved")
        : taskWorkspaceModuleType === "sql_live"
        ? t("sqlWorkspace.saved")
        : t("codingWorkspace.saved")
      : codingTaskSaveState === "failed"
      ? isWrittenCommunication
        ? t("writtenWorkspace.failed")
        : taskWorkspaceModuleType === "sql_live"
        ? t("sqlWorkspace.failed")
        : t("codingWorkspace.failed")
      : codingTaskDirty
      ? isWrittenCommunication
        ? t("writtenWorkspace.unsaved")
        : taskWorkspaceModuleType === "sql_live"
        ? t("sqlWorkspace.unsaved")
        : t("codingWorkspace.unsaved")
      : null;
  const codingTaskSavedAtLabel = codingTaskSavedAt
    ? new Date(codingTaskSavedAt).toLocaleTimeString()
    : null;
  const elapsedLabel = formatElapsedDuration(elapsedSeconds);
  const currentQuestionLabel = introPending
    ? t("introPending")
    : t("question", {
        current: Math.min(Math.max(visibleQuestionCount, 1), Math.max(maxQuestions, 1)),
        total: Math.max(maxQuestions, 1),
      });
  const askedInChatLabel = t("askedInChat", { count: assistantAskedCount });
  const answeredInChatLabel = t("answeredInChat", { count: candidateAnswerCount });
  const stageDisplayTitle =
    structurePhaseLabel ||
    (overviewModuleSession || taskWorkspaceSession)?.stage_title ||
    t("stageLabel");
  const structuredPhaseOrder = ["intro", "resume_followup", "technical", "behavioral_closing"];
  const structuredPhaseIndex = structuredInterviewStage
    ? structuredPhaseOrder.indexOf(structuredInterviewStage.phase_key)
    : -1;
  const structuredPhaseProgressCurrent =
    structuredPhaseIndex >= 0 ? structuredPhaseIndex + 1 : 1;
  const structuredPhaseProgressTotal = structuredPhaseOrder.length;
  const stageRailItems: StageRailItem[] =
    structuredPhaseIndex >= 0
      ? structuredPhaseOrder.map((phaseKey, index) => ({
          key: phaseKey,
          label: t(`structurePhases.${phaseKey}`),
          state:
            index < structuredPhaseIndex
              ? "done"
              : index === structuredPhaseIndex
              ? "current"
              : "upcoming",
        }))
      : [];
  const interviewStatusToneClass =
    interview.status === "in_progress"
      ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
      : interview.status === "report_generated"
      ? "border-blue-500/30 bg-blue-500/10 text-blue-300"
      : "border-slate-700 bg-slate-800/80 text-slate-300";
  const currentQuestionTypeLabel =
    questionType === "verification" || questionType === "claim_verification"
      ? t("verification")
      : questionType === "deep_technical"
      ? t("deepDive")
      : questionType === "clarification"
      ? t("clarification")
      : questionType === "structured_reframe"
      ? t("structuredReframe")
      : isFollowup
      ? t("followup")
      : t("mainQuestion");
  const faceAwayValue = faceAwayPct != null ? `${Math.round(faceAwayPct * 100)}%` : "—";
  const speechActivityValue = speechActivityPct != null ? `${Math.round(speechActivityPct * 100)}%` : "—";
  const silenceValue = silencePct != null ? `${Math.round(silencePct * 100)}%` : "—";
  const localizedRecordingError =
    recordingError === "Camera or microphone permission denied. Interview will continue without recording."
      ? t("recordingErrors.cameraOrMicPermissionDenied")
      : recordingError === "Camera permission denied. Interview will continue without recording."
      ? t("recordingErrors.cameraPermissionDenied")
      : recordingError === "Microphone permission denied. Interview will continue without recording."
      ? t("recordingErrors.microphonePermissionDenied")
      : recordingError === "Screen permission denied. Interview will continue without recording."
      ? t("recordingErrors.screenPermissionDenied")
      : recordingError === "Screen, camera, or microphone permission denied. Interview will continue without recording."
      ? t("recordingErrors.combinedPermissionDenied")
      : recordingError === "Camera preview could not start automatically."
      ? t("recordingErrors.previewStartFailed")
      : recordingError === "Camera stream is unavailable."
      ? t("recordingErrors.cameraStreamUnavailable")
      : recordingError === "Microphone stream is unavailable."
      ? t("recordingErrors.microphoneStreamUnavailable")
      : recordingError === "Screen capture stream is unavailable."
      ? t("recordingErrors.screenStreamUnavailable")
      : recordingError === "Screen sharing was stopped. Recording ended."
      ? t("recordingErrors.screenShareStopped")
      : recordingError === "Camera stream was stopped. Recording ended."
      ? t("recordingErrors.cameraStreamLost")
      : recordingError;

  return (
    <div className="interview-cockpit-light min-h-screen flex flex-col">
      <header className="border-b border-slate-900 bg-slate-950/90 backdrop-blur sticky top-0 z-30">
        <div className="mx-auto max-w-[1600px] px-4 py-3 sm:px-6 flex flex-col gap-3">
          <div className="flex items-center justify-between gap-4">
            {/* Back button and title */}
            <div className="flex min-w-0 items-center gap-3">
              <Link href="/candidate/reports" className="text-slate-500 transition-colors hover:text-slate-300 text-lg">
                ←
              </Link>
              <div className="min-w-0">
                <h1 className="truncate text-base md:text-lg font-bold text-white tracking-tight">
                  {t("interviewTitle", { role: roleLabel })}
                </h1>
              </div>
            </div>

            {/* Controls */}
            <div className="flex items-center gap-3 shrink-0">
              <button
                type="button"
                onClick={() => setCameraPanelOpen((prev) => !prev)}
                className="rounded-xl border border-slate-800 bg-slate-900/50 px-3 py-1.5 text-xs font-medium text-slate-300 hover:text-white hover:bg-slate-900 transition-all flex items-center gap-1.5"
              >
                <span>📷</span>
                <span className="hidden sm:inline">
                  {cameraPanelOpen
                    ? (interviewLanguage === "ru" ? "Скрыть камеру" : "Hide Camera")
                    : (interviewLanguage === "ru" ? "Показать камеру" : "Show Camera")
                  }
                </span>
              </button>
              <LocaleSwitcher />
            </div>
          </div>

          {/* Horizontal Chips Row */}
          <div className="flex flex-wrap items-center gap-2 pt-1.5 border-t border-slate-905">
            {/* Timer */}
            <span className="inline-flex items-center gap-1.5 rounded-full border border-blue-500/20 bg-blue-500/10 px-2.5 py-0.5 text-xs font-medium text-blue-200">
              ⏱ {elapsedLabel}
            </span>

            {/* Voice Status Chip */}
            <button
              type="button"
              onClick={toggleTTS}
              className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium transition-all ${
                ttsEnabled
                  ? "border-blue-500/30 bg-blue-500/15 text-blue-200 hover:bg-blue-500/25"
                  : "border-slate-800 bg-slate-900/40 text-slate-400 hover:text-slate-200 hover:bg-slate-900/60"
              }`}
            >
              <span>🎙️</span>
              <span>{ttsEnabled ? (interviewLanguage === "ru" ? "Голос включён" : "Voice enabled") : (interviewLanguage === "ru" ? "Голос выключен" : "Voice disabled")}</span>
            </button>

            {/* Stage Progress */}
            {structuredInterviewStage ? (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2.5 py-0.5 text-xs font-medium text-emerald-200">
                📌 {stageDisplayTitle} ({structuredPhaseProgressCurrent}/{structuredPhaseProgressTotal})
              </span>
            ) : (overviewModuleSession || taskWorkspaceSession) ? (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-blue-500/20 bg-blue-500/10 px-2.5 py-0.5 text-xs font-medium text-blue-200">
                📌 {stageDisplayTitle} ({((overviewModuleSession || taskWorkspaceSession)?.stage_index ?? 0) + 1}/{Math.max((overviewModuleSession || taskWorkspaceSession)?.stage_count ?? 0, 1)})
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-800 bg-slate-900/80 px-2.5 py-0.5 text-xs font-medium text-slate-300">
                📌 {stageDisplayTitle}
              </span>
            )}

            {/* Question Progress */}
            <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-800 bg-slate-900/80 px-2.5 py-0.5 text-xs font-medium text-slate-300">
              ❓ {currentQuestionLabel}
            </span>

            {/* Answer count */}
            <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-800 bg-slate-900/80 px-2.5 py-0.5 text-xs font-medium text-slate-300">
              💬 {answeredInChatLabel}
            </span>

            {/* Estimate */}
            <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-800 bg-slate-900/80 px-2.5 py-0.5 text-xs font-medium text-slate-300">
              ⏳ {t("structureEstimatedDuration", estimatedDuration)}
            </span>

            {/* Status */}
            <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${interviewStatusToneClass}`}>
              {interview.status === "in_progress" ? t("statusInProgress") : reportPhaseLabel}
            </span>
          </div>
        </div>
      </header>

      <main className="mx-auto flex w-full max-w-[1600px] flex-1 flex-col xl:flex-row gap-6 p-4 md:p-6 min-h-0">
        {/* Left Sidebar */}
        <aside className="w-full xl:w-72 shrink-0 flex flex-col gap-6 overflow-y-auto pr-1">
          {/* Role card */}
          <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
            <div className="text-[10px] font-bold uppercase tracking-[0.24em] text-cyan-400">
              {t("candidateCardEyebrow")}
            </div>
            <h2 className="mt-1.5 text-base font-bold text-white leading-tight">
              {roleLabel}
            </h2>
            {isFollowup && (
              <span className="mt-2 inline-block rounded border border-purple-500/20 bg-purple-500/5 px-1.5 py-0.5 text-[10px] text-purple-300 font-medium">
                {currentQuestionTypeLabel}
              </span>
            )}
            {resumeText && (
              <button
                onClick={() => setResumeOpen((value) => !value)}
                className={`mt-3 w-full rounded-xl border px-3 py-1.5 text-[11px] font-semibold transition-all flex items-center justify-center gap-1.5 ${
                  resumeOpen
                    ? "border-purple-500/30 bg-purple-500/10 text-purple-300 shadow-[0_0_8px_rgba(147,51,234,0.15)]"
                    : "border-slate-800 bg-slate-950/60 text-slate-400 hover:border-slate-700 hover:text-slate-200"
                }`}
              >
                <span>📄</span>
                <span>{resumeOpen ? (interviewLanguage === "ru" ? "Скрыть резюме" : "Hide Resume") : t("resume")}</span>
              </button>
            )}
          </div>

          {/* Stage/Progress (Vertical Stepper) */}
          <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4 space-y-4">
            <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-400">
              {interviewLanguage === "ru" ? "Этапы прохождения" : "Interview Stages"}
            </div>

            {stageRailItems.length > 0 ? (
              <VerticalStepper items={stageRailItems} />
            ) : (
              <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
                <div className="text-xs uppercase tracking-[0.16em] text-slate-500">
                  {t("stageLabel")}
                </div>
                <div className="mt-1 text-sm font-semibold text-white">
                  {stageDisplayTitle}
                </div>
                {(overviewModuleSession || taskWorkspaceSession)?.scenario_title && (
                  <div className="mt-3 border-t border-slate-900 pt-2">
                    <div className="text-xs uppercase tracking-[0.16em] text-slate-500">
                      {taskWorkspaceSession ? t("taskLabel") : t("scenarioLabel")}
                    </div>
                    <div className="mt-1 text-xs text-slate-300">
                      {(overviewModuleSession || taskWorkspaceSession)?.scenario_title}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Competencies */}
          {structuredInterviewStage?.competency_targets.length ? (
            <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4 space-y-3">
              <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-400">
                {t("structureCompetencies")}
              </div>
              <div className="flex flex-wrap gap-1.5">
                {structuredInterviewStage.competency_targets.map((competency) => (
                  <span
                    key={competency}
                    className="rounded-full border border-cyan-500/20 bg-cyan-500/10 px-2.5 py-0.5 text-xs text-cyan-100"
                  >
                    {competency}
                  </span>
                ))}
              </div>
            </div>
          ) : null}

          {/* Actions */}
          <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4 space-y-3">
            <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-400">
              {interviewLanguage === "ru" ? "Управление" : "Controls"}
            </div>

            <div className="flex flex-col gap-2">
              {!isRecording && interview.status === "in_progress" && (
                <button
                  onClick={() => void startRecording()}
                  className="w-full rounded-xl border border-yellow-500/30 bg-yellow-500/10 px-3 py-2.5 text-xs font-semibold text-yellow-200 hover:bg-yellow-500/20 transition-all flex items-center justify-center gap-2"
                >
                  <span>🔴</span>
                  <span>{t("enableRecording")}</span>
                </button>
              )}
            </div>

            {(localizedRecordingError || (voiceError && !isVoiceError) || (!isRecording && interview.status === "in_progress")) && (
              <div className="space-y-2 pt-2 border-t border-slate-900">
                {!isRecording && interview.status === "in_progress" && (
                  <div className="rounded-xl border border-yellow-500/25 bg-yellow-500/5 px-3 py-2 text-xs text-yellow-200">
                    {t("recordingRequired")}
                  </div>
                )}
                {localizedRecordingError && (
                  <div className="rounded-xl border border-yellow-500/25 bg-yellow-500/5 px-3 py-2 text-xs text-yellow-200">
                    {localizedRecordingError}
                  </div>
                )}
                {voiceError && !isVoiceError && (
                  <div className="rounded-xl border border-red-500/25 bg-red-500/5 px-3 py-2 text-xs text-red-200">
                    {voiceError}
                  </div>
                )}
              </div>
            )}
          </div>

          {resumeOpen && resumeText && (
            <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4 shadow-lg">
              <div className="flex items-center justify-between gap-3 mb-2">
                <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-400">{t("resume")}</div>
                <button
                  onClick={() => setResumeOpen(false)}
                  className="text-slate-400 hover:text-white text-xs"
                >
                  ×
                </button>
              </div>
              <pre className="max-h-56 overflow-y-auto whitespace-pre-wrap rounded-xl border border-slate-800 bg-slate-950/70 p-3 text-xs leading-5 text-slate-300">
                {resumeText}
              </pre>
            </div>
          )}
        </aside>

        {/* Center Cockpit */}
        <section className="flex-1 min-w-0 flex flex-col items-center gap-6">
          {error && !canFinish && (
            <div className="w-full max-w-[800px] rounded-xl border border-red-500/20 bg-red-500/5 px-4 py-3 text-sm text-red-200 shadow-md">
              {error}
            </div>
          )}

          {/* Question / Welcome Card */}
          <div className="w-full max-w-[800px] rounded-2xl border border-slate-800/80 bg-slate-900/60 p-5 md:p-6 shadow-xl space-y-4">
            {/* Header info */}
            <div className="flex items-center justify-between gap-3 border-b border-slate-800/60 pb-3">
              <span className="text-[10px] font-bold uppercase tracking-[0.2em] text-cyan-400">
                {stageDisplayTitle}
              </span>
              <span className="text-[10px] font-semibold text-slate-400">
                {currentQuestionLabel}
              </span>
            </div>

            {/* Main text content */}
            <div className="min-h-[100px] flex items-center">
              {introPending ? (
                <div className="space-y-2 w-full">
                  <h3 className="text-lg font-bold text-white">
                    {interviewLanguage === "ru" ? "Добро пожаловать на интервью!" : "Welcome to the interview!"}
                  </h3>
                  <p className="text-sm text-slate-300 leading-relaxed">
                    {interviewLanguage === "ru"
                      ? "Интервью проходит в автоматическом формате с участием AI-интервьюера. ИИ будет задавать вам вопросы, а ваши ответы будут анализироваться."
                      : "The interview is conducted in an automated format with an AI interviewer. The AI will ask you questions and analyze your answers."}
                  </p>
                </div>
              ) : (
                <p className="text-base font-medium text-white leading-relaxed whitespace-pre-wrap">
                  {currentQuestion || t("introPending")}
                </p>
              )}
            </div>

            {/* Mini Controls (Replay Voice) */}
            {!introPending && currentQuestion && ttsEnabled && (
              <div className="flex justify-end pt-2 border-t border-slate-800/60">
                <button
                  type="button"
                  onClick={() => speak(currentQuestion, interviewLanguage)}
                  disabled={speaking}
                  className="rounded-full border border-blue-500/30 bg-slate-950/60 px-3.5 py-1.5 text-xs text-blue-300 hover:bg-blue-500/20 disabled:opacity-40 transition-all flex items-center gap-1.5"
                >
                  <span>{speaking ? "■" : "▶"}</span>
                  <span>{speaking ? (interviewLanguage === "ru" ? "Говорит..." : "AI speaking...") : (interviewLanguage === "ru" ? "Повторить вопрос" : "Replay Question")}</span>
                </button>
              </div>
            )}
          </div>

          {practicalTask && !practicalModalOpen && !canFinish && (
            <div className="w-full max-w-[800px] rounded-2xl border border-amber-500/25 bg-amber-500/10 p-4 shadow-xl">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <div className="text-xs font-semibold uppercase tracking-[0.18em] text-amber-300">Практическое задание</div>
                  <div className="mt-1 text-sm font-semibold text-white">{practicalTask.title}</div>
                  <p className="mt-1 text-xs text-slate-400">
                    Черновик сохранён локально. Откройте задание и отправьте решение, чтобы продолжить интервью.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setPracticalModalOpen(true)}
                  className="rounded-xl bg-amber-600 px-5 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-amber-500"
                >
                  Открыть задание
                </button>
              </div>
            </div>
          )}

          {/* Transcript Review Card (Immediately below Question Card) */}
          {transcriptPending && input.trim() && !sending && (
            <div className="w-full max-w-[800px] rounded-2xl border border-slate-800 bg-slate-900/60 p-4 shadow-xl space-y-3">
              <div className="rounded-xl border border-slate-805 bg-slate-950 p-3">
                <label className="text-[10px] uppercase font-bold tracking-wider text-slate-500 block mb-1">
                  {interviewLanguage === "ru" ? "Проверка распознавания (можно отредактировать)" : "Review Text (editable)"}
                </label>
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  className="w-full rounded-lg border border-slate-805 bg-slate-950 p-2.5 text-sm text-white focus:outline-none focus:ring-1 focus:ring-blue-500 resize-y font-medium leading-relaxed"
                  rows={3}
                />
              </div>
              <div className="flex flex-col sm:flex-row items-center gap-3">
                <button
                  type="button"
                  onClick={() => {
                    setInput("");
                    setLatestTranscript("");
                    setTranscriptPending(false);
                    void startVoice();
                  }}
                  className="w-full sm:flex-1 rounded-xl border border-slate-805 bg-slate-950 hover:bg-slate-900 py-2.5 text-xs font-semibold text-slate-300 hover:text-white transition-all flex items-center justify-center gap-1.5"
                >
                  ↺ {interviewLanguage === "ru" ? "Перезаписать" : "Re-record"}
                </button>
                <button
                  type="button"
                  onClick={() => void handleSend()}
                  disabled={sending}
                  className="w-full sm:flex-1 rounded-xl bg-blue-600 hover:bg-blue-500 py-2.5 text-xs font-semibold text-white transition-all shadow-md shadow-blue-900/20 flex items-center justify-center gap-1.5"
                >
                  ✓ {interviewLanguage === "ru" ? "Подтвердить и отправить" : "Confirm & Send"}
                </button>
              </div>
            </div>
          )}

          {/* Interactive Workspace Session in Cockpit */}
          {!canFinish && (overviewModuleSession || taskWorkspaceSession) && (
            <div className="w-full max-w-[800px] rounded-2xl border border-blue-500/25 bg-blue-500/5 p-5 space-y-4 shadow-xl">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-blue-500/15 pb-3">
                <div className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-300">
                  {(overviewModuleSession || taskWorkspaceSession)?.module_title || t("moduleCardEyebrow")}
                </div>
                <div className="rounded-full border border-blue-500/20 bg-slate-900/50 px-3 py-1 text-xs text-slate-200">
                  {t("stageProgress", {
                    current: ((overviewModuleSession || taskWorkspaceSession)?.stage_index ?? 0) + 1,
                    total: Math.max((overviewModuleSession || taskWorkspaceSession)?.stage_count ?? 0, 1),
                  })}
                </div>
              </div>
              {(overviewModuleSession || taskWorkspaceSession)?.scenario_title && (
                <div>
                  <div className="text-xs uppercase tracking-[0.14em] text-slate-400">
                    {taskWorkspaceSession ? t("taskLabel") : t("scenarioLabel")}
                  </div>
                  <div className="mt-1 text-sm font-semibold text-white">
                    {(overviewModuleSession || taskWorkspaceSession)?.scenario_title}
                  </div>
                </div>
              )}
              {(overviewModuleSession || taskWorkspaceSession)?.scenario_prompt && (
                <p className="text-sm leading-relaxed text-slate-300">
                  {(overviewModuleSession || taskWorkspaceSession)?.scenario_prompt}
                </p>
              )}
              {taskWorkspaceSession && (
                <div className="space-y-4 pt-3 border-t border-blue-500/15">
                  <div className="rounded-xl border border-slate-800 bg-slate-950/40 px-4 py-3 text-xs text-slate-400 leading-relaxed">
                    {taskWorkspaceSession.workspace_hint || (isWrittenCommunication ? t("writtenTaskHint") : isSqlLive ? t("sqlTaskHint") : t("codingTaskHint"))}
                  </div>
                  <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4 space-y-3">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
                          {isWrittenCommunication ? t("writtenWorkspace.title") : isSqlLive ? t("sqlWorkspace.title") : t("codingWorkspace.title")}
                        </div>
                        <p className="text-xs text-slate-400 mt-1">
                          {isWrittenCommunication ? t("writtenWorkspace.description") : isSqlLive ? t("sqlWorkspace.description") : t("codingWorkspace.description")}
                        </p>
                      </div>
                      {codingTaskSaveLabel && (
                        <div className="text-xs text-slate-400">
                          <span>{codingTaskSaveLabel}</span>
                          {codingTaskSavedAtLabel && codingTaskSaveState === "saved" && (
                            <span>{` · ${codingTaskSavedAtLabel}`}</span>
                          )}
                        </div>
                      )}
                    </div>

                    <div className="flex flex-wrap items-center gap-3">
                      {!isSqlLive && !isWrittenCommunication && (
                        <>
                          <label className="text-xs uppercase tracking-[0.14em] text-slate-500">
                            {t("codingWorkspace.language")}
                          </label>
                          <select
                            value={codingTaskLanguage}
                            onChange={(e) => {
                              setCodingTaskLanguage(e.target.value);
                              setCodingTaskDirty(true);
                              setCodingTaskSaveState("idle");
                            }}
                            className="rounded-lg border border-slate-800 bg-slate-900 px-2.5 py-1.5 text-xs text-white focus:outline-none focus:ring-1 focus:ring-blue-500"
                          >
                            {CODING_TASK_LANGUAGES.map((language) => (
                              <option key={language} value={language}>
                                {language}
                              </option>
                            ))}
                          </select>
                        </>
                      )}
                      {isWrittenCommunication && (
                        <span className="rounded-full border border-slate-800 bg-slate-900 px-3 py-1.5 text-xs uppercase tracking-[0.16em] text-slate-300">
                          {t("writtenWorkspace.mode")}
                        </span>
                      )}
                      {isSqlLive && (
                        <span className="rounded-full border border-slate-800 bg-slate-900 px-3 py-1.5 text-xs uppercase tracking-[0.16em] text-slate-300">
                          SQL
                        </span>
                      )}
                      {!isSqlLive && !isWrittenCommunication && taskWorkspaceSession.preferred_language && (
                        <span className="rounded-full border border-slate-800 bg-slate-900 px-3 py-1.5 text-xs uppercase tracking-[0.16em] text-slate-405">
                          {t("recommendedLanguage")}: {taskWorkspaceSession.preferred_language}
                        </span>
                      )}
                      <button
                        type="button"
                        onClick={() => void saveCodingTaskDraftArtifact(true)}
                        disabled={!codingTaskDraft.trim() || codingTaskSaveState === "saving"}
                        className="rounded-lg border border-blue-500/30 bg-blue-500/10 px-3 py-1.5 text-xs font-semibold text-blue-300 hover:bg-blue-500/20 transition-all disabled:opacity-40"
                      >
                        {codingTaskSaveState === "saving"
                          ? (isWrittenCommunication ? t("writtenWorkspace.saving") : isSqlLive ? t("sqlWorkspace.saving") : t("codingWorkspace.saving"))
                          : (isWrittenCommunication ? t("writtenWorkspace.save") : isSqlLive ? t("sqlWorkspace.save") : t("codingWorkspace.save"))}
                      </button>
                    </div>

                    <textarea
                      value={codingTaskDraft}
                      onChange={(e) => {
                        setCodingTaskDraft(e.target.value);
                        setCodingTaskDirty(true);
                        setCodingTaskSaveState("idle");
                      }}
                      onPaste={() => {
                        pasteCountRef.current++;
                        trackProctoringEvent({
                          event_type: "paste_detected",
                          severity: PROCTORING_POLICY_MODE === "strict_flagging" ? "medium" : "info",
                          details: { count: pasteCountRef.current, source: isWrittenCommunication ? "written_workspace" : "coding_workspace" },
                        });
                      }}
                      placeholder={isWrittenCommunication ? t("writtenWorkspace.placeholder") : isSqlLive ? t("sqlWorkspace.placeholder") : t("codingWorkspace.placeholder")}
                      rows={12}
                      className={`w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm leading-6 text-white placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-blue-500 ${
                        isWrittenCommunication ? "font-sans" : "font-mono"
                      }`}
                    />
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Center Action Panel */}
          <div className="w-full max-w-[800px] flex flex-col gap-4">
            {/* 1. Intro pending / Start screen */}
            {introPending && (
              <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5 shadow-xl text-center space-y-4">
                <div className="text-xs text-slate-400 leading-relaxed">
                  {voiceMode
                    ? (interviewLanguage === "ru" ? "Вы находитесь в голосовом режиме. Нажмите кнопку ниже и произнесите «Готов» или нажмите кнопку, чтобы начать интервью." : "You are in voice-first mode. Click the button below and say 'Ready', or click to start.")
                    : (interviewLanguage === "ru" ? "Вы находитесь в текстовом режиме. Нажмите кнопку ниже, чтобы начать интервью." : "You are in text mode. Click the button below to start.")
                  }
                </div>

                <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
                  {/* If in voice mode, let them also start with Voice input */}
                  {voiceMode && (
                    <button
                      type="button"
                      onMouseDown={() => { setInput(""); setTranscriptPending(false); void startVoice(); }}
                      onMouseUp={stopVoice}
                      onTouchStart={() => { setInput(""); setTranscriptPending(false); void startVoice(); }}
                      onTouchEnd={stopVoice}
                      className={`rounded-xl border px-5 py-3 text-sm font-semibold transition-all ${
                        voiceState === "listening"
                          ? "animate-pulse border-red-500 bg-red-500/20 text-red-300 shadow-[0_0_20px_rgba(239,68,68,0.3)]"
                          : "border-slate-700 bg-slate-800 text-slate-200 hover:bg-slate-700"
                      }`}
                    >
                      {voiceState === "listening" ? "🎤 Слушаю..." : "🎙 Сказать «Готов»"}
                    </button>
                  )}

                  <button
                    type="button"
                    onClick={() => {
                      void handleSend(interviewLanguage === "ru" ? "Готов" : "Ready");
                    }}
                    className="rounded-xl bg-emerald-600 hover:bg-emerald-500 px-8 py-3 text-sm font-bold text-white transition-all shadow-lg shadow-emerald-950/20 hover:scale-[1.02] active:scale-[0.98]"
                  >
                    {interviewLanguage === "ru" ? "Начать интервью" : "Start Interview"}
                  </button>
                </div>
              </div>
            )}

            {/* 2. Finished screen */}
            {canFinish && (
              <div className="rounded-2xl border border-blue-500/20 bg-blue-500/5 p-6 text-center space-y-4 shadow-xl">
                <div className="text-white font-bold text-lg">{t("completeTitle")}</div>
                <div className="text-sm text-slate-300">
                  {t("completeDescription", {
                    answeredCount: candidateAnswerCount,
                    askedCount: assistantAskedCount,
                  })}
                </div>
                {uploadStatusLabel && (
                  <div className={`text-sm ${recordingUploadState === "failed" ? "text-red-300" : "text-slate-200"}`}>
                    {uploadStatusLabel}
                  </div>
                )}
                <button
                  onClick={handleFinish}
                  disabled={finishing || reportRetrying}
                  className="rounded-xl bg-blue-600 px-8 py-3 font-semibold text-white transition-colors hover:bg-blue-500 disabled:opacity-50"
                >
                  {finishing ? (waitingForReport ? t("waiting") : t("generating")) : t("finish")}
                </button>
              </div>
            )}

            {/* 3. Active Interview Controls */}
            {!canFinish && interview.status === "in_progress" && !introPending && !practicalTask && (
              <>
                {/* A. VOICE MODE COCKPIT CONTROLS */}
                {voiceMode && !showTranscript && (
                  <div className="w-full max-w-[800px] rounded-2xl border border-slate-800 bg-slate-900/60 p-4 shadow-xl space-y-3">
                    {/* Dynamic Status / Action Row */}
                    <div className="flex flex-col sm:flex-row items-center justify-between gap-4 px-2 py-1">
                      {/* Visual Status Indicator */}
                      <div className="flex items-center gap-3">
                        <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full transition-all duration-300 ${
                          voiceStatus === "ai_speaking" ? "bg-blue-500/20 shadow-[0_0_16px_rgba(59,130,246,0.25)]"
                          : voiceStatus === "listening" ? "animate-pulse bg-red-500/20 shadow-[0_0_16px_rgba(239,68,68,0.25)]"
                          : voiceStatus === "processing" ? "bg-amber-500/20 shadow-[0_0_16px_rgba(245,158,11,0.2)]"
                          : "bg-slate-800"
                        }`}>
                          <span className="text-base">
                            {voiceStatus === "ai_speaking" ? "🔊" : voiceStatus === "listening" ? "🎤" : voiceStatus === "processing" ? "⏳" : "🎙"}
                          </span>
                        </div>
                        <div className="text-left">
                          <span className="text-xs font-semibold text-slate-300 block">
                            {voiceStatus === "ai_speaking" ? (interviewLanguage === "ru" ? "AI озвучивает вопрос" : "AI speaking...")
                              : voiceStatus === "listening" ? (interviewLanguage === "ru" ? "Запись ответа..." : "Recording answer...")
                              : voiceStatus === "processing" ? (interviewLanguage === "ru" ? "Распознаем речь..." : "Transcribing speech...")
                              : (interviewLanguage === "ru" ? "Готов к ответу" : "Ready to answer")}
                          </span>
                          <span className="text-[10px] text-slate-500">
                            {voiceStatus === "listening" ? (interviewLanguage === "ru" ? "Говорите в микрофон" : "Speak into your mic") : ""}
                          </span>
                        </div>
                      </div>

                      {/* Primary Action Panel */}
                      <div className="flex items-center gap-2">
                        {/* AI Speaking Mode */}
                        {speaking && (
                          <button
                            type="button"
                            onClick={stop}
                            className="rounded-xl border border-slate-700 bg-slate-800 px-4 py-2 text-xs font-semibold text-slate-300 hover:text-white transition-colors"
                          >
                            {interviewLanguage === "ru" ? "Пропустить" : "Skip"}
                          </button>
                        )}

                        {/* Ready to Answer Mode (Idle) */}
                        {voiceStatus === "idle" && !isVoiceError && !transcriptPending && !speaking && (
                          <button
                            type="button"
                            onClick={() => {
                              setInput("");
                              setTranscriptPending(false);
                              void startVoice();
                            }}
                            className="rounded-xl bg-emerald-600 hover:bg-emerald-500 px-6 py-2.5 text-xs font-bold text-white transition-all shadow-md shadow-emerald-900/20 hover:scale-[1.01] active:scale-[0.99] flex items-center gap-1.5"
                          >
                            <span className="relative flex h-1.5 w-1.5">
                              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-450 opacity-75"></span>
                              <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-500"></span>
                            </span>
                            <span>{interviewLanguage === "ru" ? "Начать ответ" : "Start Answer"}</span>
                          </button>
                        )}

                        {/* Listening/Recording Mode */}
                        {voiceState === "listening" && (
                          <button
                            type="button"
                            onClick={stopVoice}
                            className="rounded-xl bg-red-650 hover:bg-red-600 px-6 py-2.5 text-xs font-bold text-white transition-all shadow-md shadow-red-950/20 hover:scale-[1.01] active:scale-[0.99] flex items-center gap-1.5"
                          >
                            <span className="h-1.5 w-1.5 rounded-full bg-white animate-ping" />
                            <span>{interviewLanguage === "ru" ? "Завершить ответ" : "Finish Answer"}</span>
                          </button>
                        )}

                        {/* Transcribing Mode */}
                        {voiceState === "transcribing" && (
                          <div className="flex items-center gap-2 text-xs text-slate-400">
                            <span className="h-3 w-3 border-2 border-slate-500 border-t-transparent rounded-full animate-spin" />
                            <span>{interviewLanguage === "ru" ? "Распознаем..." : "Transcribing..."}</span>
                          </div>
                        )}
                      </div>
                    </div>

                    <div className="rounded-xl border border-blue-500/15 bg-blue-500/5 px-3 py-2 text-[11px] font-medium leading-5 text-slate-400">
                      {interviewLanguage === "ru"
                        ? "Голосовой сценарий: послушайте вопрос, нажмите «Начать ответ», проверьте расшифровку и подтвердите отправку. Текстовый режим доступен только как резервный вариант."
                        : "Voice-first flow: listen to the question, press “Start Answer”, review the transcript, then confirm submission. Text mode is available only as a fallback."}
                    </div>

                    {/* Voice Error State Panel */}
                    {isVoiceError && (
                      <div className="w-full pt-2 border-t border-slate-800/60 space-y-3">
                        <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-3 text-center">
                          <p className="text-xs font-semibold text-red-300">
                            {voiceError || (interviewLanguage === "ru" ? "Не удалось распознать голос. Попробуйте еще раз." : "Failed to transcribe speech. Please try again.")}
                          </p>
                        </div>
                        <div className="flex flex-wrap items-center justify-center gap-2.5">
                          <button
                            type="button"
                            onClick={() => {
                              clearVoiceError();
                              setInput("");
                              setTranscriptPending(false);
                              void startVoice();
                            }}
                            className="rounded-xl bg-blue-650 hover:bg-blue-600 px-4 py-2 text-xs font-semibold text-white transition-all flex items-center gap-1"
                          >
                            ↺ {interviewLanguage === "ru" ? "Повторить запись" : "Retry Recording"}
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              trackProctoringEvent({
                                event_type: "candidate_reported_voice_error",
                                severity: "medium",
                                details: { error: voiceError },
                              });
                              alert(interviewLanguage === "ru" ? "Сообщение об ошибке отправлено организатору." : "Error report has been sent to the organizer.");
                            }}
                            className="rounded-xl border border-slate-700 bg-slate-800 hover:bg-slate-700 px-4 py-2 text-xs font-semibold text-slate-300 hover:text-white transition-all flex items-center gap-1"
                          >
                            📢 {interviewLanguage === "ru" ? "Сообщить организатору" : "Report to Organizer"}
                          </button>
                          {ALLOW_TEXT_FALLBACK && (
                            <button
                              type="button"
                              onClick={() => {
                                setAnswerMode("text");
                                setTranscriptPending(false);
                              }}
                              className="rounded-xl border border-yellow-500/30 bg-yellow-500/10 hover:bg-yellow-500/20 px-4 py-2 text-xs font-semibold text-yellow-300 transition-all flex items-center gap-1"
                            >
                              ⌨ {interviewLanguage === "ru" ? "Текстовый режим" : "Text Mode"}
                            </button>
                          )}
                        </div>
                      </div>
                    )}

                    {/* Toggle Chat History Button */}
                    <div className="flex justify-center pt-1">
                      <button
                        type="button"
                        onClick={() => setShowTranscript(true)}
                        className="text-[11px] font-semibold text-slate-500 hover:text-slate-300 transition-colors flex items-center gap-1"
                      >
                        <span>💬</span>
                        <span>{interviewLanguage === "ru" ? "Показать историю чата" : "Show Chat History"}</span>
                      </button>
                    </div>
                  </div>
                )}

                {/* B. TEXT MODE OR CHAT HISTORY INLINE */}
                {(!voiceMode || showTranscript) && (
                  <div className="w-full flex-1 flex flex-col min-h-[400px] rounded-2xl border border-slate-800 bg-slate-900/60 overflow-hidden shadow-xl">
                    {/* Inline Chat Header (Shown only when in Voice Mode viewing History) */}
                    {voiceMode && showTranscript && (
                      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3 bg-slate-950/40">
                        <h3 className="font-semibold text-xs uppercase tracking-wider text-slate-400">
                          {interviewLanguage === "ru" ? "История диалога" : "Conversation History"}
                        </h3>
                        <button
                          type="button"
                          onClick={() => setShowTranscript(false)}
                          className="rounded-xl border border-slate-800 bg-slate-950 px-3 py-1 text-xs font-semibold text-slate-300 hover:text-white transition-colors"
                        >
                          ✕ {interviewLanguage === "ru" ? "Закрыть историю" : "Close History"}
                        </button>
                      </div>
                    )}

                    {/* Inline Chat Messages */}
                    <div className="flex-1 overflow-y-auto p-4 space-y-4 max-h-[450px]">
                      {messages.map((msg, i) => (
                        <MessageBubble
                          key={i}
                          msg={msg}
                          onReplay={msg.role === "assistant" ? () => speak(msg.content, interviewLanguage) : undefined}
                          speaking={speaking}
                        />
                      ))}
                      {sending && <TypingIndicator />}
                      <div ref={bottomRef} />
                    </div>

                    {/* Text Input Row */}
                    {ALLOW_TEXT_FALLBACK && (
                      <div className="border-t border-slate-800 bg-slate-950/80 p-4">
                        <form
                          className="space-y-3"
                          onSubmit={(e) => {
                            e.preventDefault();
                            void handleSend();
                          }}
                        >
                          <div className="flex items-center justify-between gap-3">
                            <div className="flex items-center gap-2">
                              <button
                                type="button"
                                onClick={() => {
                                  setAnswerMode("text");
                                  setTranscriptPending(false);
                                }}
                                className={`rounded-xl border px-3 py-1.5 text-xs font-medium transition-colors ${
                                  !voiceMode
                                    ? "border-blue-500/30 bg-blue-500/10 text-blue-300"
                                    : "border-slate-800 bg-slate-905 text-slate-400 hover:text-slate-200"
                                }`}
                              >
                                {t("textMode")}
                              </button>
                              <button
                                type="button"
                                onClick={() => {
                                  setAnswerMode("voice");
                                  setTranscriptPending(false);
                                  setShowTranscript(false);
                                }}
                                className={`rounded-xl border px-3 py-1.5 text-xs font-medium transition-colors ${
                                  voiceMode
                                    ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                                    : "border-slate-800 bg-slate-905 text-slate-400 hover:text-slate-200"
                                }`}
                              >
                                {t("voiceMode")}
                              </button>
                            </div>
                          </div>

                          <div className="flex gap-2">
                            <textarea
                              value={input}
                              onChange={(e) => setInput(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === "Enter" && !e.shiftKey) {
                                  e.preventDefault();
                                  void handleSend();
                                }
                              }}
                              disabled={sending}
                              placeholder={
                                sending
                                  ? t("placeholderThinking")
                                  : taskWorkspaceModuleType
                                  ? isWrittenCommunication
                                    ? t("writtenWorkspace.answerPlaceholder")
                                    : isSqlLive
                                    ? t("sqlWorkspace.answerPlaceholder")
                                    : t("codingWorkspace.answerPlaceholder")
                                  : t("placeholderText")
                              }
                              rows={taskWorkspaceModuleType ? 5 : 3}
                              className="flex-1 rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50 resize-y"
                            />
                            <div className="flex flex-col gap-2">
                              <button
                                type="submit"
                                disabled={!input.trim() || sending}
                                className="h-full rounded-xl bg-blue-600 hover:bg-blue-500 px-4 text-sm font-semibold text-white transition-colors disabled:cursor-not-allowed disabled:opacity-40"
                              >
                                {sending ? "..." : t("send")}
                              </button>
                            </div>
                          </div>
                        </form>
                      </div>
                    )}
                  </div>
                )}
              </>
            )}
          </div>
        </section>

        {/* Right Monitor Panel (Webcam + Proctoring) */}
        {cameraPanelOpen && (
          <aside className="w-full xl:w-64 2xl:w-72 shrink-0 space-y-4">
            <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4 shadow-lg sticky top-20">
              <div className="flex items-center justify-between gap-3 mb-3">
                <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-400">
                  {t("cameraCardTitle")}
                </div>
                <StatusPill tone={cameraPreviewReady ? "emerald" : "slate"}>
                  {cameraPreviewReady ? t("face") : t("cameraPreviewOff")}
                </StatusPill>
              </div>

              {/* 16:9 Aspect Video Preview */}
              <div className="relative aspect-video overflow-hidden rounded-xl border border-slate-800 bg-slate-950">
                <video
                  ref={previewRef}
                  muted
                  autoPlay
                  playsInline
                  className={`h-full w-full object-cover transition-opacity ${
                    cameraPreviewReady ? "opacity-100" : "opacity-0"
                  }`}
                />
                {!cameraPreviewReady && (
                  <div className="absolute inset-0 flex items-center justify-center px-4 text-center text-xs text-slate-500">
                    {isRecording ? t("cameraPreviewStarting") : t("cameraPreviewOff")}
                  </div>
                )}
                <div className="absolute inset-x-0 bottom-0 flex items-center justify-between bg-gradient-to-t from-slate-950/90 to-transparent px-3 py-2">
                  <div className="flex items-center gap-1.5 text-[10px] font-medium text-white">
                    <span className={`h-2 w-2 rounded-full ${isRecording ? "animate-pulse bg-red-500" : "bg-slate-500"}`} />
                    <span>{isRecording ? "REC" : t("recordingRequired")}</span>
                  </div>
                  <div className="text-[10px] text-slate-300">{isScreenSharing ? t("screenOn") : t("screenOff")}</div>
                </div>
              </div>

              {/* Compact Monitoring Metrics Underneath */}
              <div className="mt-3 grid grid-cols-3 gap-2">
                <div className="flex flex-col items-center justify-center rounded-lg border border-slate-805 bg-slate-950/60 p-1.5 text-center">
                  <span className="text-[8px] uppercase tracking-wider text-slate-500">{interviewLanguage === "ru" ? "Вне кадра" : "Away"}</span>
                  <span className={`mt-0.5 text-xs font-semibold ${faceAwayPct != null && faceAwayPct > 0.3 ? "text-amber-400" : "text-slate-300"}`}>
                    {faceAwayValue}
                  </span>
                </div>
                <div className="flex flex-col items-center justify-center rounded-lg border border-slate-805 bg-slate-950/60 p-1.5 text-center">
                  <span className="text-[8px] uppercase tracking-wider text-slate-500">{interviewLanguage === "ru" ? "Речь" : "Speech"}</span>
                  <span className={`mt-0.5 text-xs font-semibold ${isSpeechActive ? "text-emerald-400" : "text-slate-300"}`}>
                    {speechActivityValue}
                  </span>
                </div>
                <div className="flex flex-col items-center justify-center rounded-lg border border-slate-805 bg-slate-950/60 p-1.5 text-center">
                  <span className="text-[8px] uppercase tracking-wider text-slate-500">{interviewLanguage === "ru" ? "Тишина" : "Silence"}</span>
                  <span className={`mt-0.5 text-xs font-semibold ${silencePct != null && silencePct > 0.4 ? "text-amber-400" : "text-slate-300"}`}>
                    {silenceValue}
                  </span>
                </div>
              </div>
            </div>
          </aside>
        )}
      </main>

      {/* Practical Task Modal */}
      {practicalModalOpen && practicalTask && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-950/80 backdrop-blur-sm p-4">
          <div className="flex w-full max-w-2xl max-h-[90vh] flex-col overflow-hidden rounded-[28px] border border-slate-700 bg-slate-900 shadow-[0_32px_100px_rgba(2,6,23,0.6)]">
            {/* Modal header */}
            <div className="flex items-start justify-between gap-4 border-b border-slate-800 px-6 py-5">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.22em] text-amber-300">Практическое задание</div>
                <div className="mt-1 text-lg font-semibold text-white">{practicalTask.title}</div>
                {practicalTask.time_limit_minutes && (
                  <div className="mt-1 text-xs text-slate-400">⏱ {practicalTask.time_limit_minutes} минут</div>
                )}
              </div>
              <div className="rounded-full border border-amber-500/30 bg-amber-500/10 px-3 py-1 text-xs uppercase tracking-[0.16em] text-amber-300">
                {practicalTask.task_type.replace(/_/g, " ")}
              </div>
            </div>

            <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
              {/* Instructions */}
              <div className="rounded-2xl border border-slate-700/80 bg-slate-950/50 px-5 py-4">
                <div className="text-xs uppercase tracking-[0.16em] text-slate-500 mb-2">Задание</div>
                <p className="text-sm leading-relaxed text-slate-200 whitespace-pre-wrap">{practicalTask.instruction}</p>
              </div>

              {/* Examples */}
              {practicalTask.examples && practicalTask.examples.length > 0 && (
                <div>
                  <div className="text-xs uppercase tracking-[0.16em] text-slate-500 mb-2">Примеры</div>
                  <div className="space-y-2">
                    {practicalTask.examples.map((ex, i) => (
                      <div key={i} className="rounded-xl border border-slate-700 bg-slate-950/40 px-4 py-3 text-xs font-mono">
                        {ex.description && <div className="text-slate-400 mb-1">{ex.description}</div>}
                        {ex.input && <div className="text-slate-300"><span className="text-slate-500">Input: </span>{ex.input}</div>}
                        {ex.output && <div className="text-slate-300"><span className="text-slate-500">Output: </span>{ex.output}</div>}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Evaluation criteria */}
              {practicalTask.evaluation_criteria && practicalTask.evaluation_criteria.length > 0 && (
                <div>
                  <div className="text-xs uppercase tracking-[0.16em] text-slate-500 mb-2">Критерии оценки</div>
                  <div className="flex flex-wrap gap-2">
                    {practicalTask.evaluation_criteria.map((c) => (
                      <span key={c} className="rounded-full border border-slate-700 bg-slate-800/60 px-3 py-1 text-xs text-slate-300">{c}</span>
                    ))}
                  </div>
                </div>
              )}

              {/* Starter code / reference */}
              {practicalTask.starter_code && (
                <div>
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <div className="text-xs uppercase tracking-[0.16em] text-slate-500">Boilerplate / reference</div>
                    <span className="rounded-full border border-blue-500/20 bg-blue-500/10 px-3 py-1 text-[11px] font-semibold text-blue-300">
                      Только подсказка, не ответ
                    </span>
                  </div>
                  <pre className="max-h-44 overflow-auto rounded-2xl border border-slate-700 bg-slate-950/60 px-4 py-3 text-xs leading-5 text-slate-300">
                    {practicalTask.starter_code}
                  </pre>
                </div>
              )}

              {/* Answer area */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <div className="text-xs uppercase tracking-[0.16em] text-slate-500">Ваше решение</div>
                  {practicalTask.language && practicalTask.language !== "text" && (
                    <span className="rounded-full border border-slate-700 bg-slate-800 px-3 py-1 text-xs uppercase tracking-[0.14em] text-slate-300">
                      {practicalTask.language}
                    </span>
                  )}
                </div>
                <textarea
                  value={practicalAnswer}
                  onChange={(e) => {
                    setPracticalAnswer(e.target.value);
                    if (practicalError) setPracticalError("");
                  }}
                  placeholder={
                    practicalTask.task_type === "coding_task" || practicalTask.task_type === "debugging_task"
                      ? "Напишите код здесь..."
                      : practicalTask.task_type === "sql_task"
                      ? "Напишите SQL-запрос здесь..."
                      : "Напишите ответ здесь..."
                  }
                  rows={14}
                  className={`w-full rounded-2xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm leading-6 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-amber-500 resize-y ${
                    practicalTask.language && practicalTask.language !== "text" && practicalTask.language !== "other"
                      ? "font-mono"
                      : "font-sans"
                  }`}
                />
              </div>
            </div>

            {/* Modal footer */}
            <div className="space-y-3 border-t border-slate-800 px-6 py-4">
              {practicalError && (
                <div className="rounded-xl border border-red-500/20 bg-red-500/10 px-3 py-2 text-sm text-red-300">
                  {practicalError}
                </div>
              )}
              <div className="flex items-center justify-between gap-4">
              <button
                type="button"
                onClick={() => {
                  setPracticalModalOpen(false);
                  setPracticalError("");
                }}
                disabled={practicalSubmitting}
                className="rounded-xl border border-slate-700 px-5 py-2.5 text-sm text-slate-300 transition-colors hover:border-slate-600 hover:text-white disabled:opacity-40"
              >
                Закрыть
              </button>
              <button
                type="button"
                onClick={() => void handlePracticalSubmit()}
                disabled={practicalSubmitting || !practicalAnswer.trim() || practicalAnswerIsOnlyStarter}
                title={practicalAnswerIsOnlyStarter ? "Добавьте собственное решение, boilerplate сам по себе не засчитывается." : undefined}
                className="rounded-xl bg-amber-600 px-8 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-amber-500 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {practicalSubmitting ? "Отправляю..." : "Отправить решение"}
              </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Slide-out Drawer for Voice Chat History */}
      {showTranscript && voiceMode && (
        <div className="fixed inset-0 z-40 flex justify-end">
          {/* Backdrop blur overlay */}
          <div
            className="absolute inset-0 bg-slate-950/40 backdrop-blur-sm transition-opacity"
            onClick={() => setShowTranscript(false)}
          />
          {/* Drawer container */}
          <div className="relative w-full max-w-[440px] h-full bg-slate-900/95 border-l border-slate-800 shadow-2xl flex flex-col z-10 transition-transform duration-350">
            {/* Drawer Header */}
            <div className="flex items-center justify-between border-b border-slate-800 p-4">
              <h3 className="font-semibold text-white">
                {interviewLanguage === "ru" ? "История диалога" : "Conversation History"}
              </h3>
              <button
                type="button"
                onClick={() => setShowTranscript(false)}
                className="rounded-full border border-slate-700 bg-slate-800 hover:bg-slate-700 p-1.5 text-slate-400 hover:text-white transition-colors"
              >
                ✕
              </button>
            </div>
            {/* Drawer Body (Scrollable Chat) */}
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
              {messages.map((msg, i) => (
                <MessageBubble
                  key={i}
                  msg={msg}
                  onReplay={msg.role === "assistant" ? () => speak(msg.content, interviewLanguage) : undefined}
                  speaking={speaking}
                />
              ))}
              {sending && <TypingIndicator />}
              <div ref={bottomRef} />
            </div>
          </div>
        </div>
      )}

      {(finishing || reportRetrying) && (
        <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-slate-900/90 backdrop-blur-sm">
          <div className="flex flex-col items-center gap-6 px-8 text-center">
            <div className="relative h-16 w-16">
              <div className="absolute inset-0 rounded-full border-4 border-slate-700" />
              <div className="absolute inset-0 rounded-full border-4 border-t-blue-500 animate-spin" />
            </div>
            <div>
              <p className="text-lg font-semibold text-white">
                {waitingForReport || reportRetrying ? t("analyzing") : t("finishing")}
              </p>
              <p className="mt-1 text-sm text-slate-400">
                {waitingForReport || reportRetrying ? t("analysisDuration") : t("savingResponses")}
              </p>
              {(waitingForReport || reportRetrying) && (
                <div className="mt-3">
                  <span className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium ${reportPhaseToneClass}`}>
                    {reportPhaseLabel}
                  </span>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="flex justify-start">
      <div className="bg-slate-800 border border-slate-700 rounded-2xl rounded-bl-sm px-4 py-3">
        <div className="text-blue-400 text-xs font-medium mb-1.5 uppercase tracking-wide">AI</div>
        <div className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-slate-500 animate-bounce" style={{ animationDelay: "0ms" }} />
          <span className="w-2 h-2 rounded-full bg-slate-500 animate-bounce" style={{ animationDelay: "150ms" }} />
          <span className="w-2 h-2 rounded-full bg-slate-500 animate-bounce" style={{ animationDelay: "300ms" }} />
        </div>
      </div>
    </div>
  );
}

function WorkspaceStat({
  label,
  value,
  tone = "slate",
  compact = false,
}: {
  label: string;
  value: string;
  tone?: "slate" | "blue" | "emerald" | "amber";
  compact?: boolean;
}) {
  const toneClasses: Record<NonNullable<typeof tone>, string> = {
    slate: "border-slate-800 bg-slate-950/60 text-white",
    blue: "border-blue-500/20 bg-blue-500/10 text-blue-50",
    emerald: "border-emerald-500/20 bg-emerald-500/10 text-emerald-50",
    amber: "border-yellow-500/20 bg-yellow-500/10 text-yellow-50",
  };

  return (
    <div className={`rounded-2xl border px-3 py-3 ${toneClasses[tone]}`}>
      <div className="text-[11px] uppercase tracking-[0.16em] text-slate-500">{label}</div>
      <div className={`mt-1 font-semibold ${compact ? "text-sm" : "text-base"}`}>{value}</div>
    </div>
  );
}

function StatusPill({
  children,
  tone = "slate",
}: {
  children: React.ReactNode;
  tone?: "slate" | "blue" | "emerald" | "amber" | "purple";
}) {
  const toneClasses: Record<NonNullable<typeof tone>, string> = {
    slate: "border-slate-700 bg-slate-900/70 text-slate-200",
    blue: "border-blue-500/30 bg-blue-500/10 text-blue-200",
    emerald: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
    amber: "border-yellow-500/30 bg-yellow-500/10 text-yellow-200",
    purple: "border-purple-500/30 bg-purple-500/10 text-purple-200",
  };

  return (
    <span className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium ${toneClasses[tone]}`}>
      {children}
    </span>
  );
}

function VerticalStepper({ items }: { items: StageRailItem[] }) {
  if (!items.length) return null;

  return (
    <div className="flex flex-col space-y-4">
      {items.map((item, index) => {
        const isDone = item.state === "done";
        const isCurrent = item.state === "current";

        const circleBg = isDone
          ? "bg-emerald-500 text-slate-950 font-bold"
          : isCurrent
          ? "bg-blue-600 text-white font-bold ring-4 ring-blue-500/20"
          : "bg-slate-800 text-slate-400 border border-slate-700";

        const textClass = isCurrent
          ? "text-white font-semibold"
          : isDone
          ? "text-slate-300"
          : "text-slate-500";

        return (
          <div key={item.key} className="relative flex items-start gap-3">
            {/* Connector Line */}
            {index < items.length - 1 && (
              <div
                className={`absolute left-[11px] top-6 w-[2px] h-[calc(100%+16px)] ${
                  isDone ? "bg-emerald-500" : "bg-slate-800"
                }`}
              />
            )}

            {/* Circle indicator */}
            <div className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs transition-colors ${circleBg}`}>
              {isDone ? "✓" : index + 1}
            </div>

            {/* Label */}
            <div className="pt-0.5 min-w-0">
              <span className={`text-sm block truncate transition-colors ${textClass}`}>
                {item.label}
              </span>
            </div>
          </div>
        );
      })}
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
  const t = useTranslations("interview");
  const isAI = msg.role === "assistant";
  return (
    <div className={`flex ${isAI ? "justify-start" : "justify-end"}`}>
      <div className="group relative max-w-[92%] md:max-w-[80%]">
        <div
          className={`rounded-2xl px-4 py-3 text-sm leading-relaxed ${
            isAI
              ? "rounded-bl-sm border border-slate-700 bg-slate-800 text-slate-100 shadow-[0_10px_30px_rgba(2,6,23,0.18)]"
              : "rounded-br-sm bg-blue-600 text-white shadow-[0_10px_30px_rgba(37,99,235,0.25)]"
          }`}
        >
          {isAI && (
            <div className="text-blue-400 text-xs font-medium mb-1 uppercase tracking-wide">
              AI
            </div>
          )}
          {msg.content}
        </div>
        {/* Replay button — shown on hover for AI messages */}
        {isAI && onReplay && (
          <button
            type="button"
            onClick={onReplay}
            title={t("tooltips.replayQuestion")}
            className="absolute -bottom-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity bg-slate-700 hover:bg-slate-600 text-slate-300 text-xs rounded-full w-6 h-6 flex items-center justify-center"
          >
            {speaking ? "■" : "▶"}
          </button>
        )}
      </div>
    </div>
  );
}
