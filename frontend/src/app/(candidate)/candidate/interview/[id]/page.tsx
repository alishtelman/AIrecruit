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
const DEFAULT_INTERVIEW_MODE: "voice" | "text" =
  process.env.NEXT_PUBLIC_DEFAULT_INTERVIEW_MODE === "voice" ? "voice" : "text";
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
  const { loading: authLoading } = useAuth();

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
    setPracticalSubmitting(true);
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
      setError(err instanceof Error ? err.message : "Ошибка отправки задания");
    } finally {
      setPracticalSubmitting(false);
    }
  }

  async function handleSend() {
    if (!input.trim() || sending || !id) return;
    const text = input.trim();

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
          setPracticalAnswer(res.practical_task.starter_code ?? "");
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
    : voiceState === "recording" ? "listening"
    : voiceState === "transcribing" || sending ? "processing"
    : "idle";
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
    <div className="min-h-screen bg-slate-950 text-white">
      <header className="border-b border-slate-800/80 bg-slate-950/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-4 sm:px-6">
          <div className="flex min-w-0 items-center gap-4">
            <Link href="/candidate/reports" className="text-slate-500 transition-colors hover:text-slate-300">
              ←
            </Link>
            <div className="min-w-0">
              <div className="truncate text-lg font-semibold">{t("interviewTitle", { role: roleLabel })}</div>
              <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-slate-400">
                <span>{currentQuestionLabel}</span>
                <span>•</span>
                <span>{askedInChatLabel}</span>
                <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium ${interviewStatusToneClass}`}>
                  {interview.status === "in_progress" ? t("statusInProgress") : reportPhaseLabel}
                </span>
              </div>
            </div>
          </div>
          <LocaleSwitcher />
        </div>
      </header>

      <main className="mx-auto flex max-w-7xl flex-col gap-5 px-4 py-5 sm:px-6 xl:grid xl:min-h-[calc(100vh-81px)] xl:grid-cols-[minmax(320px,380px)_minmax(0,1fr)] xl:gap-6 xl:overflow-hidden">
        <aside className="space-y-4 xl:overflow-y-auto xl:pr-1">
          <section className="overflow-hidden rounded-[28px] border border-slate-800 bg-[radial-gradient(circle_at_top,_rgba(59,130,246,0.18),_transparent_58%),linear-gradient(180deg,_rgba(15,23,42,0.98),_rgba(15,23,42,0.9))] p-5 shadow-[0_24px_80px_rgba(2,6,23,0.45)]">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.24em] text-cyan-300">{t("candidateCardEyebrow")}</div>
                <div className="mt-2 text-xl font-semibold text-white">{roleLabel}</div>
                <div className="mt-2 text-sm leading-6 text-slate-300">
                  {isFollowup ? currentQuestionTypeLabel : currentQuestionLabel}
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <StatusPill tone={isRecording ? "emerald" : "amber"}>{isRecording ? "REC" : t("recordingRequired")}</StatusPill>
                <StatusPill tone={isScreenSharing ? "emerald" : "slate"}>{isScreenSharing ? t("screenOn") : t("screenOff")}</StatusPill>
              </div>
            </div>

            <div className="mt-5 grid gap-3 sm:grid-cols-3 xl:grid-cols-1 2xl:grid-cols-3">
              <WorkspaceStat label={t("timerLabel")} value={elapsedLabel} tone="blue" />
              <WorkspaceStat label={t("questionProgressLabel")} value={currentQuestionLabel} tone="slate" />
              <WorkspaceStat label={t("askedQuestionsLabel")} value={askedInChatLabel} tone="slate" />
              <WorkspaceStat
                label={t("estimateLabel")}
                value={t("structureEstimatedDuration", estimatedDuration)}
                tone="emerald"
              />
            </div>
            <p className="mt-3 text-xs text-slate-400">
              {t("progressHint", {
                percent: Math.min(100, Math.max(visibleProgressPct, 0)),
                answered: candidateAnswerCount,
              })}
            </p>

            <div className="mt-5 rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="text-xs uppercase tracking-[0.18em] text-slate-500">{t("stageLabel")}</div>
                  <div className="mt-1 text-base font-semibold text-white">{stageDisplayTitle}</div>
                </div>
                {structuredInterviewStage ? (
                  <StatusPill tone="emerald">
                    {t("stageProgress", {
                      current: structuredPhaseProgressCurrent,
                      total: structuredPhaseProgressTotal,
                    })}
                  </StatusPill>
                ) : (overviewModuleSession || taskWorkspaceSession) ? (
                  <StatusPill tone="blue">
                    {t("stageProgress", {
                      current: ((overviewModuleSession || taskWorkspaceSession)?.stage_index ?? 0) + 1,
                      total: Math.max((overviewModuleSession || taskWorkspaceSession)?.stage_count ?? 0, 1),
                    })}
                  </StatusPill>
                ) : null}
              </div>

              {stageRailItems.length > 0 && <StageRail items={stageRailItems} />}

              {(overviewModuleSession || taskWorkspaceSession)?.scenario_title && (
                <div className="mt-4">
                  <div className="text-xs uppercase tracking-[0.16em] text-slate-500">
                    {taskWorkspaceSession ? t("taskLabel") : t("scenarioLabel")}
                  </div>
                  <div className="mt-1 text-sm text-slate-200">{(overviewModuleSession || taskWorkspaceSession)?.scenario_title}</div>
                </div>
              )}

              {structuredInterviewStage?.resume_anchor && (
                <div className="mt-4">
                  <div className="text-xs uppercase tracking-[0.16em] text-slate-500">{t("structureResumeAnchor")}</div>
                  <div className="mt-1 text-sm leading-6 text-slate-200">{structuredInterviewStage.resume_anchor}</div>
                </div>
              )}

              {structuredInterviewStage?.verification_target && (
                <div className="mt-4">
                  <div className="text-xs uppercase tracking-[0.16em] text-slate-500">{t("structureVerificationTarget")}</div>
                  <div className="mt-1 text-sm leading-6 text-slate-200">{structuredInterviewStage.verification_target}</div>
                </div>
              )}

              {taskWorkspaceSession?.stack_focus && (
                <div className="mt-4">
                  <div className="text-xs uppercase tracking-[0.16em] text-slate-500">{t("stackLabel")}</div>
                  <div className="mt-1 text-sm leading-6 text-slate-200">{taskWorkspaceSession.stack_focus}</div>
                </div>
              )}
            </div>

            {currentQuestion && interview.status === "in_progress" && (
              <div className="mt-5 rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
                <div className="text-xs uppercase tracking-[0.18em] text-slate-500">{t("currentFocusLabel")}</div>
                <div className="mt-2 text-sm leading-6 text-slate-100">{currentQuestion}</div>
              </div>
            )}

            {structuredInterviewStage?.competency_targets.length ? (
              <div className="mt-5">
                <div className="text-xs uppercase tracking-[0.18em] text-slate-500">{t("structureCompetencies")}</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {structuredInterviewStage.competency_targets.map((competency) => (
                    <span
                      key={competency}
                      className="rounded-full border border-cyan-500/20 bg-cyan-500/10 px-3 py-1 text-xs text-cyan-100"
                    >
                      {competency}
                    </span>
                  ))}
                </div>
              </div>
            ) : null}

            <div className="mt-5 flex flex-wrap gap-2">
              {resumeText && (
                <button
                  onClick={() => setResumeOpen((value) => !value)}
                  title={t("tooltips.toggleResume")}
                  className={`rounded-xl border px-3 py-2 text-xs font-medium transition-colors ${
                    resumeOpen
                      ? "border-purple-500/30 bg-purple-500/10 text-purple-300"
                      : "border-slate-700 bg-slate-900/60 text-slate-300 hover:border-slate-600"
                  }`}
                >
                  {t("resume")}
                </button>
              )}
              <button
                onClick={toggleTTS}
                title={ttsEnabled ? t("tooltips.muteVoice") : t("tooltips.enableVoice")}
                className={`rounded-xl border px-3 py-2 text-xs font-medium transition-colors ${
                  ttsEnabled
                    ? "border-blue-500/30 bg-blue-500/10 text-blue-300 hover:bg-blue-500/20"
                    : "border-slate-700 bg-slate-900/60 text-slate-300 hover:border-slate-600"
                }`}
              >
                {ttsEnabled ? t("voiceOn") : t("voiceOff")}
              </button>
              {!isRecording && interview.status === "in_progress" && (
                <button
                  onClick={() => void startRecording()}
                  className="rounded-xl border border-yellow-500/30 bg-yellow-500/10 px-3 py-2 text-xs font-medium text-yellow-200 transition-colors hover:bg-yellow-500/20"
                >
                  {t("enableRecording")}
                </button>
              )}
            </div>

            {(localizedRecordingError || voiceError || (!isRecording && interview.status === "in_progress")) && (
              <div className="mt-5 space-y-3">
                {!isRecording && interview.status === "in_progress" && (
                  <div className="rounded-2xl border border-yellow-500/30 bg-yellow-500/10 px-4 py-3 text-sm text-yellow-100">
                    <div className="font-medium text-yellow-200">{t("recordingRequired")}</div>
                    <div className="mt-1 text-yellow-50/90">{t("recordingDescription")}</div>
                  </div>
                )}
                {localizedRecordingError && (
                  <div className="rounded-2xl border border-yellow-500/30 bg-yellow-500/10 px-4 py-3 text-sm text-yellow-100">
                    {localizedRecordingError}
                  </div>
                )}
                {voiceError && (
                  <div className="rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
                    {voiceError}
                  </div>
                )}
              </div>
            )}
          </section>

          <section className="rounded-[28px] border border-slate-800 bg-slate-900/80 p-4 shadow-[0_18px_60px_rgba(2,6,23,0.35)]">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500">{t("cameraCardTitle")}</div>
                <div className="mt-1 text-sm text-slate-400">{t("cameraCardHint")}</div>
              </div>
              <StatusPill tone={cameraPreviewReady ? "emerald" : "slate"}>
                {cameraPreviewReady ? t("face") : t("cameraPreviewOff")}
              </StatusPill>
            </div>

            <div className="relative mt-4 aspect-[4/3] overflow-hidden rounded-2xl border border-slate-800 bg-slate-950">
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
                <div className="absolute inset-0 flex items-center justify-center px-6 text-center text-sm text-slate-400">
                  {isRecording ? t("cameraPreviewStarting") : t("cameraPreviewOff")}
                </div>
              )}
              <div className="absolute inset-x-0 bottom-0 flex items-center justify-between bg-gradient-to-t from-slate-950/95 via-slate-950/40 to-transparent px-4 py-3">
                <div className="flex items-center gap-2 text-xs font-medium text-white">
                  <span className={`h-2.5 w-2.5 rounded-full ${isRecording ? "animate-pulse bg-red-500" : "bg-slate-500"}`} />
                  <span>{isRecording ? "REC" : t("recordingRequired")}</span>
                </div>
                <div className="text-xs text-slate-300">{isScreenSharing ? t("screenOn") : t("screenOff")}</div>
              </div>
            </div>

            <div className="mt-4 grid grid-cols-3 gap-3">
              <WorkspaceStat label={t("faceAwayLabel")} value={faceAwayValue} tone={faceAwayPct != null && faceAwayPct > 0.3 ? "amber" : "slate"} compact />
              <WorkspaceStat label={t("speechActivityLabel")} value={speechActivityValue} tone={isSpeechActive ? "emerald" : "slate"} compact />
              <WorkspaceStat label={t("silenceLabel")} value={silenceValue} tone={silencePct != null && silencePct > 0.4 ? "amber" : "slate"} compact />
            </div>
          </section>

          {resumeOpen && resumeText && (
            <section className="rounded-[28px] border border-slate-800 bg-slate-900/80 p-4 shadow-[0_18px_60px_rgba(2,6,23,0.35)]">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500">{t("resume")}</div>
                  <div className="mt-1 text-sm text-slate-400">{t("resumePreviewHint")}</div>
                </div>
                <button
                  onClick={() => setResumeOpen(false)}
                  className="rounded-full border border-slate-700 bg-slate-950/70 px-3 py-1 text-xs text-slate-300 transition-colors hover:border-slate-600 hover:text-white"
                >
                  ×
                </button>
              </div>
              <pre className="mt-4 max-h-72 overflow-y-auto whitespace-pre-wrap rounded-2xl border border-slate-800 bg-slate-950/70 p-4 text-xs leading-6 text-slate-300">
                {resumeText}
              </pre>
            </section>
          )}
        </aside>

        <section className="flex min-h-0 flex-col">
          {error && !canFinish && (
            <div className="mb-4 rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
              {error}
            </div>
          )}

          <div className="flex min-h-[65vh] flex-1 flex-col overflow-hidden rounded-[30px] border border-slate-800 bg-slate-900/80 shadow-[0_24px_80px_rgba(2,6,23,0.4)]">
            {/* Header */}
            <div className="border-b border-slate-800/80 px-4 py-4 sm:px-6">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-300">{t("chatCardEyebrow")}</div>
                  <div className="mt-1 text-lg font-semibold text-white">{stageDisplayTitle}</div>
                </div>
                <div className="flex flex-wrap gap-2">
                  {voiceMode && (
                    <button
                      type="button"
                      onClick={() => setShowTranscript((v) => !v)}
                      className={`rounded-xl border px-3 py-1.5 text-xs font-medium transition-colors ${
                        showTranscript
                          ? "border-cyan-500/30 bg-cyan-500/10 text-cyan-300"
                          : "border-slate-700 bg-slate-900/60 text-slate-400 hover:text-slate-200"
                      }`}
                    >
                      {showTranscript ? "↑ Скрыть чат" : "↓ Показать чат"}
                    </button>
                  )}
                  {ENABLE_VOICE_INTERVIEW && (
                    <button
                      type="button"
                      onClick={() => {
                        setAnswerMode((m) => m === "voice" ? "text" : "voice");
                        setTranscriptPending(false);
                        setInput("");
                      }}
                      className="rounded-xl border border-slate-700 bg-slate-900/60 px-3 py-1.5 text-xs text-slate-400 transition-colors hover:text-slate-200"
                    >
                      {voiceMode ? "Текстовый режим" : "Голосовой режим"}
                    </button>
                  )}
                  <StatusPill tone={isFollowup ? "purple" : "slate"}>{currentQuestionTypeLabel}</StatusPill>
                  {uploadStatusLabel && <StatusPill tone={recordingUploadState === "failed" ? "amber" : "slate"}>{uploadStatusLabel}</StatusPill>}
                </div>
              </div>
            </div>

            {/* Voice-first main area — only when feature flag is enabled */}
            {ENABLE_VOICE_INTERVIEW && voiceMode && !showTranscript && !canFinish && interview.status === "in_progress" && (
              <div className="flex flex-1 flex-col items-center justify-center gap-6 px-6 py-10">
                {/* Status indicator */}
                <div className="flex flex-col items-center gap-2">
                  <div className={`flex h-16 w-16 items-center justify-center rounded-full transition-all duration-300 ${
                    voiceStatus === "ai_speaking" ? "bg-blue-500/20 shadow-[0_0_32px_rgba(59,130,246,0.4)]"
                    : voiceStatus === "listening" ? "animate-pulse bg-red-500/20 shadow-[0_0_32px_rgba(239,68,68,0.4)]"
                    : voiceStatus === "processing" ? "bg-amber-500/20 shadow-[0_0_24px_rgba(245,158,11,0.3)]"
                    : "bg-slate-800"
                  }`}>
                    <span className="text-2xl">
                      {voiceStatus === "ai_speaking" ? "🔊" : voiceStatus === "listening" ? "🎤" : voiceStatus === "processing" ? "⏳" : "🎙"}
                    </span>
                  </div>
                  <div className="text-sm font-medium text-slate-300">
                    {voiceStatus === "ai_speaking" ? "AI говорит..."
                      : voiceStatus === "listening" ? "Слушаю..."
                      : voiceStatus === "processing" ? "Обрабатываю..."
                      : "Готов к ответу"}
                  </div>
                </div>

                {/* Current question */}
                {currentQuestion && (
                  <div className="w-full max-w-xl rounded-2xl border border-blue-500/20 bg-blue-500/10 px-6 py-5 text-center">
                    <div className="mb-3 text-xs font-semibold uppercase tracking-[0.2em] text-blue-300">Вопрос</div>
                    <p className="text-base leading-relaxed text-white">{currentQuestion}</p>
                    <button
                      type="button"
                      onClick={() => speak(currentQuestion, interviewLanguage)}
                      disabled={speaking}
                      className="mt-4 rounded-full border border-blue-500/30 bg-slate-900/60 px-4 py-1.5 text-xs text-blue-300 transition-colors hover:bg-blue-500/20 disabled:opacity-40"
                    >
                      ▶ Повторить
                    </button>
                  </div>
                )}

                {introPending && (
                  <div className="w-full max-w-xl rounded-2xl border border-slate-700 bg-slate-900/60 px-6 py-5 text-center text-sm text-slate-300">
                    {t("introPending")}
                  </div>
                )}

                {/* Transcript preview + confirm (when VOICE_AUTO_SEND=false and STT done) */}
                {transcriptPending && input.trim() && !sending && (
                  <div className="w-full max-w-xl space-y-3">
                    <div className="rounded-2xl border border-emerald-500/20 bg-emerald-500/10 px-5 py-4">
                      <div className="mb-2 text-xs font-semibold uppercase tracking-[0.2em] text-emerald-300">Ваш ответ</div>
                      <p className="text-sm leading-relaxed text-white">{input}</p>
                    </div>
                    <div className="flex items-center gap-3">
                      <button
                        type="button"
                        onClick={() => void handleSend()}
                        disabled={sending}
                        className="flex-1 rounded-xl bg-blue-600 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-blue-500 disabled:opacity-40"
                      >
                        ✓ Отправить ответ
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setInput("");
                          setLatestTranscript("");
                          setTranscriptPending(false);
                        }}
                        className="rounded-xl border border-slate-700 px-4 py-2.5 text-sm text-slate-300 transition-colors hover:border-slate-600"
                      >
                        ↺ Перезаписать
                      </button>
                    </div>
                  </div>
                )}

                {/* Mic button — hidden while transcript is pending or AI is speaking or sending */}
                {!sending && voiceStatus !== "ai_speaking" && !introPending && !transcriptPending && (
                  <div className="flex flex-col items-center gap-3">
                    <button
                      type="button"
                      onMouseDown={() => { setInput(""); setTranscriptPending(false); void startVoice(); }}
                      onMouseUp={stopVoice}
                      onTouchStart={() => { setInput(""); setTranscriptPending(false); void startVoice(); }}
                      onTouchEnd={stopVoice}
                      disabled={voiceState === "transcribing" || sending}
                      className={`h-20 w-20 rounded-full border-2 text-3xl font-bold transition-all duration-200 select-none ${
                        voiceState === "recording"
                          ? "animate-pulse border-red-500 bg-red-500/20 text-red-300 shadow-[0_0_32px_rgba(239,68,68,0.5)]"
                          : voiceState === "transcribing"
                          ? "border-amber-500/50 bg-amber-500/10 text-amber-400 opacity-60"
                          : "border-slate-600 bg-slate-800 text-slate-200 hover:border-slate-500 hover:bg-slate-700 active:scale-95"
                      }`}
                    >
                      {voiceState === "recording" ? "●" : voiceState === "transcribing" ? "…" : "🎙"}
                    </button>
                    <p className="text-xs text-slate-500">
                      {voiceState === "recording" ? "Говорите — отпустите чтобы завершить"
                        : voiceState === "transcribing" ? "Распознаю речь..."
                        : "Удержите кнопку и говорите"}
                    </p>
                  </div>
                )}

                {/* Intro "ready" prompt */}
                {introPending && !transcriptPending && (
                  <div className="flex flex-col items-center gap-3">
                    <button
                      type="button"
                      onMouseDown={() => { setInput(""); setTranscriptPending(false); void startVoice(); }}
                      onMouseUp={stopVoice}
                      onTouchStart={() => { setInput(""); setTranscriptPending(false); void startVoice(); }}
                      onTouchEnd={stopVoice}
                      disabled={voiceState !== "idle"}
                      className={`rounded-2xl border px-8 py-3 font-semibold transition-all ${
                        voiceState === "recording"
                          ? "animate-pulse border-red-500 bg-red-500/20 text-red-300"
                          : voiceState === "transcribing"
                          ? "border-amber-500/50 bg-amber-500/10 text-amber-400 opacity-60"
                          : "border-emerald-500/30 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20"
                      }`}
                    >
                      {voiceState === "recording" ? "🎤 Слушаю..." : voiceState === "transcribing" ? "Распознаю..." : "🎙 Я готов / Ready"}
                    </button>
                    <p className="text-xs text-slate-500">Скажите «Готов» или «Ready»</p>
                  </div>
                )}

                {/* Intro confirm when transcript pending */}
                {introPending && transcriptPending && input.trim() && (
                  <div className="flex flex-col items-center gap-3">
                    <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/10 px-5 py-3 text-sm text-emerald-200">
                      Распознано: <span className="font-medium">{input}</span>
                    </div>
                    <div className="flex gap-3">
                      <button
                        type="button"
                        onClick={() => void handleSend()}
                        className="rounded-xl bg-emerald-600 px-6 py-2 text-sm font-semibold text-white hover:bg-emerald-500"
                      >
                        Отправить
                      </button>
                      <button
                        type="button"
                        onClick={() => { setInput(""); setTranscriptPending(false); }}
                        className="rounded-xl border border-slate-700 px-5 py-2 text-sm text-slate-300 hover:border-slate-600"
                      >
                        Перезаписать
                      </button>
                    </div>
                  </div>
                )}

                {voiceError && (
                  <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
                    {voiceError}
                  </div>
                )}
              </div>
            )}

            {/* Transcript / Chat panel */}
            <div className={`flex-1 overflow-y-auto px-4 py-4 sm:px-6 ${ENABLE_VOICE_INTERVIEW && voiceMode && !showTranscript && !canFinish && interview.status === "in_progress" ? "hidden" : ""}`}>
              <div className="space-y-4">
                {(overviewModuleSession || taskWorkspaceSession) && (
                  <div className="rounded-2xl border border-blue-500/20 bg-blue-500/10 p-5">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-300">
                        {(overviewModuleSession || taskWorkspaceSession)?.module_title || t("moduleCardEyebrow")}
                      </div>
                      <div className="rounded-full border border-blue-400/20 bg-slate-900/50 px-3 py-1 text-xs text-slate-200">
                        {t("stageProgress", {
                          current: ((overviewModuleSession || taskWorkspaceSession)?.stage_index ?? 0) + 1,
                          total: Math.max((overviewModuleSession || taskWorkspaceSession)?.stage_count ?? 0, 1),
                        })}
                      </div>
                    </div>
                    {(overviewModuleSession || taskWorkspaceSession)?.scenario_title && (
                      <div className="mt-3">
                        <div className="text-xs uppercase tracking-[0.14em] text-slate-400">
                          {taskWorkspaceSession ? t("taskLabel") : t("scenarioLabel")}
                        </div>
                        <div className="mt-1 text-sm font-medium text-white">
                          {(overviewModuleSession || taskWorkspaceSession)?.scenario_title}
                        </div>
                      </div>
                    )}
                    {(overviewModuleSession || taskWorkspaceSession)?.stage_title && (
                      <div className="mt-3">
                        <div className="text-xs uppercase tracking-[0.14em] text-slate-400">{t("stageLabel")}</div>
                        <div className="mt-1 text-sm text-slate-200">{(overviewModuleSession || taskWorkspaceSession)?.stage_title}</div>
                      </div>
                    )}
                    {taskWorkspaceSession?.stack_focus && (
                      <div className="mt-3">
                        <div className="text-xs uppercase tracking-[0.14em] text-slate-400">{t("stackLabel")}</div>
                        <div className="mt-1 text-sm text-slate-200">{taskWorkspaceSession.stack_focus}</div>
                      </div>
                    )}
                    {(overviewModuleSession || taskWorkspaceSession)?.scenario_prompt && (
                      <p className="mt-3 text-sm leading-6 text-slate-300">{(overviewModuleSession || taskWorkspaceSession)?.scenario_prompt}</p>
                    )}
                    {taskWorkspaceSession && (
                      <div className="mt-4 space-y-3">
                        <div className="rounded-xl border border-slate-700/80 bg-slate-950/40 px-4 py-3 text-sm text-slate-300">
                          {taskWorkspaceSession.workspace_hint || (isWrittenCommunication ? t("writtenTaskHint") : isSqlLive ? t("sqlTaskHint") : t("codingTaskHint"))}
                        </div>
                        <div className="rounded-2xl border border-slate-700 bg-slate-950/70 p-4">
                          <div className="flex flex-wrap items-center justify-between gap-3">
                            <div>
                              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
                                {isWrittenCommunication ? t("writtenWorkspace.title") : isSqlLive ? t("sqlWorkspace.title") : t("codingWorkspace.title")}
                              </div>
                              <p className="mt-1 text-sm text-slate-300">
                                {isWrittenCommunication ? t("writtenWorkspace.description") : isSqlLive ? t("sqlWorkspace.description") : t("codingWorkspace.description")}
                              </p>
                            </div>
                            {codingTaskSaveLabel && (
                              <div className="text-xs text-slate-400">
                                <span>{codingTaskSaveLabel}</span>
                                {codingTaskSavedAtLabel && codingTaskSaveState === "saved" ? (
                                  <span>{` · ${codingTaskSavedAtLabel}`}</span>
                                ) : null}
                              </div>
                            )}
                          </div>
                          <div className="mt-4 flex flex-wrap items-center gap-3">
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
                                  className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
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
                              <div className="rounded-full border border-slate-700 bg-slate-900 px-3 py-2 text-xs uppercase tracking-[0.16em] text-slate-300">
                                {t("writtenWorkspace.mode")}
                              </div>
                            )}
                            {isSqlLive && (
                              <div className="rounded-full border border-slate-700 bg-slate-900 px-3 py-2 text-xs uppercase tracking-[0.16em] text-slate-300">
                                SQL
                              </div>
                            )}
                            {!isSqlLive && !isWrittenCommunication && taskWorkspaceSession.preferred_language && (
                              <div className="rounded-full border border-slate-700 bg-slate-900 px-3 py-2 text-xs uppercase tracking-[0.16em] text-slate-300">
                                {t("recommendedLanguage")}: {taskWorkspaceSession.preferred_language}
                              </div>
                            )}
                            <button
                              type="button"
                              onClick={() => void saveCodingTaskDraftArtifact(true)}
                              disabled={!codingTaskDraft.trim() || codingTaskSaveState === "saving"}
                              className="rounded-lg border border-blue-500/30 bg-blue-500/10 px-4 py-2 text-sm font-medium text-blue-300 transition-colors hover:bg-blue-500/20 disabled:cursor-not-allowed disabled:opacity-40"
                            >
                              {codingTaskSaveState === "saving"
                                ? isWrittenCommunication
                                  ? t("writtenWorkspace.saving")
                                  : isSqlLive
                                  ? t("sqlWorkspace.saving")
                                  : t("codingWorkspace.saving")
                                : isWrittenCommunication
                                ? t("writtenWorkspace.save")
                                : isSqlLive
                                ? t("sqlWorkspace.save")
                                : t("codingWorkspace.save")}
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
                            rows={14}
                            className={`mt-4 w-full rounded-xl border border-slate-700 bg-slate-900 px-4 py-3 text-sm leading-6 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                              isWrittenCommunication ? "font-sans" : "font-mono"
                            }`}
                          />
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {structuredInterviewStage && (
                  <div className="rounded-2xl border border-emerald-500/20 bg-emerald-500/10 p-5">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="text-xs font-semibold uppercase tracking-[0.18em] text-emerald-300">
                        {t("structureCardEyebrow")}
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <div className="rounded-full border border-slate-700 bg-slate-900/50 px-3 py-1 text-xs text-slate-300">
                          {t("structureEstimatedDuration", estimatedDuration)}
                        </div>
                        <div className="rounded-full border border-emerald-400/20 bg-slate-900/50 px-3 py-1 text-xs text-slate-200">
                          {t("stageProgress", {
                            current: structuredPhaseProgressCurrent,
                            total: structuredPhaseProgressTotal,
                          })}
                        </div>
                      </div>
                    </div>
                    <div className="mt-3 text-base font-semibold text-white">{structurePhaseLabel}</div>
                    {structuredInterviewStage.resume_anchor && (
                      <div className="mt-3">
                        <div className="text-xs uppercase tracking-[0.14em] text-slate-400">
                          {t("structureResumeAnchor")}
                        </div>
                        <div className="mt-1 text-sm text-slate-200">{structuredInterviewStage.resume_anchor}</div>
                      </div>
                    )}
                    {structuredInterviewStage.verification_target && (
                      <div className="mt-3">
                        <div className="text-xs uppercase tracking-[0.14em] text-slate-400">
                          {t("structureVerificationTarget")}
                        </div>
                        <div className="mt-1 text-sm text-slate-200">{structuredInterviewStage.verification_target}</div>
                      </div>
                    )}
                  </div>
                )}

                {messages.map((msg, i) => (
                  <MessageBubble
                    key={i}
                    msg={msg}
                    onReplay={msg.role === "assistant" ? () => speak(msg.content, interviewLanguage) : undefined}
                    speaking={speaking}
                  />
                ))}
                {sending && <TypingIndicator />}

                {canFinish && (
                  <div className="rounded-2xl border border-blue-500/30 bg-blue-500/10 p-5 text-center">
                    <div className="text-white font-semibold">{t("completeTitle")}</div>
                    <div className="mt-1 text-sm text-slate-300">
                      {t("completeDescription", {
                        answeredCount: candidateAnswerCount,
                        askedCount: assistantAskedCount,
                      })}
                    </div>
                    {uploadStatusLabel && (
                      <div className={`mt-4 text-sm ${recordingUploadState === "failed" ? "text-red-300" : "text-slate-200"}`}>
                        {uploadStatusLabel}
                      </div>
                    )}
                    {(waitingForReport || reportRetrying) && (
                      <div className="mt-4">
                        <span className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium ${reportPhaseToneClass}`}>
                          {reportPhaseLabel}
                        </span>
                      </div>
                    )}
                    {(waitingForReport || reportRetrying) && reportAttempts > 0 && (
                      <div className="mt-4 space-y-1 text-xs text-slate-300">
                        <p>{t("reportAttempts", { count: reportAttempts, max: reportMaxAttempts || reportAttempts })}</p>
                        {reportLastError && <p className="text-yellow-300">{t("lastReportError", { reason: reportLastError })}</p>}
                        {retryCountdownSeconds !== null && retryCountdownSeconds > 0 && <p>{t("nextRetryIn", { seconds: retryCountdownSeconds })}</p>}
                        {pollRefreshCycle > 0 && (
                          <p>{t("statusRefreshCycle", { current: pollRefreshCycle + 1, total: REPORT_SOFT_REFRESH_CYCLES + 1 })}</p>
                        )}
                      </div>
                    )}
                    {error && (
                      <div className="mt-4 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
                        {error}
                      </div>
                    )}
                    <div className="mt-5 flex flex-col items-center gap-3">
                      <button
                        onClick={handleFinish}
                        disabled={finishing || reportRetrying}
                        className="rounded-xl bg-blue-600 px-8 py-2.5 font-semibold text-white transition-colors hover:bg-blue-500 disabled:opacity-50"
                      >
                        {finishing ? (waitingForReport ? t("waiting") : t("generating")) : t("finish")}
                      </button>
                      {error && (
                        <button
                          onClick={handleRetryReport}
                          disabled={finishing || reportRetrying}
                          className="rounded-xl border border-slate-600 px-6 py-2 text-sm text-slate-200 transition-colors hover:border-slate-500 hover:text-white disabled:opacity-50"
                        >
                          {reportRetrying ? t("retryingReport") : t("retryReport")}
                        </button>
                      )}
                    </div>
                  </div>
                )}

                <div ref={bottomRef} />
              </div>
            </div>

            {!canFinish && interview.status === "in_progress" && !(ENABLE_VOICE_INTERVIEW && voiceMode) && (
              <div className="border-t border-slate-800/80 bg-slate-950/80 px-4 py-4 sm:px-6">
                <form
                  className="space-y-3"
                  onSubmit={(e) => {
                    e.preventDefault();
                    void handleSend();
                  }}
                >
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => setAnswerMode("text")}
                        className={`rounded-xl border px-3 py-1.5 text-xs font-medium transition-colors ${
                          !voiceMode
                            ? "border-blue-500/30 bg-blue-500/10 text-blue-300"
                            : "border-slate-700 bg-slate-900/60 text-slate-400 hover:text-slate-200"
                        }`}
                      >
                        {t("textMode")}
                      </button>
                      <button
                        type="button"
                        onClick={() => setAnswerMode("voice")}
                        className={`rounded-xl border px-3 py-1.5 text-xs font-medium transition-colors ${
                          voiceMode
                            ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                            : "border-slate-700 bg-slate-900/60 text-slate-400 hover:text-slate-200"
                        }`}
                      >
                        {t("voiceMode")}
                      </button>
                    </div>
                    {voiceMode && <p className="text-xs text-slate-500">{t("voiceHint")}</p>}
                  </div>

                  {(voiceMode || latestTranscript) && (
                    <div className="rounded-xl border border-slate-800 bg-slate-900/70 px-4 py-3 text-sm text-slate-300">
                      {latestTranscript ? <p>{t("latestTranscript")}</p> : <p>{t("voiceHint")}</p>}
                    </div>
                  )}

                  <div className="flex flex-col gap-3 sm:flex-row">
                    <textarea
                      value={input}
                      onChange={(e) => setInput(e.target.value)}
                      onPaste={() => {
                        pasteCountRef.current++;
                        trackProctoringEvent({
                          event_type: "paste_detected",
                          severity: PROCTORING_POLICY_MODE === "strict_flagging" ? "medium" : "info",
                          details: { count: pasteCountRef.current },
                        });
                      }}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && !e.shiftKey) {
                          e.preventDefault();
                          handleSend();
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
                          : voiceMode && voiceState === "recording"
                          ? t("placeholderListening")
                          : voiceMode && voiceState === "transcribing"
                          ? t("placeholderTranscribing")
                          : voiceMode
                          ? t("placeholderVoice")
                          : t("placeholderText")
                      }
                      rows={taskWorkspaceModuleType ? 5 : 3}
                      className={`flex-1 rounded-2xl border border-slate-700 bg-slate-900 px-4 py-3 text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50 ${
                        taskWorkspaceModuleType ? "resize-y leading-6" : "resize-none"
                      }`}
                    />
                    <div className="flex gap-3 sm:flex-col">
                      {voiceMode && (
                        <button
                          type="button"
                          onMouseDown={startVoice}
                          onMouseUp={stopVoice}
                          onTouchStart={startVoice}
                          onTouchEnd={stopVoice}
                          disabled={sending || voiceState === "transcribing"}
                          title={t("tooltips.holdToSpeak")}
                          className={`rounded-2xl border px-4 py-3 text-sm font-medium transition-colors ${
                            voiceState === "recording"
                              ? "animate-pulse border-red-500/50 bg-red-500/20 text-red-300"
                              : voiceState === "transcribing"
                              ? "border-slate-700 bg-slate-800 text-slate-400 opacity-60"
                              : voiceState === "error"
                              ? "border-red-500/30 bg-red-500/10 text-red-300"
                              : "border-slate-700 bg-slate-800 text-slate-200 hover:border-slate-600"
                          }`}
                        >
                          {voiceState === "recording" ? "REC" : voiceState === "transcribing" ? "..." : "MIC"}
                        </button>
                      )}
                      <button
                        type="submit"
                        disabled={!input.trim() || sending}
                        className="rounded-2xl bg-blue-600 px-5 py-3 text-sm font-semibold text-white transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-40"
                      >
                        {sending ? "..." : t("send")}
                      </button>
                    </div>
                  </div>
                </form>
              </div>
            )}
          </div>
        </section>
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
                  onChange={(e) => setPracticalAnswer(e.target.value)}
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
            <div className="flex items-center justify-between gap-4 border-t border-slate-800 px-6 py-4">
              <button
                type="button"
                onClick={() => {
                  setPracticalModalOpen(false);
                  setPracticalTask(null);
                  setPracticalAnswer("");
                }}
                disabled={practicalSubmitting}
                className="rounded-xl border border-slate-700 px-5 py-2.5 text-sm text-slate-300 transition-colors hover:border-slate-600 hover:text-white disabled:opacity-40"
              >
                Пропустить
              </button>
              <button
                type="button"
                onClick={() => void handlePracticalSubmit()}
                disabled={practicalSubmitting || !practicalAnswer.trim()}
                className="rounded-xl bg-amber-600 px-8 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-amber-500 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {practicalSubmitting ? "Отправляю..." : "Отправить решение"}
              </button>
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

function StageRail({ items }: { items: StageRailItem[] }) {
  if (!items.length) return null;

  return (
    <div className="mt-4 grid gap-2">
      {items.map((item) => {
        const toneClass =
          item.state === "done"
            ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-200"
            : item.state === "current"
            ? "border-cyan-500/20 bg-cyan-500/10 text-cyan-100"
            : "border-slate-800 bg-slate-950/50 text-slate-500";
        const dotClass =
          item.state === "done"
            ? "bg-emerald-400"
            : item.state === "current"
            ? "bg-cyan-400"
            : "bg-slate-600";

        return (
          <div key={item.key} className={`flex items-center gap-3 rounded-xl border px-3 py-2 ${toneClass}`}>
            <span className={`h-2.5 w-2.5 rounded-full ${dotClass}`} />
            <span className="text-sm">{item.label}</span>
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
