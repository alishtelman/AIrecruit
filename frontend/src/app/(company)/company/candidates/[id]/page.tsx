"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { companyApi } from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";
import type { CandidateDetail, HiringRecommendation, ReportWithRole, CompetencyScore, SkillTag, RedFlag } from "@/lib/types";

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

const REC_STYLES: Record<HiringRecommendation, { label: string; className: string }> = {
  strong_yes: { label: "Strong Yes", className: "bg-green-500/15 text-green-400 border-green-500/30" },
  yes:        { label: "Yes",         className: "bg-blue-500/15 text-blue-400 border-blue-500/30" },
  maybe:      { label: "Maybe",       className: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30" },
  no:         { label: "No",          className: "bg-red-500/15 text-red-400 border-red-500/30" },
};

const CATEGORY_LABELS: Record<string, string> = {
  technical_core: "Core",
  technical_breadth: "Breadth",
  problem_solving: "Problem Solving",
  communication: "Communication",
  behavioral: "Behavioral",
};

const CATEGORY_COLORS: Record<string, string> = {
  technical_core: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  technical_breadth: "bg-cyan-500/15 text-cyan-400 border-cyan-500/30",
  problem_solving: "bg-purple-500/15 text-purple-400 border-purple-500/30",
  communication: "bg-green-500/15 text-green-400 border-green-500/30",
  behavioral: "bg-orange-500/15 text-orange-400 border-orange-500/30",
};

const PROFICIENCY_COLORS: Record<string, string> = {
  expert: "bg-green-500/20 text-green-400",
  advanced: "bg-blue-500/20 text-blue-400",
  intermediate: "bg-yellow-500/20 text-yellow-400",
  beginner: "bg-slate-500/20 text-slate-400",
};

const SEVERITY_COLORS: Record<string, string> = {
  high: "border-red-500/40 bg-red-500/10 text-red-300",
  medium: "border-yellow-500/40 bg-yellow-500/10 text-yellow-300",
  low: "border-slate-600 bg-slate-700/50 text-slate-400",
};

function ScoreBar({ label, value }: { label: string; value: number | null }) {
  const pct = value != null ? (value / 10) * 100 : 0;
  return (
    <div>
      <div className="flex justify-between text-sm mb-1">
        <span className="text-slate-400">{label}</span>
        <span className="text-white font-medium">{value != null ? value.toFixed(1) : "—"}</span>
      </div>
      <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
        <div
          className="h-full bg-blue-500 rounded-full transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function CompetencyRow({ cs }: { cs: CompetencyScore }) {
  const pct = (cs.score / 10) * 100;
  const categoryColor = CATEGORY_COLORS[cs.category] ?? "bg-slate-700 text-slate-400 border-slate-600";
  const barColor = cs.score >= 7 ? "bg-green-500" : cs.score >= 5 ? "bg-yellow-500" : "bg-red-500";
  const scoreColor = cs.score >= 7 ? "text-green-400" : cs.score >= 5 ? "text-yellow-400" : "text-red-400";

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-slate-300 text-xs truncate">{cs.competency}</span>
          <span className={`text-xs px-1.5 py-0.5 rounded border shrink-0 ${categoryColor}`}>
            {CATEGORY_LABELS[cs.category] ?? cs.category}
          </span>
        </div>
        <span className={`text-xs font-bold shrink-0 ${scoreColor}`}>{cs.score.toFixed(1)}</span>
      </div>
      <div className="h-1 bg-slate-700 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${barColor}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function ReportCard({ report }: { report: ReportWithRole }) {
  const rec = REC_STYLES[report.hiring_recommendation] ?? REC_STYLES.maybe;
  const [showCompetencies, setShowCompetencies] = useState(false);

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl p-6 space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-white font-semibold">
            {ROLE_LABELS[report.target_role] ?? report.target_role}
          </h3>
          <p className="text-slate-500 text-xs mt-0.5">
            {new Date(report.created_at).toLocaleDateString()}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className={`text-xs px-2.5 py-1 rounded-full border ${rec.className}`}>
            {rec.label}
          </span>
          <div className="text-right">
            <div className="text-2xl font-bold text-white">
              {report.overall_score != null ? report.overall_score.toFixed(1) : "—"}
            </div>
            <div className="text-slate-500 text-xs">/ 10</div>
          </div>
        </div>
      </div>

      {report.interview_summary && (
        <p className="text-slate-300 text-sm">{report.interview_summary}</p>
      )}

      {/* Aggregate score bars */}
      <div className="space-y-2.5">
        <ScoreBar label="Hard Skills" value={report.hard_skills_score} />
        <ScoreBar label="Soft Skills" value={report.soft_skills_score} />
        <ScoreBar label="Communication" value={report.communication_score} />
        {report.problem_solving_score != null && (
          <ScoreBar label="Problem Solving" value={report.problem_solving_score} />
        )}
        {report.response_consistency != null && (
          <ScoreBar label="Consistency" value={report.response_consistency} />
        )}
      </div>

      {/* Competency breakdown toggle */}
      {report.competency_scores && report.competency_scores.length > 0 && (
        <div>
          <button
            onClick={() => setShowCompetencies(!showCompetencies)}
            className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
          >
            {showCompetencies ? "▲ Hide" : "▼ Show"} competency breakdown ({report.competency_scores.length})
          </button>
          {showCompetencies && (
            <div className="mt-3 space-y-2.5">
              {report.competency_scores.map((cs, i) => (
                <CompetencyRow key={i} cs={cs} />
              ))}
            </div>
          )}
        </div>
      )}

      {/* Skill tags */}
      {report.skill_tags && report.skill_tags.length > 0 && (
        <div>
          <p className="text-slate-500 text-xs uppercase tracking-wide mb-2">Skills</p>
          <div className="flex flex-wrap gap-1.5">
            {report.skill_tags.map((tag, i) => (
              <span key={i} className={`px-2 py-0.5 rounded-full text-xs ${PROFICIENCY_COLORS[tag.proficiency] ?? PROFICIENCY_COLORS.intermediate}`}>
                {tag.skill}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Red flags */}
      {report.red_flags && report.red_flags.length > 0 && (
        <div>
          <p className="text-slate-500 text-xs uppercase tracking-wide mb-2">Red Flags</p>
          <div className="space-y-2">
            {report.red_flags.map((rf: RedFlag, i) => (
              <div key={i} className={`border rounded-lg px-3 py-2 text-sm ${SEVERITY_COLORS[rf.severity] ?? SEVERITY_COLORS.low}`}>
                <span className="font-medium">⚠ {rf.flag}</span>
                {rf.evidence && <span className="ml-2 opacity-70 text-xs">{rf.evidence}</span>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Qualitative sections */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2">
        <div>
          <h4 className="text-green-400 text-xs font-semibold uppercase tracking-wide mb-2">Strengths</h4>
          <ul className="space-y-1">
            {report.strengths.map((s, i) => (
              <li key={i} className="text-slate-300 text-sm flex gap-2">
                <span className="text-green-500 mt-0.5">+</span>{s}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h4 className="text-red-400 text-xs font-semibold uppercase tracking-wide mb-2">Weaknesses</h4>
          <ul className="space-y-1">
            {report.weaknesses.map((w, i) => (
              <li key={i} className="text-slate-300 text-sm flex gap-2">
                <span className="text-red-500 mt-0.5">−</span>{w}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h4 className="text-blue-400 text-xs font-semibold uppercase tracking-wide mb-2">Recommendations</h4>
          <ul className="space-y-1">
            {report.recommendations.map((r, i) => (
              <li key={i} className="text-slate-300 text-sm flex gap-2">
                <span className="text-blue-500 mt-0.5">→</span>{r}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

export default function CandidateDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { loading: authLoading } = useAuth("/company/login");
  const [candidate, setCandidate] = useState<CandidateDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (authLoading) return;
    companyApi.getCandidate(id)
      .then(setCandidate)
      .catch((err) => setError(err.message ?? "Failed to load candidate"))
      .finally(() => setLoading(false));
  }, [id, authLoading, router]);

  return (
    <div className="min-h-screen bg-slate-900 px-4 py-8">
      <div className="max-w-3xl mx-auto">
        <Link
          href="/company/dashboard"
          className="text-slate-400 hover:text-white text-sm flex items-center gap-1 mb-6 transition-colors"
        >
          ← Back to candidates
        </Link>

        {loading && <div className="text-center py-16 text-slate-400">Loading…</div>}

        {error && (
          <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg px-4 py-3">
            {error}
          </div>
        )}

        {!loading && candidate && (
          <>
            <div className="mb-6">
              <h1 className="text-2xl font-bold text-white">{candidate.full_name}</h1>
              <p className="text-slate-400 mt-1">{candidate.email}</p>
              <p className="text-slate-500 text-sm mt-0.5">
                {candidate.reports.length} interview{candidate.reports.length !== 1 ? "s" : ""} completed
              </p>
            </div>

            <div className="space-y-4">
              {candidate.reports.map((report) => (
                <ReportCard key={report.report_id} report={report} />
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
