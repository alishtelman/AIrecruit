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
} from "@/lib/types";

const REPORT_POLL_INTERVAL_MS = 1500;
const REPORT_POLL_TIMEOUT_MS = 120000;
const REPORT_SOFT_REFRESH_CYCLES = 2;
const REPORT_SOFT_REFRESH_DELAY_MS = 1000;
const PROCTORING_POLICY_MODE =
  process.env.NEXT_PUBLIC_PROCTORING_POLICY_MODE === "strict_flagging"
    ? "strict_flagging"
    : "observe_only";
const CODING_TASK_LANGUAGES = ["python", "typescript", "javascript", "go", "java", "sql", "other"] as const;

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
  const [answerMode, setAnswerMode] = useState<"text" | "voice">("text");
  const [latestTranscript, setLatestTranscript] = useState("");
  const [recordingUploadState, setRecordingUploadState] = useState<"idle" | "uploading" | "uploaded" | "failed" | "skipped">("idle");
  const [moduleSession, setModuleSession] = useState<InterviewModuleSession | null>(null);
  const [codingTaskDraft, setCodingTaskDraft] = useState("");
  const [codingTaskLanguage, setCodingTaskLanguage] = useState<string>("python");
  const [codingTaskSaveState, setCodingTaskSaveState] = useState<"idle" | "saving" | "saved" | "failed">("idle");
  const [codingTaskSavedAt, setCodingTaskSavedAt] = useState<string | null>(null);
  const [codingTaskDirty, setCodingTaskDirty] = useState(false);
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
  const { state: voiceState, start: startVoice, stop: stopVoice, errorMessage: voiceError, clearError: clearVoiceError } = useVoiceInput({
    onTranscript: (text) => {
      setLatestTranscript(text);
      setInput((prev) => (prev ? `${prev} ${text}` : text));
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
    moduleSession?.module_type === "coding_task" || moduleSession?.module_type === "sql_live"
      ? moduleSession.module_type
      : null;
  const isSqlLive = taskWorkspaceModuleType === "sql_live";

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
      const saved = await interviewApi.saveCodingTaskArtifact(id, {
        language: isSqlLive ? "sql" : codingTaskLanguage,
        code: codingTaskDraft,
      });
      setCodingTaskDraft(saved.code);
      setCodingTaskLanguage(saved.language ?? (isSqlLive ? "sql" : "python"));
      setCodingTaskSavedAt(saved.updated_at ?? null);
      setCodingTaskDirty(false);
      setCodingTaskSaveState("saved");
      return true;
    } catch (err: unknown) {
      setCodingTaskSaveState("failed");
      setError(
        err instanceof Error
          ? err.message
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
        setMessages(data.messages.filter((m) => m.role !== "system"));
        setQuestionCount(data.question_count);
        setMaxQuestions(data.max_questions);
        setModuleSession(data.module_session ?? null);
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
      setCodingTaskLanguage(taskWorkspaceModuleType === "sql_live" ? "sql" : "python");
      setCodingTaskSavedAt(null);
      setCodingTaskSaveState("idle");
      setCodingTaskDirty(false);
      return;
    }

    let cancelled = false;
    interviewApi
      .getCodingTaskArtifact(id)
      .then((artifact) => {
        if (cancelled) return;
        setCodingTaskDraft(artifact.code ?? "");
        setCodingTaskLanguage(artifact.language ?? (taskWorkspaceModuleType === "sql_live" ? "sql" : "python"));
        setCodingTaskSavedAt(artifact.updated_at ?? null);
        setCodingTaskSaveState(artifact.code ? "saved" : "idle");
        setCodingTaskDirty(false);
      })
      .catch(() => {
        if (cancelled) return;
        setCodingTaskDraft("");
        setCodingTaskLanguage(taskWorkspaceModuleType === "sql_live" ? "sql" : "python");
        setCodingTaskSavedAt(null);
        setCodingTaskSaveState("idle");
        setCodingTaskDirty(false);
      });

    return () => {
      cancelled = true;
    };
  }, [id, taskWorkspaceModuleType]);

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

  async function handleSend() {
    if (!input.trim() || sending || !id) return;
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
      setIsFollowup(res.is_followup ?? false);
      setQuestionType(res.question_type ?? "main");
      setModuleSession(res.module_session ?? null);

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
      setError(err instanceof Error ? err.message : t("sendFailed"));
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
    setReportStatus(null);
    setPollRefreshCycle(0);
    setError("");
    try {
      if (taskWorkspaceModuleType) {
        const artifactSaved = await saveCodingTaskDraftArtifact(true);
        if (!artifactSaved) {
          throw new Error(isSqlLive ? t("sqlWorkspace.saveFailed") : t("codingWorkspace.saveFailed"));
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
  const progress = Math.round((questionCount / maxQuestions) * 100);
  const voiceMode = answerMode === "voice";
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
  const codingTaskSession = moduleSession?.module_type === "coding_task" ? moduleSession : null;
  const sqlLiveSession = moduleSession?.module_type === "sql_live" ? moduleSession : null;
  const taskWorkspaceSession = codingTaskSession || sqlLiveSession;
  const codingTaskSaveLabel =
    codingTaskSaveState === "saving"
      ? taskWorkspaceModuleType === "sql_live"
        ? t("sqlWorkspace.saving")
        : t("codingWorkspace.saving")
      : codingTaskSaveState === "saved"
      ? taskWorkspaceModuleType === "sql_live"
        ? t("sqlWorkspace.saved")
        : t("codingWorkspace.saved")
      : codingTaskSaveState === "failed"
      ? taskWorkspaceModuleType === "sql_live"
        ? t("sqlWorkspace.failed")
        : t("codingWorkspace.failed")
      : codingTaskDirty
      ? taskWorkspaceModuleType === "sql_live"
        ? t("sqlWorkspace.unsaved")
        : t("codingWorkspace.unsaved")
      : null;
  const codingTaskSavedAtLabel = codingTaskSavedAt
    ? new Date(codingTaskSavedAt).toLocaleTimeString()
    : null;

  return (
    <div className="min-h-screen bg-slate-900 flex flex-col">
      {/* Header */}
      <header className="border-b border-slate-800 px-6 py-4 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-4">
          <Link href="/candidate/reports" className="text-slate-500 hover:text-slate-300 text-sm transition-colors">
            ←
          </Link>
          <div className="flex items-center gap-3">
            <span className="text-white font-semibold">{t("interviewTitle", {role: roleLabel})}</span>
            {isFollowup ? (
              <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-purple-500/15 border border-purple-500/30 text-purple-300 font-medium">
                {questionType === "verification" ? t("verification") : questionType === "deep_technical" ? t("deepDive") : t("followup")}
              </span>
            ) : (
              <span className="text-slate-400 text-sm">
                {t("question", {current: questionCount, total: maxQuestions})}
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-3">
          <LocaleSwitcher />
          {/* Webcam preview */}
          {interview.status === "in_progress" && (
            <div className="relative w-[120px] h-[90px] rounded-lg overflow-hidden border border-slate-700 bg-slate-900">
              <video
                ref={previewRef}
                muted
                autoPlay
                playsInline
                className={`w-full h-full object-cover transition-opacity ${
                  cameraPreviewReady ? "opacity-100" : "opacity-0"
                }`}
              />
              {!cameraPreviewReady && (
                <div className="absolute inset-0 flex items-center justify-center text-[11px] text-slate-400 px-2 text-center">
                  {isRecording ? t("cameraPreviewStarting") : t("cameraPreviewOff")}
                </div>
              )}
            </div>
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
                title={isScreenSharing ? t("tooltips.screenRecorded") : t("tooltips.screenInactive")}
              >
                {isScreenSharing ? t("screenOn") : t("screenOff")}
              </span>
              {faceModelLoaded && (
                <span
                  className={`text-xs font-medium ${
                    faceAwayPct !== null && faceAwayPct > 0.3
                      ? "text-orange-400"
                      : "text-green-400"
                  }`}
                  title={t("tooltips.faceDetection", {
                    status: faceAwayPct !== null ? `${Math.round(faceAwayPct * 100)}% away` : t("tooltips.detecting"),
                  })}
                >
                  {faceAwayPct !== null && faceAwayPct > 0.3 ? t("lookAtCamera") : t("face")}
                </span>
              )}
              {speechMonitoringSupported && (
                <span
                  className={`text-xs font-medium ${
                    isSpeechActive ? "text-emerald-400" : "text-slate-400"
                  }`}
                  title={t("tooltips.speechMonitoring", {
                    activity:
                      speechActivityPct !== null ? `${Math.round(speechActivityPct * 100)}%` : t("tooltips.detecting"),
                  })}
                >
                  {isSpeechActive ? t("speechDetected") : t("speechMonitoring")}
                </span>
              )}
            </span>
          )}
          {!isRecording && interview.status === "in_progress" && (
            <span className="text-xs px-3 py-1.5 rounded-lg border border-yellow-500/40 bg-yellow-500/10 text-yellow-300">
              {t("recordingRequired")}
            </span>
          )}
          {/* Resume panel toggle */}
          {resumeText && (
            <button
              onClick={() => setResumeOpen((v) => !v)}
              title={t("tooltips.toggleResume")}
              className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${
                resumeOpen
                  ? "bg-purple-500/15 border-purple-500/30 text-purple-400"
                  : "bg-slate-700/50 border-slate-600 text-slate-400 hover:text-slate-300"
              }`}
            >
              {t("resume")}
            </button>
          )}
          {/* TTS toggle */}
          <button
            onClick={toggleTTS}
            title={ttsEnabled ? t("tooltips.muteVoice") : t("tooltips.enableVoice")}
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
              <span>{ttsEnabled ? t("on") : t("off")}</span>
            )}
            {ttsEnabled ? t("voiceOn") : t("voiceOff")}
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
          {(systemDesignSession || taskWorkspaceSession) && (
            <div className="rounded-2xl border border-blue-500/20 bg-blue-500/10 p-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-300">
                  {(systemDesignSession || taskWorkspaceSession)?.module_title || t("moduleCardEyebrow")}
                </div>
                <div className="rounded-full border border-blue-400/20 bg-slate-900/50 px-3 py-1 text-xs text-slate-200">
                  {t("stageProgress", {
                    current: ((systemDesignSession || taskWorkspaceSession)?.stage_index ?? 0) + 1,
                    total: Math.max((systemDesignSession || taskWorkspaceSession)?.stage_count ?? 0, 1),
                  })}
                </div>
              </div>
              {(systemDesignSession || taskWorkspaceSession)?.scenario_title && (
                <div className="mt-3">
                  <div className="text-xs uppercase tracking-[0.14em] text-slate-400">
                    {taskWorkspaceSession ? t("taskLabel") : t("scenarioLabel")}
                  </div>
                  <div className="mt-1 text-sm font-medium text-white">
                    {(systemDesignSession || taskWorkspaceSession)?.scenario_title}
                  </div>
                </div>
              )}
              {(systemDesignSession || taskWorkspaceSession)?.stage_title && (
                <div className="mt-3">
                  <div className="text-xs uppercase tracking-[0.14em] text-slate-400">{t("stageLabel")}</div>
                  <div className="mt-1 text-sm text-slate-200">{(systemDesignSession || taskWorkspaceSession)?.stage_title}</div>
                </div>
              )}
              {(systemDesignSession || taskWorkspaceSession)?.scenario_prompt && (
                <p className="mt-3 text-sm leading-6 text-slate-300">{(systemDesignSession || taskWorkspaceSession)?.scenario_prompt}</p>
              )}
              {taskWorkspaceSession && (
                <div className="mt-4 space-y-3">
                  <div className="rounded-xl border border-slate-700/80 bg-slate-950/40 px-4 py-3 text-sm text-slate-300">
                    {isSqlLive ? t("sqlTaskHint") : t("codingTaskHint")}
                  </div>
                  <div className="rounded-2xl border border-slate-700 bg-slate-950/70 p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
                          {isSqlLive ? t("sqlWorkspace.title") : t("codingWorkspace.title")}
                        </div>
                        <p className="mt-1 text-sm text-slate-300">
                          {isSqlLive ? t("sqlWorkspace.description") : t("codingWorkspace.description")}
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
                      {!isSqlLive && (
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
                      {isSqlLive && (
                        <div className="rounded-full border border-slate-700 bg-slate-900 px-3 py-2 text-xs uppercase tracking-[0.16em] text-slate-300">
                          SQL
                        </div>
                      )}
                      <button
                        type="button"
                        onClick={() => void saveCodingTaskDraftArtifact(true)}
                        disabled={!codingTaskDraft.trim() || codingTaskSaveState === "saving"}
                        className="rounded-lg border border-blue-500/30 bg-blue-500/10 px-4 py-2 text-sm font-medium text-blue-300 transition-colors hover:bg-blue-500/20 disabled:cursor-not-allowed disabled:opacity-40"
                      >
                        {codingTaskSaveState === "saving"
                          ? isSqlLive
                            ? t("sqlWorkspace.saving")
                            : t("codingWorkspace.saving")
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
                          details: { count: pasteCountRef.current, source: "coding_workspace" },
                        });
                      }}
                      placeholder={isSqlLive ? t("sqlWorkspace.placeholder") : t("codingWorkspace.placeholder")}
                      rows={14}
                      className="mt-4 w-full rounded-xl border border-slate-700 bg-slate-900 px-4 py-3 font-mono text-sm leading-6 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </div>
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
          <div ref={bottomRef} />
        </div>

        {/* Resume panel */}
        {resumeOpen && resumeText && (
          <aside className="fixed right-0 top-0 h-full w-80 bg-slate-800 border-l border-slate-700 overflow-y-auto p-4 z-10">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-white font-semibold text-sm">{t("resume")}</h3>
              <button
                onClick={() => setResumeOpen(false)}
                className="text-slate-400 hover:text-white text-lg leading-none"
              >
                ×
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

      {!isRecording && interview.status === "in_progress" && (
        <div className="max-w-2xl w-full mx-auto px-4 pb-4">
          <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-xl p-5">
            <div className="text-yellow-300 font-semibold mb-1">{t("recordingRequired")}</div>
            <div className="text-slate-300 text-sm">
              {t("recordingDescription")}
            </div>
          </div>
        </div>
      )}

      {/* Finish CTA */}
      {canFinish && (
        <div className="max-w-2xl w-full mx-auto px-4 pb-4">
          <div className="bg-blue-500/10 border border-blue-500/30 rounded-xl p-5 text-center">
            <div className="text-white font-semibold mb-1">{t("completeTitle")}</div>
            <div className="text-slate-400 text-sm mb-4">
              {t("completeDescription", {count: maxQuestions})}
            </div>
            {uploadStatusLabel && (
              <div className={`mb-4 text-sm ${recordingUploadState === "failed" ? "text-red-400" : "text-slate-300"}`}>
                {uploadStatusLabel}
              </div>
            )}
            {(waitingForReport || reportRetrying) && (
              <div className="mb-3">
                <span className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium ${reportPhaseToneClass}`}>
                  {reportPhaseLabel}
                </span>
              </div>
            )}
            {(waitingForReport || reportRetrying) && reportAttempts > 0 && (
              <div className="mb-3 text-xs text-slate-300 space-y-1">
                <p>{t("reportAttempts", {count: reportAttempts, max: reportMaxAttempts || reportAttempts})}</p>
                {reportLastError && (
                  <p className="text-yellow-300">{t("lastReportError", {reason: reportLastError})}</p>
                )}
                {retryCountdownSeconds !== null && retryCountdownSeconds > 0 && (
                  <p>{t("nextRetryIn", {seconds: retryCountdownSeconds})}</p>
                )}
                {pollRefreshCycle > 0 && (
                  <p>{t("statusRefreshCycle", {current: pollRefreshCycle + 1, total: REPORT_SOFT_REFRESH_CYCLES + 1})}</p>
                )}
              </div>
            )}
            <button
              onClick={handleFinish}
              disabled={finishing || reportRetrying}
              className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white font-semibold px-8 py-2.5 rounded-lg transition-colors"
            >
              {finishing ? (waitingForReport ? t("waiting") : t("generating")) : t("finish")}
            </button>
            {error && (
              <button
                onClick={handleRetryReport}
                disabled={finishing || reportRetrying}
                className="mt-3 border border-slate-600 text-slate-200 hover:border-slate-500 hover:text-white disabled:opacity-50 px-6 py-2 rounded-lg text-sm transition-colors"
              >
                {reportRetrying ? t("retryingReport") : t("retryReport")}
              </button>
            )}
          </div>
        </div>
      )}

      {/* Full-screen finishing overlay */}
      {(finishing || reportRetrying) && (
        <div className="fixed inset-0 bg-slate-900/90 backdrop-blur-sm flex flex-col items-center justify-center z-50">
          <div className="flex flex-col items-center gap-6 text-center px-8">
            <div className="relative w-16 h-16">
              <div className="absolute inset-0 rounded-full border-4 border-slate-700" />
              <div className="absolute inset-0 rounded-full border-4 border-t-blue-500 animate-spin" />
            </div>
            <div>
              <p className="text-white font-semibold text-lg">
                {waitingForReport || reportRetrying ? t("analyzing") : t("finishing")}
              </p>
              <p className="text-slate-400 text-sm mt-1">
                {waitingForReport || reportRetrying
                  ? t("analysisDuration")
                  : t("savingResponses")}
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

      {/* Input */}
      {!canFinish && interview.status === "in_progress" && (
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
                  {t("textMode")}
                </button>
                <button
                  onClick={() => setAnswerMode("voice")}
                  className={`rounded-lg border px-3 py-1.5 text-xs transition-colors ${
                    voiceMode
                      ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                      : "border-slate-700 text-slate-400 hover:text-slate-200"
                  }`}
                >
                  {t("voiceMode")}
                </button>
              </div>
              {voiceMode && (
                <p className="text-xs text-slate-500">
                  {t("voiceHint")}
                </p>
              )}
            </div>

            {(voiceMode || voiceError || recordingError || latestTranscript) && (
              <div className="rounded-xl border border-slate-800 bg-slate-800/60 px-4 py-3 text-sm">
                {latestTranscript && (
                  <p className="text-slate-300">
                    {t("latestTranscript")}
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
                  ? isSqlLive
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
              rows={taskWorkspaceModuleType ? 4 : 2}
              className={`flex-1 bg-slate-800 border border-slate-700 text-white rounded-xl px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder-slate-500 disabled:opacity-50 disabled:cursor-not-allowed ${
                taskWorkspaceModuleType ? "resize-y leading-6" : "resize-none"
              }`}
            />
            {voiceMode && (
              <button
                onMouseDown={startVoice}
                onMouseUp={stopVoice}
                onTouchStart={startVoice}
                onTouchEnd={stopVoice}
                disabled={sending || voiceState === "transcribing"}
                title={t("tooltips.holdToSpeak")}
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
                {voiceState === "recording" ? "REC" : voiceState === "transcribing" ? "..." : "MIC"}
              </button>
            )}
            <button
              onClick={handleSend}
              disabled={!input.trim() || sending}
              className="bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white px-5 rounded-xl transition-colors font-medium"
            >
              {sending ? "..." : t("send")}
            </button>
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
