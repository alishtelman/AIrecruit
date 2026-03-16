"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { companyApi } from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";
import type { InterviewReplay, ReplayTurn } from "@/lib/types";

const ROLE_LABELS: Record<string, string> = {
  backend_engineer: "Backend Engineer",
  frontend_engineer: "Frontend Engineer",
  qa_engineer: "QA Engineer",
  devops_engineer: "DevOps Engineer",
  data_scientist: "Data Scientist",
  product_manager: "Product Manager",
  mobile_engineer: "Mobile Engineer",
  designer: "UX/UI Designer",
};

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
                {qa.depth}
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
            <p className="text-slate-500 text-xs uppercase tracking-wide mb-1">Question</p>
            <p className="text-slate-300 text-sm">{turn.question}</p>
            {turn.question_time && (
              <p className="text-slate-600 text-xs mt-1">{new Date(turn.question_time).toLocaleTimeString()}</p>
            )}
          </div>

          {/* Answer */}
          <div>
            <p className="text-slate-500 text-xs uppercase tracking-wide mb-1">Answer</p>
            <p className="text-slate-200 text-sm whitespace-pre-wrap">{turn.answer || <span className="text-slate-500 italic">No answer</span>}</p>
            {turn.answer_time && (
              <p className="text-slate-600 text-xs mt-1">{new Date(turn.answer_time).toLocaleTimeString()}</p>
            )}
          </div>

          {/* Analysis */}
          {qa && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2 border-t border-slate-700">
              {qa.evidence && (
                <div>
                  <p className="text-slate-500 text-xs uppercase tracking-wide mb-1">Evidence</p>
                  <p className="text-slate-400 text-xs">{qa.evidence}</p>
                </div>
              )}
              {qa.skills_mentioned && qa.skills_mentioned.length > 0 && (
                <div>
                  <p className="text-slate-500 text-xs uppercase tracking-wide mb-1">Skills Mentioned</p>
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
                  <p className="text-slate-500 text-xs uppercase tracking-wide mb-1">Red Flags</p>
                  <ul className="space-y-1">
                    {qa.red_flags.map((rf, i) => (
                      <li key={i} className="text-red-400 text-xs">⚠ {rf}</li>
                    ))}
                  </ul>
                </div>
              )}
              <div className="sm:col-span-2 flex gap-4 text-xs text-slate-500">
                <span>Specificity: <span className="text-slate-300 capitalize">{qa.specificity}</span></span>
                <span>Depth: <span className={`capitalize ${DEPTH_COLORS[qa.depth]?.split(" ")[0]}`}>{qa.depth}</span></span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function InterviewReplayPage() {
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
      .catch((err) => setError(err.message ?? "Could not load replay"))
      .finally(() => setLoading(false));
  }, [id, authLoading]);

  if (authLoading || loading) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="text-slate-400">Loading replay…</div>
      </div>
    );
  }

  if (error || !replay) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center px-4">
        <div className="text-center">
          <div className="text-red-400 mb-4">{error || "Replay not found"}</div>
          <button onClick={() => router.back()} className="text-blue-400 hover:underline text-sm">← Go back</button>
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
          ← Back
        </button>

        <div className="mb-6">
          <h1 className="text-2xl font-bold text-white">Interview Replay</h1>
          <p className="text-slate-400 mt-1">
            {replay.candidate_name} · {ROLE_LABELS[replay.target_role] ?? replay.target_role}
          </p>
          {replay.completed_at && (
            <p className="text-slate-500 text-sm mt-0.5">
              Completed {new Date(replay.completed_at).toLocaleDateString()}
            </p>
          )}
          <p className="text-slate-500 text-xs mt-1">{replay.turns.length} questions</p>
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
