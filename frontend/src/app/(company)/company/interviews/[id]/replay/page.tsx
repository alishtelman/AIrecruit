"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useRouter } from "@/i18n/navigation";
import { CompanyWorkspaceHeader } from "@/components/company-workspace-header";
import { companyApi } from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";
import type { InterviewReplay, ReplayTurn, TranscriptBlock } from "@/lib/types";

const DEPTH_COLORS: Record<string, string> = {
  expert: "text-green-400 bg-green-500/10",
  strong: "text-blue-400 bg-blue-500/10",
  adequate: "text-yellow-400 bg-yellow-500/10",
  surface: "text-orange-400 bg-orange-500/10",
  none: "text-red-400 bg-red-500/10",
};

function TurnCard({ turn, expanded, onToggle }: {
  turn: ReplayTurn;
  expanded: boolean;
  onToggle: () => void;
}) {
  const reportT = useTranslations("report");
  const qa = turn.analysis;
  const qualityColor = qa
    ? qa.answer_quality >= 7 ? "text-green-400" : qa.answer_quality >= 5 ? "text-yellow-400" : "text-red-400"
    : "text-slate-400";

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-start justify-between px-5 py-4 text-left hover:bg-slate-750 transition-colors"
      >
        <div className="flex-1 min-w-0 pr-4">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-slate-500 text-xs font-mono shrink-0">Q{turn.question_number}</span>
            {turn.stage_title && (
              <span className="text-xs px-2 py-0.5 rounded bg-violet-500/10 text-violet-300 border border-violet-500/20">
                {turn.stage_title}
              </span>
            )}
            {qa?.targeted_competencies && qa.targeted_competencies.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {qa.targeted_competencies.map((c, i) => (
                  <span key={i} className="text-xs px-1.5 py-0.5 bg-blue-500/10 text-blue-400 rounded">
                    {c}
                  </span>
                ))}
              </div>
            )}
          </div>
          <p className="text-slate-300 text-sm font-medium line-clamp-2">{turn.question}</p>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          {qa && (
            <>
              <span className={`text-xs px-2 py-0.5 rounded capitalize ${DEPTH_COLORS[qa.depth] ?? "text-slate-400 bg-slate-700"}`}>
                {reportT(`depth.${qa.depth}`)}
              </span>
              <span className={`text-sm font-bold ${qualityColor}`}>{qa.answer_quality.toFixed(1)}</span>
            </>
          )}
          <span className="text-slate-500 text-xs">{expanded ? "▲" : "▼"}</span>
        </div>
      </button>

      {expanded && (
        <div className="border-t border-slate-700 px-5 py-4 space-y-4">
          {/* Question */}
          <div>
            <p className="text-slate-500 text-xs uppercase tracking-wide mb-1">{reportT("question")}</p>
            <p className="text-slate-300 text-sm">{turn.question}</p>
            {turn.question_time && (
              <p className="text-slate-600 text-xs mt-1">{new Date(turn.question_time).toLocaleTimeString()}</p>
            )}
          </div>

          {/* Answer */}
          <div>
            <p className="text-slate-500 text-xs uppercase tracking-wide mb-1">{reportT("answer")}</p>
            <p className="text-slate-200 text-sm whitespace-pre-wrap">{turn.answer || <span className="text-slate-500 italic">{reportT("empty")}</span>}</p>
            {turn.answer_time && (
              <p className="text-slate-600 text-xs mt-1">{new Date(turn.answer_time).toLocaleTimeString()}</p>
            )}
          </div>

          {/* Analysis */}
          {qa && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2 border-t border-slate-700">
              {qa.evidence && (
                <div>
                  <p className="text-slate-500 text-xs uppercase tracking-wide mb-1">{reportT("evidence")}</p>
                  <p className="text-slate-400 text-xs">{qa.evidence}</p>
                </div>
              )}
              {qa.skills_mentioned && qa.skills_mentioned.length > 0 && (
                <div>
                  <p className="text-slate-500 text-xs uppercase tracking-wide mb-1">{reportT("skillsMentioned")}</p>
                  <div className="flex flex-wrap gap-1">
                    {qa.skills_mentioned.map((s, i) => (
                      <span key={i} className="text-xs px-2 py-0.5 bg-slate-700 text-slate-300 rounded">
                        {s.skill} <span className="text-slate-500">({s.proficiency})</span>
                      </span>
                    ))}
                  </div>
                </div>
              )}
              {qa.red_flags && qa.red_flags.length > 0 && (
                <div className="sm:col-span-2">
                  <p className="text-slate-500 text-xs uppercase tracking-wide mb-1">{reportT("redFlags")}</p>
                  <ul className="space-y-1">
                    {qa.red_flags.map((rf, i) => (
                      <li key={i} className="text-red-400 text-xs">{reportT("alert")} {rf}</li>
                    ))}
                  </ul>
                </div>
              )}
              <div className="sm:col-span-2 flex flex-wrap gap-4 text-xs text-slate-500">
                <span>{reportT("specificity")}: <span className="text-slate-300 capitalize">{reportT(`specificityValue.${qa.specificity}`)}</span></span>
                <span>{reportT("depthLabel")}: <span className={`capitalize ${DEPTH_COLORS[qa.depth]?.split(" ")[0]}`}>{reportT(`depth.${qa.depth}`)}</span></span>
                {qa.ai_likelihood != null && qa.ai_likelihood > 0.1 && (
                  <span className={`font-medium ${qa.ai_likelihood >= 0.7 ? "text-red-400" : qa.ai_likelihood >= 0.4 ? "text-orange-400" : "text-yellow-400"}`}>
                    {reportT("aiLikelihood")}: {Math.round(qa.ai_likelihood * 100)}%
                  </span>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function buildFallbackTranscriptBlocks(turns: ReplayTurn[]): TranscriptBlock[] {
  return turns.flatMap((turn) => [
    {
      speaker: "interviewer",
      kind: "question",
      turn_number: turn.question_number,
      text: turn.question,
      timestamp: turn.question_time,
    },
    {
      speaker: "candidate",
      kind: "answer",
      turn_number: turn.question_number,
      text: turn.answer,
      timestamp: turn.answer_time,
    },
  ]);
}

function buildFallbackTranscriptText(blocks: TranscriptBlock[]): string {
  return blocks
    .flatMap((block) => {
      const speakerLabel = block.speaker === "interviewer" ? "Interviewer" : "Candidate";
      const kindLabel = block.kind === "question" ? `Q${block.turn_number}` : `A${block.turn_number}`;
      const header = block.timestamp
        ? `${kindLabel} | ${speakerLabel} | ${block.timestamp}`
        : `${kindLabel} | ${speakerLabel}`;
      return [header, block.text.trim() || "[no answer captured]", ""];
    })
    .join("\n")
    .trim();
}

function TranscriptBlockCard({ block }: { block: TranscriptBlock }) {
  const t = useTranslations("companyReplay");
  const isInterviewer = block.speaker === "interviewer";
  const badgeClass = isInterviewer
    ? "border-blue-500/30 bg-blue-500/10 text-blue-300"
    : "border-emerald-500/30 bg-emerald-500/10 text-emerald-300";
  const text = block.text.trim() || t("emptyAnswer");

  return (
    <div className="rounded-xl border border-slate-700 bg-slate-800 p-5">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`rounded-full border px-2.5 py-1 text-xs font-medium ${badgeClass}`}>
          {t(`speakers.${block.speaker}`)}
        </span>
        <span className="text-xs font-mono text-slate-500">
          {block.kind === "question" ? `Q${block.turn_number}` : `A${block.turn_number}`}
        </span>
        <span className="text-xs text-slate-500">{t(`kinds.${block.kind}`)}</span>
        {block.timestamp ? (
          <span className="text-xs text-slate-600">{new Date(block.timestamp).toLocaleTimeString()}</span>
        ) : null}
      </div>
      <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-200">{text}</p>
    </div>
  );
}

export default function InterviewReplayPage() {
  const t = useTranslations("companyReplay");
  const startT = useTranslations("interviewStart");
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { loading: authLoading, logout } = useAuth({
    redirectTo: "/company/login",
    allowedRoles: ["company_admin", "company_member"],
    unauthorizedRedirectTo: "/candidate/dashboard",
  });
  const [replay, setReplay] = useState<InterviewReplay | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [expandedTurn, setExpandedTurn] = useState<number | null>(0);
  const [mode, setMode] = useState<"replay" | "transcript">("replay");
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");

  useEffect(() => {
    if (!id || authLoading) return;
    companyApi.getInterviewReplay(id)
      .then(setReplay)
      .catch((err) => setError(err.message ?? t("errors.load")))
      .finally(() => setLoading(false));
  }, [id, authLoading, t]);

  if (authLoading || loading) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="text-slate-400">{t("loading")}</div>
      </div>
    );
  }

  if (error || !replay) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center px-4">
        <div className="text-center">
          <div className="text-red-400 mb-4">{error || t("errors.notFound")}</div>
          <button onClick={() => router.back()} className="text-blue-400 hover:underline text-sm">← {t("goBack")}</button>
        </div>
      </div>
    );
  }

  const transcriptBlocks = replay.transcript_blocks && replay.transcript_blocks.length > 0
    ? replay.transcript_blocks
    : buildFallbackTranscriptBlocks(replay.turns);
  const transcriptText = replay.transcript_text?.trim() || buildFallbackTranscriptText(transcriptBlocks);

  async function handleCopyTranscript() {
    try {
      await navigator.clipboard.writeText(transcriptText);
      setCopyState("copied");
      window.setTimeout(() => setCopyState("idle"), 2000);
    } catch {
      setCopyState("failed");
      window.setTimeout(() => setCopyState("idle"), 2000);
    }
  }

  function handleDownloadTranscript() {
    if (!replay) {
      return;
    }
    const blob = new Blob([transcriptText], { type: "text/plain;charset=utf-8" });
    const url = window.URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `interview-transcript-${replay.interview_id}.txt`;
    anchor.click();
    window.URL.revokeObjectURL(url);
  }

  return (
    <div className="ai-shell min-h-screen px-4 py-10">
      <div className="ai-section max-w-4xl mx-auto">
        <CompanyWorkspaceHeader onLogout={logout} />
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
          <button
            onClick={() => router.back()}
            className="text-slate-400 hover:text-white text-sm inline-block transition-colors"
          >
            ← {t("back")}
          </button>
        </div>

        <div className="ai-panel-strong mb-6 rounded-[2rem] p-7">
          <h1 className="text-3xl font-semibold tracking-[-0.03em] text-white">{t("title")}</h1>
          <p className="mt-1 text-slate-400">
            {replay.candidate_name} · {startT(`roles.${replay.target_role}`)}
          </p>
          {replay.completed_at && (
            <p className="mt-1 text-sm text-slate-500">
              {t("completed", {date: new Date(replay.completed_at).toLocaleDateString()})}
            </p>
          )}
          <p className="mt-2 text-xs text-slate-500">{t("questionCount", {count: replay.turns.length})}</p>
          {replay.module_session?.scenario_title && (
            <p className="mt-2 text-sm text-slate-300">
              {replay.module_session.module_title || "Module"} · {replay.module_session.scenario_title}
            </p>
          )}
          <div className="mt-5 flex flex-wrap items-center gap-3">
            <div className="inline-flex rounded-xl border border-slate-700 bg-slate-900/80 p-1">
              <button
                onClick={() => setMode("replay")}
                className={`rounded-lg px-3 py-1.5 text-sm transition-colors ${
                  mode === "replay" ? "bg-slate-700 text-white" : "text-slate-400 hover:text-slate-200"
                }`}
              >
                {t("modes.replay")}
              </button>
              <button
                onClick={() => setMode("transcript")}
                className={`rounded-lg px-3 py-1.5 text-sm transition-colors ${
                  mode === "transcript" ? "bg-slate-700 text-white" : "text-slate-400 hover:text-slate-200"
                }`}
              >
                {t("modes.transcript")}
              </button>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button
                onClick={handleCopyTranscript}
                className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-200 transition-colors hover:border-slate-500 hover:text-white"
              >
                {copyState === "copied"
                  ? t("actions.copied")
                  : copyState === "failed"
                  ? t("actions.copyFailed")
                  : t("actions.copyTranscript")}
              </button>
              <button
                onClick={handleDownloadTranscript}
                className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-200 transition-colors hover:border-slate-500 hover:text-white"
              >
                {t("actions.downloadTranscript")}
              </button>
            </div>
          </div>
        </div>

        {mode === "replay" ? (
          <div className="space-y-3">
            {replay.turns.map((turn, i) => (
              <TurnCard
                key={turn.question_number}
                turn={turn}
                expanded={expandedTurn === i}
                onToggle={() => setExpandedTurn(expandedTurn === i ? null : i)}
              />
            ))}
          </div>
        ) : (
          <div className="space-y-3">
            <div className="rounded-xl border border-slate-700 bg-slate-800/80 p-4 text-sm text-slate-400">
              {t("transcriptHint")}
            </div>
            {transcriptBlocks.map((block, index) => (
              <TranscriptBlockCard
                key={`${block.kind}-${block.turn_number}-${index}`}
                block={block}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
