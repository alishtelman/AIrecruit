"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { useRouter } from "@/i18n/navigation";

import { AdminWorkspaceHeader } from "@/components/admin-workspace-header";
import { useAuth } from "@/hooks/useAuth";
import { adminApi } from "@/lib/api";
import type { AssessmentReport } from "@/lib/types";

function formatScore(value: number | null | undefined) {
  return typeof value === "number" ? value.toFixed(1) : "—";
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-950/40 p-4">
      <div className="text-xs uppercase tracking-[0.18em] text-slate-500">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-white">{value}</div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="ai-panel rounded-[1.75rem] p-6">
      <h2 className="text-lg font-semibold text-white">{title}</h2>
      <div className="mt-4">{children}</div>
    </section>
  );
}

export default function AdminReportDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { loading: authLoading, logout } = useAuth({
    redirectTo: "/admin/login",
    allowedRoles: ["platform_admin"],
  });
  const [report, setReport] = useState<AssessmentReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!id || authLoading) return;
    setLoading(true);
    setError("");
    adminApi
      .getReport(id)
      .then(setReport)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load report"))
      .finally(() => setLoading(false));
  }, [id, authLoading]);

  const practical = report?.practical_section ?? null;
  const counters = report?.answer_quality_counters ?? report?.interview_quality_metrics ?? null;

  return (
    <div className="ai-shell min-h-screen">
      <div className="ai-section mx-auto max-w-5xl px-4 py-6 sm:px-6 lg:px-8">
        <AdminWorkspaceHeader onLogout={logout} />

        <button onClick={() => router.back()} className="mb-5 text-sm text-slate-400 transition-colors hover:text-white">
          ← Back
        </button>

        {error && <div className="rounded-2xl border border-red-500/25 bg-red-500/10 px-5 py-4 text-sm text-red-300">{error}</div>}
        {(loading || authLoading) && <div className="rounded-2xl border border-slate-700 bg-slate-900/60 px-5 py-8 text-center text-slate-400">Loading report...</div>}

        {!loading && report && (
          <div className="space-y-6">
            <section className="ai-panel-strong rounded-[2rem] p-7 sm:p-8">
              <span className="ai-kicker">Admin report review</span>
              <h1 className="mt-4 text-3xl font-semibold text-white">Assessment report</h1>
              <p className="mt-2 break-all text-xs text-slate-500">{report.id}</p>
              {report.interview_summary && <p className="mt-5 max-w-3xl text-slate-300">{report.interview_summary}</p>}
              <div className="mt-5 inline-flex rounded-full border border-blue-500/30 bg-blue-500/10 px-4 py-1.5 text-sm font-semibold text-blue-200">
                Recommendation: {report.hiring_recommendation}
              </div>
            </section>

            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
              <MetricCard label="Overall" value={formatScore(report.overall_score)} />
              <MetricCard label="Hard" value={formatScore(report.hard_skills_score)} />
              <MetricCard label="Soft" value={formatScore(report.soft_skills_score)} />
              <MetricCard label="Communication" value={formatScore(report.communication_score)} />
              <MetricCard label="Problem solving" value={formatScore(report.problem_solving_score)} />
            </div>

            {counters && (
              <Section title="Interview quality counters">
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
                  <MetricCard label="On topic" value={String(counters.answered_on_topic_count ?? "—")} />
                  <MetricCard label="Off topic" value={String(counters.off_topic_answers_count ?? "—")} />
                  <MetricCard label="Skipped/control" value={String(counters.skipped_or_control_intent_count ?? "—")} />
                  <MetricCard label="Reframes" value={String(counters.relevance_reframe_count ?? "—")} />
                  <MetricCard label="Forced transitions" value={String(counters.forced_topic_transition_count ?? "—")} />
                </div>
              </Section>
            )}

            {practical && (
              <Section title="Practical task">
                <div className="grid gap-3 sm:grid-cols-3">
                  <MetricCard label="Status" value={String(practical.evaluation_status ?? "—")} />
                  <MetricCard label="Score" value={formatScore(asNumber(practical.practical_score))} />
                  <MetricCard label="Tasks" value={String(practical.practical_tasks_count ?? "—")} />
                </div>
              </Section>
            )}

            <div className="grid gap-6 lg:grid-cols-3">
              <Section title="Strengths">
                <ul className="space-y-2 text-sm text-slate-300">
                  {(report.strengths ?? []).map((item) => <li key={item}>✓ {item}</li>)}
                </ul>
              </Section>
              <Section title="Weaknesses">
                <ul className="space-y-2 text-sm text-slate-300">
                  {(report.weaknesses ?? []).map((item) => <li key={item}>• {item}</li>)}
                </ul>
              </Section>
              <Section title="Recommendations">
                <ul className="space-y-2 text-sm text-slate-300">
                  {(report.recommendations ?? []).map((item) => <li key={item}>→ {item}</li>)}
                </ul>
              </Section>
            </div>

            {report.per_question_analysis && report.per_question_analysis.length > 0 && (
              <Section title="Per-question analysis">
                <div className="space-y-3">
                  {report.per_question_analysis.slice(0, 12).map((item, index) => (
                    <div key={`${item.question_number}-${index}`} className="rounded-2xl border border-slate-800 bg-slate-950/40 p-4 text-sm">
                      <div className="font-semibold text-white">
                        Q{item.question_number ?? index + 1}: {item.targeted_competencies?.join(", ") || "Question evidence"}
                      </div>
                      <div className="mt-2 text-slate-300">{item.evidence || "No evidence excerpt"}</div>
                      <div className="mt-2 text-xs uppercase tracking-[0.16em] text-slate-500">Quality: {formatScore(item.answer_quality)}</div>
                    </div>
                  ))}
                </div>
              </Section>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
