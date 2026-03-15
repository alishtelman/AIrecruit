"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { companyApi } from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";
import type { CandidateDetail, HiringRecommendation, ReportWithRole } from "@/lib/types";

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

function ReportCard({ report }: { report: ReportWithRole }) {
  const rec = REC_STYLES[report.hiring_recommendation] ?? REC_STYLES.maybe;
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl p-6 space-y-5">
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

      <div className="space-y-3">
        <ScoreBar label="Hard Skills" value={report.hard_skills_score} />
        <ScoreBar label="Soft Skills" value={report.soft_skills_score} />
        <ScoreBar label="Communication" value={report.communication_score} />
      </div>

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
