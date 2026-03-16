"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/hooks/useAuth";
import { reportApi } from "@/lib/api";
import type { AssessmentReport, HiringRecommendation, CompetencyScore, SkillTag, RedFlag, QuestionAnalysis } from "@/lib/types";

const RECOMMENDATION_CONFIG: Record<HiringRecommendation, { label: string; color: string; bg: string }> = {
  strong_yes: { label: "Strong Yes", color: "text-green-400", bg: "bg-green-500/10 border-green-500/30" },
  yes:        { label: "Yes",        color: "text-blue-400",  bg: "bg-blue-500/10 border-blue-500/30" },
  maybe:      { label: "Maybe",      color: "text-yellow-400",bg: "bg-yellow-500/10 border-yellow-500/30" },
  no:         { label: "No",         color: "text-red-400",   bg: "bg-red-500/10 border-red-500/30" },
};

const CATEGORY_LABELS: Record<string, string> = {
  technical_core: "Technical Core", technical_breadth: "Technical Breadth",
  problem_solving: "Problem Solving", communication: "Communication", behavioral: "Behavioral",
};

const CATEGORY_COLORS: Record<string, string> = {
  technical_core: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  technical_breadth: "bg-cyan-500/15 text-cyan-400 border-cyan-500/30",
  problem_solving: "bg-purple-500/15 text-purple-400 border-purple-500/30",
  communication: "bg-green-500/15 text-green-400 border-green-500/30",
  behavioral: "bg-orange-500/15 text-orange-400 border-orange-500/30",
};

const PROFICIENCY_COLORS: Record<string, string> = {
  expert: "bg-green-500/20 text-green-400", advanced: "bg-blue-500/20 text-blue-400",
  intermediate: "bg-yellow-500/20 text-yellow-400", beginner: "bg-slate-500/20 text-slate-400",
};

const SEVERITY_COLORS: Record<string, string> = {
  high: "border-red-500/40 bg-red-500/10 text-red-300",
  medium: "border-yellow-500/40 bg-yellow-500/10 text-yellow-300",
  low: "border-slate-600 bg-slate-800 text-slate-400",
};

export default function CompanyReportPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { loading: authLoading } = useAuth("/company/login");
  const [report, setReport] = useState<AssessmentReport | null>(null);
  const [error, setError] = useState("");
  const [expandedQ, setExpandedQ] = useState<number | null>(null);

  useEffect(() => {
    if (!id || authLoading) return;
    reportApi.getById(id).then(setReport).catch(() => setError("Could not load report"));
  }, [id, authLoading]);

  if (authLoading || (!report && !error)) {
    return <div className="min-h-screen bg-slate-900 flex items-center justify-center"><div className="text-slate-400">Loading report…</div></div>;
  }

  if (error || !report) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center px-4">
        <div className="text-center">
          <div className="text-red-400 mb-4">{error}</div>
          <button onClick={() => router.back()} className="text-blue-400 hover:underline text-sm">← Go back</button>
        </div>
      </div>
    );
  }

  const rec = RECOMMENDATION_CONFIG[report.hiring_recommendation];

  return (
    <div className="min-h-screen bg-slate-900 px-4 py-10">
      <div className="max-w-3xl mx-auto">
        <button onClick={() => router.back()} className="text-slate-400 hover:text-white text-sm mb-6 inline-block transition-colors">
          ← Back
        </button>

        <h1 className="text-2xl font-bold text-white mb-2">Assessment Report</h1>

        {report.interview_summary && <p className="text-slate-400 mb-6">{report.interview_summary}</p>}

        <div className={`inline-flex items-center gap-2 border rounded-full px-4 py-1.5 text-sm font-semibold mb-6 ${rec.bg} ${rec.color}`}>
          Hiring Recommendation: {rec.label}
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 mb-8">
          <ScoreCard label="Overall Score" score={report.overall_score} highlight />
          <ScoreCard label="Hard Skills" score={report.hard_skills_score} />
          <ScoreCard label="Soft Skills" score={report.soft_skills_score} />
          <ScoreCard label="Communication" score={report.communication_score} />
          <ScoreCard label="Problem Solving" score={report.problem_solving_score} />
          {report.response_consistency != null && <ScoreCard label="Consistency" score={report.response_consistency} />}
        </div>

        {report.competency_scores && report.competency_scores.length > 0 && (
          <Section title="Competency Heatmap" color="blue">
            <CompetencyHeatmap scores={report.competency_scores} />
          </Section>
        )}

        {report.skill_tags && report.skill_tags.length > 0 && (
          <Section title="Skills Identified" color="cyan"><SkillMatrix tags={report.skill_tags} /></Section>
        )}

        {report.red_flags && report.red_flags.length > 0 && (
          <Section title="Red Flags" color="red">
            <div className="space-y-3">
              {report.red_flags.map((rf, i) => <RedFlagRow key={i} flag={rf} />)}
            </div>
          </Section>
        )}

        {report.strengths.length > 0 && (
          <Section title="Strengths" color="green">
            {report.strengths.map((s, i) => <ListItem key={i} text={s} bullet="✓" color="text-green-400" />)}
          </Section>
        )}

        {report.weaknesses.length > 0 && (
          <Section title="Areas to Improve" color="yellow">
            {report.weaknesses.map((w, i) => <ListItem key={i} text={w} bullet="△" color="text-yellow-400" />)}
          </Section>
        )}

        {report.recommendations.length > 0 && (
          <Section title="Recommendations" color="purple">
            {report.recommendations.map((r, i) => <ListItem key={i} text={r} bullet="→" color="text-purple-400" />)}
          </Section>
        )}

        {report.per_question_analysis && report.per_question_analysis.length > 0 && (
          <div className="mt-6">
            <h2 className="text-white font-semibold mb-3">Per-Question Analysis</h2>
            <div className="space-y-2">
              {report.per_question_analysis.map((qa, i) => (
                <QuestionAccordion key={i} qa={qa} expanded={expandedQ === i} onToggle={() => setExpandedQ(expandedQ === i ? null : i)} />
              ))}
            </div>
          </div>
        )}

        {/* Cheat risk */}
        {report.cheat_risk_score != null && report.cheat_risk_score > 0 && (
          <div className="bg-slate-800 border border-orange-500/40 rounded-xl p-5 mb-4 mt-4">
            <div className="flex items-center gap-3 mb-2">
              <span className="text-orange-400 font-semibold text-sm">⚠ Behavioral Risk Signals</span>
              <span className={`text-xs px-2 py-0.5 rounded-full font-bold ${
                report.cheat_risk_score >= 0.7 ? "bg-red-500/20 text-red-400" :
                report.cheat_risk_score >= 0.4 ? "bg-orange-500/20 text-orange-400" :
                "bg-yellow-500/20 text-yellow-400"
              }`}>
                Risk: {Math.round(report.cheat_risk_score * 100)}%
              </span>
            </div>
            {report.cheat_flags && report.cheat_flags.length > 0 && (
              <ul className="space-y-1">
                {report.cheat_flags.map((f, i) => (
                  <li key={i} className="text-orange-300 text-xs flex gap-2">
                    <span className="text-orange-500 mt-0.5 shrink-0">•</span>{f}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        <div className="text-slate-600 text-xs mt-8">
          Generated by model {report.model_version} · {new Date(report.created_at).toLocaleDateString()}
        </div>
      </div>
    </div>
  );
}

function ScoreCard({ label, score, highlight = false }: { label: string; score: number | null; highlight?: boolean }) {
  const value = score ?? 0;
  return (
    <div className={`bg-slate-800 border rounded-xl p-4 ${highlight ? "border-blue-500/40" : "border-slate-700"}`}>
      <div className="text-slate-400 text-xs mb-2">{label}</div>
      <div className={`text-2xl font-bold mb-2 ${highlight ? "text-blue-400" : "text-white"}`}>
        {value.toFixed(1)}<span className="text-slate-500 text-sm font-normal">/10</span>
      </div>
      <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${highlight ? "bg-blue-500" : "bg-slate-400"}`} style={{ width: `${(value / 10) * 100}%` }} />
      </div>
    </div>
  );
}

function CompetencyHeatmap({ scores }: { scores: CompetencyScore[] }) {
  const groups: Record<string, CompetencyScore[]> = {};
  for (const cs of scores) { if (!groups[cs.category]) groups[cs.category] = []; groups[cs.category].push(cs); }
  return (
    <div className="space-y-4">
      {Object.entries(groups).map(([category, items]) => (
        <div key={category}>
          <div className="text-xs text-slate-500 uppercase tracking-wide mb-2">{CATEGORY_LABELS[category] ?? category}</div>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {items.map((cs, i) => {
              const cellClass = cs.score >= 7 ? "bg-green-500/30 border-green-500/50 text-green-300" : cs.score >= 5 ? "bg-yellow-500/30 border-yellow-500/50 text-yellow-300" : "bg-red-500/30 border-red-500/50 text-red-300";
              return (
                <div key={i} className={`border rounded-lg px-3 py-2 ${cellClass}`}>
                  <div className="text-xs font-medium truncate">{cs.competency}</div>
                  <div className="text-lg font-bold mt-0.5">{cs.score.toFixed(1)}</div>
                  {cs.evidence && <div className="text-xs opacity-70 mt-1 line-clamp-2">{cs.evidence}</div>}
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

function SkillMatrix({ tags }: { tags: SkillTag[] }) {
  const strong = tags.filter((t) => t.proficiency === "expert" || t.proficiency === "advanced");
  const develop = tags.filter((t) => t.proficiency === "beginner" || t.proficiency === "intermediate");
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
      <div>
        <div className="text-xs text-green-400 uppercase tracking-wide font-semibold mb-2">Strong (expert / advanced)</div>
        <div className="flex flex-wrap gap-1.5">
          {strong.length === 0 ? <span className="text-slate-500 text-xs">—</span> : strong.map((tag, i) => (
            <span key={i} className="px-2.5 py-1 rounded-full text-xs font-medium bg-green-500/20 text-green-400">{tag.skill}{tag.mentions_count > 1 && <span className="ml-1 opacity-60">×{tag.mentions_count}</span>}</span>
          ))}
        </div>
      </div>
      <div>
        <div className="text-xs text-yellow-400 uppercase tracking-wide font-semibold mb-2">To Develop (beginner / intermediate)</div>
        <div className="flex flex-wrap gap-1.5">
          {develop.length === 0 ? <span className="text-slate-500 text-xs">—</span> : develop.map((tag, i) => (
            <span key={i} className="px-2.5 py-1 rounded-full text-xs font-medium bg-yellow-500/20 text-yellow-400">{tag.skill}{tag.mentions_count > 1 && <span className="ml-1 opacity-60">×{tag.mentions_count}</span>}</span>
          ))}
        </div>
      </div>
    </div>
  );
}

function RedFlagRow({ flag }: { flag: RedFlag }) {
  const style = SEVERITY_COLORS[flag.severity] ?? SEVERITY_COLORS.low;
  return (
    <div className={`border rounded-lg px-4 py-3 ${style}`}>
      <div className="flex items-center gap-2 mb-1"><span className="text-sm font-medium">⚠ {flag.flag}</span><span className="text-xs opacity-70 capitalize">{flag.severity}</span></div>
      {flag.evidence && <p className="text-xs opacity-80">{flag.evidence}</p>}
    </div>
  );
}

function QuestionAccordion({ qa, expanded, onToggle }: { qa: QuestionAnalysis; expanded: boolean; onToggle: () => void }) {
  const depthColor: Record<string, string> = { expert: "text-green-400", strong: "text-blue-400", adequate: "text-yellow-400", surface: "text-orange-400", none: "text-red-400" };
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg overflow-hidden">
      <button onClick={onToggle} className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-slate-750 transition-colors">
        <div className="flex items-center gap-3">
          <span className="text-slate-500 text-xs">Q{qa.question_number}</span>
          <span className="text-slate-300 text-sm font-medium">{qa.targeted_competencies.join(", ") || "General"}</span>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <span className={`text-xs font-medium ${depthColor[qa.depth] ?? "text-slate-400"} capitalize`}>{qa.depth}</span>
          <span className="text-white text-sm font-bold">{qa.answer_quality.toFixed(1)}</span>
          <span className="text-slate-500 text-xs">{expanded ? "▲" : "▼"}</span>
        </div>
      </button>
      {expanded && (
        <div className="px-4 pb-4 space-y-3 border-t border-slate-700">
          {qa.evidence && <div><p className="text-slate-500 text-xs uppercase tracking-wide mb-1">Evidence</p><p className="text-slate-300 text-sm">{qa.evidence}</p></div>}
          {qa.skills_mentioned.length > 0 && (
            <div><p className="text-slate-500 text-xs uppercase tracking-wide mb-1">Skills Mentioned</p>
              <div className="flex flex-wrap gap-1.5">{qa.skills_mentioned.map((s, i) => <span key={i} className={`px-2 py-0.5 rounded text-xs ${PROFICIENCY_COLORS[s.proficiency] ?? PROFICIENCY_COLORS.intermediate}`}>{s.skill}</span>)}</div>
            </div>
          )}
          {qa.red_flags.length > 0 && <div><p className="text-slate-500 text-xs uppercase tracking-wide mb-1">Flags</p><ul className="space-y-1">{qa.red_flags.map((rf, i) => <li key={i} className="text-red-400 text-xs">⚠ {rf}</li>)}</ul></div>}
          <div className="flex gap-4 text-xs"><span className="text-slate-500">Specificity: <span className="text-slate-300 capitalize">{qa.specificity}</span></span></div>
        </div>
      )}
    </div>
  );
}

function Section({ title, children, color }: { title: string; children: React.ReactNode; color: string }) {
  const colors: Record<string, string> = { green: "text-green-400", yellow: "text-yellow-400", blue: "text-blue-400", cyan: "text-cyan-400", purple: "text-purple-400", red: "text-red-400" };
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl p-6 mb-4">
      <h2 className={`font-semibold mb-3 ${colors[color] ?? "text-white"}`}>{title}</h2>
      <ul className="space-y-2">{children}</ul>
    </div>
  );
}

function ListItem({ text, bullet, color }: { text: string; bullet: string; color: string }) {
  return <li className="flex gap-3 text-sm text-slate-300"><span className={`${color} shrink-0 mt-0.5`}>{bullet}</span>{text}</li>;
}
