"use client";

import { useEffect, useState } from "react";
import { Link } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { useParams } from "next/navigation";
import { CompanyWorkspaceHeader } from "@/components/company-workspace-header";
import { companyApi } from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";
import type { CandidateActivity, CandidateDetail, CandidateNote, CompanyShortlist, HiringRecommendation, ReportWithRole, CompetencyScore, RedFlag } from "@/lib/types";

const REC_STYLES: Record<HiringRecommendation, { className: string }> = {
  strong_yes: { className: "bg-green-500/15 text-green-400 border-green-500/30" },
  yes:        { className: "bg-blue-500/15 text-blue-400 border-blue-500/30" },
  maybe:      { className: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30" },
  no:         { className: "bg-red-500/15 text-red-400 border-red-500/30" },
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
  const reportT = useTranslations("report");
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
            {reportT(`labels.${cs.category}`)}
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

const OUTCOME_LABELS: Record<string, { cls: string; labelKey: string }> = {
  hired:       { cls: "bg-green-500/15 text-green-400 border-green-500/30", labelKey: "hired" },
  rejected:    { cls: "bg-red-500/15 text-red-400 border-red-500/30", labelKey: "rejected" },
  interviewing:{ cls: "bg-blue-500/15 text-blue-400 border-blue-500/30", labelKey: "interviewing" },
  no_show:     { cls: "bg-slate-500/15 text-slate-400 border-slate-600", labelKey: "no_show" },
};

function ReportCard({ report }: { report: ReportWithRole }) {
  const t = useTranslations("companyCandidate");
  const roleT = useTranslations("interviewStart.roles");
  const reportT = useTranslations("report");
  const dashboardT = useTranslations("companyDashboard");
  const rec = REC_STYLES[report.hiring_recommendation] ?? REC_STYLES.maybe;
  const [showCompetencies, setShowCompetencies] = useState(false);

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl p-6 space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-white font-semibold">
            {roleT(report.target_role)}
          </h3>
          <p className="text-slate-500 text-xs mt-0.5">
            {new Date(report.created_at).toLocaleDateString()}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {report.interview_id && (
            <Link
              href={`/company/interviews/${report.interview_id}/replay`}
              className="text-xs text-blue-400 hover:text-blue-300 border border-blue-500/30 px-2 py-0.5 rounded transition-colors"
            >
              {t("report.viewReplay")}
            </Link>
          )}
          <span className={`text-xs px-2.5 py-1 rounded-full border ${rec.className}`}>
            {dashboardT(`recommendations.${report.hiring_recommendation}`)}
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
        <ScoreBar label={reportT("hardSkills")} value={report.hard_skills_score} />
        <ScoreBar label={reportT("softSkills")} value={report.soft_skills_score} />
        <ScoreBar label={reportT("communication")} value={report.communication_score} />
        {report.problem_solving_score != null && (
          <ScoreBar label={reportT("problemSolving")} value={report.problem_solving_score} />
        )}
        {report.response_consistency != null && (
          <ScoreBar label={reportT("consistency")} value={report.response_consistency} />
        )}
      </div>

      {/* Competency breakdown toggle */}
      {report.competency_scores && report.competency_scores.length > 0 && (
        <div>
          <button
            onClick={() => setShowCompetencies(!showCompetencies)}
            className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
          >
            {showCompetencies ? t("report.hideCompetencies") : t("report.showCompetencies")} ({report.competency_scores.length})
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
          <p className="text-slate-500 text-xs uppercase tracking-wide mb-2">{t("report.skills")}</p>
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
          <p className="text-slate-500 text-xs uppercase tracking-wide mb-2">{reportT("redFlags")}</p>
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
          <h4 className="text-green-400 text-xs font-semibold uppercase tracking-wide mb-2">{reportT("strengths")}</h4>
          <ul className="space-y-1">
            {report.strengths.map((s, i) => (
              <li key={i} className="text-slate-300 text-sm flex gap-2">
                <span className="text-green-500 mt-0.5">+</span>{s}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h4 className="text-red-400 text-xs font-semibold uppercase tracking-wide mb-2">{t("report.weaknesses")}</h4>
          <ul className="space-y-1">
            {report.weaknesses.map((w, i) => (
              <li key={i} className="text-slate-300 text-sm flex gap-2">
                <span className="text-red-500 mt-0.5">−</span>{w}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h4 className="text-blue-400 text-xs font-semibold uppercase tracking-wide mb-2">{reportT("recommendations")}</h4>
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
  const t = useTranslations("companyCandidate");
  const roleT = useTranslations("interviewStart.roles");
  const { id } = useParams<{ id: string }>();
  const { user, loading: authLoading, logout } = useAuth({
    redirectTo: "/company/login",
    allowedRoles: ["company_admin", "company_member"],
    unauthorizedRedirectTo: "/candidate/dashboard",
  });
  const [candidate, setCandidate] = useState<CandidateDetail | null>(null);
  const [shortlists, setShortlists] = useState<CompanyShortlist[]>([]);
  const [notes, setNotes] = useState<CandidateNote[]>([]);
  const [activity, setActivity] = useState<CandidateActivity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [shortlistError, setShortlistError] = useState("");
  const [outcome, setOutcome] = useState<string>("");
  const [outcomeNotes, setOutcomeNotes] = useState("");
  const [savingOutcome, setSavingOutcome] = useState(false);
  const [outcomeSaved, setOutcomeSaved] = useState(false);
  const [noteBody, setNoteBody] = useState("");
  const [noteError, setNoteError] = useState("");
  const [savingNote, setSavingNote] = useState(false);
  const companyRole = user?.company_member_role ?? (user?.role === "company_admin" ? "admin" : null);
  const canManagePipeline = companyRole === "admin" || companyRole === "recruiter";

  useEffect(() => {
    if (authLoading) return;
    Promise.all([
      companyApi.getCandidate(id),
      companyApi.listShortlists(),
      companyApi.listCandidateNotes(id),
      companyApi.listCandidateActivity(id),
    ])
      .then(([c, shortlistItems, noteItems, activityItems]) => {
        setCandidate(c);
        setShortlists(shortlistItems);
        setNotes(noteItems);
        setActivity(activityItems);
        setOutcome(c.hire_outcome ?? "");
        setOutcomeNotes(c.hire_notes ?? "");
      })
      .catch((err) => setError(err.message ?? t("errors.load")))
      .finally(() => setLoading(false));
  }, [id, authLoading, t]);

  async function reloadCandidateAndShortlists() {
    const [candidateData, shortlistItems, noteItems, activityItems] = await Promise.all([
      companyApi.getCandidate(id),
      companyApi.listShortlists(),
      companyApi.listCandidateNotes(id),
      companyApi.listCandidateActivity(id),
    ]);
    setCandidate(candidateData);
    setShortlists(shortlistItems);
    setNotes(noteItems);
    setActivity(activityItems);
    setOutcome(candidateData.hire_outcome ?? "");
    setOutcomeNotes(candidateData.hire_notes ?? "");
  }

  async function handleSaveOutcome() {
    if (!outcome) return;
    if (!canManagePipeline) {
      setError(t("errors.viewerReadonly"));
      return;
    }
    setSavingOutcome(true);
    try {
      await companyApi.setOutcome(id, outcome, outcomeNotes || undefined);
      await reloadCandidateAndShortlists();
      setOutcomeSaved(true);
      setTimeout(() => setOutcomeSaved(false), 2000);
    } catch {
      // ignore
    } finally {
      setSavingOutcome(false);
    }
  }

  async function toggleShortlist(shortlistId: string, isMember: boolean) {
    if (!canManagePipeline) {
      setShortlistError(t("errors.viewerReadonly"));
      return;
    }
    setShortlistError("");
    try {
      if (isMember) {
        await companyApi.removeCandidateFromShortlist(shortlistId, id);
      } else {
        await companyApi.addCandidateToShortlist(shortlistId, id);
      }
      await reloadCandidateAndShortlists();
    } catch (err: unknown) {
      setShortlistError(err instanceof Error ? err.message : t("errors.shortlist"));
    }
  }

  async function handleAddNote() {
    if (!noteBody.trim()) return;
    if (!canManagePipeline) {
      setNoteError(t("errors.viewerReadonly"));
      return;
    }
    setSavingNote(true);
    setNoteError("");
    try {
      await companyApi.createCandidateNote(id, noteBody.trim());
      setNoteBody("");
      await reloadCandidateAndShortlists();
    } catch (err: unknown) {
      setNoteError(err instanceof Error ? err.message : t("errors.note"));
    } finally {
      setSavingNote(false);
    }
  }

  return (
    <div className="ai-shell min-h-screen px-4 py-10">
      <div className="ai-section max-w-5xl mx-auto">
        <CompanyWorkspaceHeader onLogout={logout} />
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
          <Link
            href="/company/dashboard"
            className="text-slate-400 hover:text-white text-sm flex items-center gap-1 transition-colors"
          >
            ← {t("back")}
          </Link>
        </div>

        {loading && <div className="text-center py-16 text-slate-400">{t("loading")}</div>}

        {error && (
          <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg px-4 py-3">
            {error}
          </div>
        )}

        {!loading && candidate && (
          <>
            <div className="ai-panel-strong mb-6 rounded-[2rem] p-7">
              <h1 className="text-3xl font-semibold tracking-[-0.03em] text-white">{candidate.full_name}</h1>
              <p className="mt-1 text-slate-400">{candidate.email}</p>
              <p className="mt-1 text-sm text-slate-500">
                {t("completedInterviews", { count: candidate.reports.length })}
              </p>
              {companyRole === "viewer" && (
                <p className="mt-2 text-sm text-amber-300">{t("viewerMode")}</p>
              )}

              {/* Salary expectation */}
              {(candidate.salary_min || candidate.salary_max) && (
                <p className="mt-2 text-sm text-slate-300">
                  {t("salaryExpectation")}{" "}
                  {candidate.salary_min && candidate.salary_max
                    ? `${candidate.salary_min.toLocaleString()}–${candidate.salary_max.toLocaleString()}`
                    : (candidate.salary_min || candidate.salary_max)?.toLocaleString()}{" "}
                  {candidate.salary_currency}
                </p>
              )}

              <div className="mt-5 grid gap-4 xl:grid-cols-2">
              <div className="ai-panel rounded-[1.8rem] p-5 space-y-3">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-slate-400 text-xs uppercase tracking-wide font-semibold">{t("shortlists.title")}</p>
                    <p className="text-slate-500 text-sm mt-1">{t("shortlists.subtitle")}</p>
                  </div>
                  <Link href="/company/dashboard" className="text-blue-400 hover:text-blue-300 text-sm transition-colors">
                    {t("shortlists.manage")}
                  </Link>
                </div>
                {shortlistError && <p className="text-red-400 text-sm">{shortlistError}</p>}
                {candidate.shortlists.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {candidate.shortlists.map((membership) => (
                      <span key={membership.shortlist_id} className="px-2.5 py-1 rounded-full border border-blue-500/20 bg-blue-500/10 text-blue-300 text-xs">
                        {membership.name}
                      </span>
                    ))}
                  </div>
                )}
                {shortlists.length === 0 ? (
                  <p className="text-slate-500 text-sm">{t("shortlists.empty")}</p>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {shortlists.map((shortlist) => {
                      const isMember = candidate.shortlists.some((membership) => membership.shortlist_id === shortlist.shortlist_id);
                      return (
                        <button
                          key={shortlist.shortlist_id}
                          onClick={() => toggleShortlist(shortlist.shortlist_id, isMember)}
                          disabled={!canManagePipeline}
                          className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${
                            isMember
                              ? "border-blue-500/30 bg-blue-500/10 text-blue-300"
                              : "border-slate-600 text-slate-400 hover:text-white"
                          }`}
                        >
                          {isMember ? t("shortlists.remove", { name: shortlist.name }) : t("shortlists.add", { name: shortlist.name })}
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>

              <div className="ai-panel rounded-[1.8rem] p-5 space-y-3">
                <p className="text-slate-400 text-xs uppercase tracking-wide font-semibold">{t("decision.title")}</p>
                <div className="flex flex-wrap gap-2">
                  {(["hired", "interviewing", "rejected", "no_show"] as const).map((o) => {
                    const cfg = OUTCOME_LABELS[o];
                    return (
                      <button
                        key={o}
                        onClick={() => setOutcome(o)}
                        disabled={!canManagePipeline}
                        className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${
                          outcome === o ? cfg.cls : "border-slate-600 text-slate-500 hover:border-slate-500"
                        }`}
                      >
                        {t(`outcomes.${cfg.labelKey}`)}
                      </button>
                    );
                  })}
                </div>
                <input
                  type="text"
                  placeholder={t("decision.notesPlaceholder")}
                  value={outcomeNotes}
                  onChange={(e) => setOutcomeNotes(e.target.value)}
                  disabled={!canManagePipeline}
                  className="ai-input w-full rounded-xl px-4 py-2.5 text-sm placeholder:text-slate-500"
                />
                <button
                  onClick={handleSaveOutcome}
                  disabled={!outcome || savingOutcome || !canManagePipeline}
                  className="ai-button-primary rounded-xl px-4 py-2 text-sm text-white disabled:opacity-50"
                >
                  {outcomeSaved ? t("decision.saved") : savingOutcome ? t("decision.saving") : t("decision.save")}
                </button>
              </div>
              </div>

              <div className="ai-panel mt-4 rounded-[1.8rem] p-5 space-y-3">
                <p className="text-slate-400 text-xs uppercase tracking-wide font-semibold">{t("notes.title")}</p>
                {noteError && <p className="text-red-400 text-sm">{noteError}</p>}
                <div className="space-y-2">
                  <textarea
                    value={noteBody}
                    onChange={(e) => setNoteBody(e.target.value)}
                    disabled={!canManagePipeline}
                    rows={3}
                    placeholder={t("notes.placeholder")}
                    className="ai-input w-full rounded-xl px-4 py-3 text-sm placeholder:text-slate-500 focus:border-blue-500 resize-y"
                  />
                  <button
                    onClick={handleAddNote}
                    disabled={savingNote || !noteBody.trim() || !canManagePipeline}
                    className="rounded-xl bg-emerald-600 px-4 py-2 text-sm text-white transition-colors hover:bg-emerald-500 disabled:opacity-50"
                  >
                    {savingNote ? t("notes.saving") : t("notes.add")}
                  </button>
                </div>
                {notes.length === 0 ? (
                  <p className="text-slate-500 text-sm">{t("notes.empty")}</p>
                ) : (
                  <div className="space-y-3">
                    {notes.map((note) => (
                      <div key={note.note_id} className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-3">
                        <p className="text-slate-200 text-sm whitespace-pre-wrap">{note.body}</p>
                        <p className="text-slate-500 text-xs mt-2">
                          {note.author_email ?? t("labels.unknown")} · {new Date(note.created_at).toLocaleString()}
                        </p>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="ai-panel mt-4 rounded-[1.8rem] p-5 space-y-3">
                <p className="text-slate-400 text-xs uppercase tracking-wide font-semibold">{t("activity.title")}</p>
                {activity.length === 0 ? (
                  <p className="text-slate-500 text-sm">{t("activity.empty")}</p>
                ) : (
                  <div className="space-y-3">
                    {activity.map((item) => (
                      <div key={item.activity_id} className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-3">
                        <p className="text-slate-200 text-sm">{item.summary}</p>
                        <p className="text-slate-500 text-xs mt-1">
                          {item.actor_email ?? t("labels.system")} · {new Date(item.created_at).toLocaleString()}
                        </p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
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
