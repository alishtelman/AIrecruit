"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Link, useRouter } from "@/i18n/navigation";
import { companyApi } from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";
import type { InterviewReplay, ReplayTurn } from "@/lib/types";

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

export default function InterviewReplayPage() {
  const t = useTranslations("companyReplay");
  const startT = useTranslations("interviewStart");
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { loading: authLoading } = useAuth("/company/login");
  const [replay, setReplay] = useState<InterviewReplay | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [expandedTurn, setExpandedTurn] = useState<number | null>(0);

  useEffect(() => {
    if (!id || authLoading) return;
    companyApi.getInterviewReplay(id)
      .then(setReplay)
      .catch((err) => setError(err.message ?? t("errors.load")))
      .finally(() => setLoading(false));
  }, [id, authLoading]);

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

  return (
    <div className="min-h-screen bg-slate-900 px-4 py-8">
      <div className="max-w-3xl mx-auto">
        <button
          onClick={() => router.back()}
          className="text-slate-400 hover:text-white text-sm mb-6 inline-block transition-colors"
        >
          ← {t("back")}
        </button>

        <div className="mb-6">
          <h1 className="text-2xl font-bold text-white">{t("title")}</h1>
          <p className="text-slate-400 mt-1">
            {replay.candidate_name} · {startT(`roles.${replay.target_role}`)}
          </p>
          {replay.completed_at && (
            <p className="text-slate-500 text-sm mt-0.5">
              {t("completed", {date: new Date(replay.completed_at).toLocaleDateString()})}
            </p>
          )}
          <p className="text-slate-500 text-xs mt-1">{t("questionCount", {count: replay.turns.length})}</p>
        </div>

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
      </div>
    </div>
  );
}
