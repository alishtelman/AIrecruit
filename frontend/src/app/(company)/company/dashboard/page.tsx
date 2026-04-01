"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { CompanyWorkspaceHeader } from "@/components/company-workspace-header";
import { companyApi } from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";
import type {
  AnalyticsBreakdownItem,
  AnalyticsFunnel,
  AnalyticsOverview,
  AnalyticsSalary,
  CandidateListItem,
  CompanyCandidateSearchParams,
  CompanyShortlist,
  HireOutcome,
  HiringRecommendation,
} from "@/lib/types";

const OUTCOME_LABELS: Record<string, { cls: string }> = {
  hired: { cls: "bg-green-500/20 text-green-400" },
  rejected: { cls: "bg-red-500/20 text-red-400" },
  interviewing: { cls: "bg-blue-500/20 text-blue-400" },
  no_show: { cls: "bg-slate-500/20 text-slate-400" },
};

const REC_STYLES: Record<HiringRecommendation, { className: string }> = {
  strong_yes: { className: "bg-green-500/15 text-green-400 border-green-500/30" },
  yes: { className: "bg-blue-500/15 text-blue-400 border-blue-500/30" },
  maybe: { className: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30" },
  no: { className: "bg-red-500/15 text-red-400 border-red-500/30" },
};

const ROLE_VALUES = [
  "backend_engineer",
  "frontend_engineer",
  "qa_engineer",
  "devops_engineer",
  "data_scientist",
  "product_manager",
  "mobile_engineer",
  "designer",
] as const;

type DashboardTab = "candidates" | "analytics";
type DashboardSort = NonNullable<CompanyCandidateSearchParams["sort"]>;

type FilterDraft = {
  q: string;
  role: string;
  skills: string;
  minScore: string;
  recommendation: string;
  salaryMin: string;
  salaryMax: string;
  hireOutcome: string;
  shortlistId: string;
  sort: DashboardSort;
};

const DEFAULT_FILTERS: FilterDraft = {
  q: "",
  role: "",
  skills: "",
  minScore: "",
  recommendation: "",
  salaryMin: "",
  salaryMax: "",
  hireOutcome: "",
  shortlistId: "",
  sort: "score_desc",
};

function parseFilters(draft: FilterDraft): CompanyCandidateSearchParams {
  return {
    q: draft.q.trim() || undefined,
    role: draft.role || undefined,
    skills: draft.skills
      .split(",")
      .map((skill) => skill.trim())
      .filter(Boolean),
    min_score: draft.minScore ? Number(draft.minScore) : undefined,
    recommendation: (draft.recommendation || undefined) as CompanyCandidateSearchParams["recommendation"],
    salary_min: draft.salaryMin ? Number(draft.salaryMin) : undefined,
    salary_max: draft.salaryMax ? Number(draft.salaryMax) : undefined,
    hire_outcome: (draft.hireOutcome || undefined) as CompanyCandidateSearchParams["hire_outcome"],
    shortlist_id: draft.shortlistId || undefined,
    sort: draft.sort || "score_desc",
  };
}

function formatSalary(candidate: CandidateListItem) {
  if (candidate.salary_min == null && candidate.salary_max == null) {
    return null;
  }
  const low = candidate.salary_min ?? candidate.salary_max;
  const high = candidate.salary_max ?? candidate.salary_min;
  if (low == null || high == null) return null;
  return low === high
    ? `${low.toLocaleString()} ${candidate.salary_currency}`
    : `${low.toLocaleString()}–${high.toLocaleString()} ${candidate.salary_currency}`;
}

function formatSalaryBand(
  band: {
    candidate_count: number;
    range_min: number | null;
    median_min: number | null;
    median_max: number | null;
    range_max: number | null;
  } | null,
  currency: string,
) {
  if (!band || band.candidate_count === 0 || band.range_min == null || band.range_max == null) {
    return null;
  }
  return `${Math.round(band.range_min).toLocaleString()}–${Math.round(band.range_max).toLocaleString()} ${currency}`;
}

function normalizeDashboardError(message: string | undefined, fallback: string) {
  if (!message) return fallback;
  const normalized = message.trim().toLowerCase();
  if (normalized === "company access required") {
    return fallback;
  }
  return message;
}

function MetricCard({ label, value, tone = "default" }: { label: string; value: string; tone?: "default" | "good" | "warn" }) {
  const toneClass =
    tone === "good"
      ? "border-green-500/20 bg-green-500/5"
      : tone === "warn"
        ? "border-orange-500/20 bg-orange-500/5"
        : "border-slate-700 bg-slate-800";
  return (
    <div className={`rounded-xl border p-4 ${toneClass}`}>
      <p className="text-slate-400 text-xs uppercase tracking-wide mb-2">{label}</p>
      <p className="text-white text-2xl font-semibold">{value}</p>
    </div>
  );
}

function BreakdownList({ items }: { items: AnalyticsBreakdownItem[] }) {
  const t = useTranslations("companyDashboard");
  if (items.length === 0) {
    return <p className="text-slate-500 text-sm">{t("analytics.noData")}</p>;
  }

  const max = Math.max(...items.map((item) => item.count), 1);
  return (
    <div className="space-y-3">
      {items.map((item) => (
        <div key={item.key}>
          <div className="flex items-center justify-between text-sm mb-1">
            <span className="text-slate-300">{item.label}</span>
            <span className="text-slate-400">{item.count}</span>
          </div>
          <div className="h-2 rounded-full bg-slate-700 overflow-hidden">
            <div
              className="h-full rounded-full bg-blue-500"
              style={{ width: `${(item.count / max) * 100}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

function ComparePanel({ candidates, onRemove }: { candidates: CandidateListItem[]; onRemove: (candidateId: string) => void }) {
  const t = useTranslations("companyDashboard");
  const startT = useTranslations("interviewStart");
  if (candidates.length < 2) return null;

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 mb-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-white font-semibold">{t("compare.title")}</h2>
          <p className="text-slate-400 text-sm">{t("compare.subtitle")}</p>
        </div>
      </div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {candidates.map((candidate) => {
          const rec = REC_STYLES[candidate.hiring_recommendation] ?? REC_STYLES.maybe;
          return (
            <div key={candidate.candidate_id} className="rounded-xl border border-slate-700 bg-slate-900 p-4 space-y-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="text-white font-semibold">{candidate.full_name}</h3>
                  <p className="text-slate-400 text-sm">{startT(`roles.${candidate.target_role}`)}</p>
                </div>
                <button
                  onClick={() => onRemove(candidate.candidate_id)}
                  className="text-slate-500 hover:text-white text-xs transition-colors"
                >
                  {t("compare.remove")}
                </button>
              </div>
              <div className="flex items-center gap-3">
                <span className={`text-xs px-2 py-0.5 rounded-full border ${rec.className}`}>{t(`recommendations.${candidate.hiring_recommendation}`)}</span>
                <span className="text-white font-semibold">
                  {candidate.overall_score != null ? `${candidate.overall_score.toFixed(1)} / 10` : t("compare.noScore")}
                </span>
              </div>
              <div className="text-sm text-slate-300">
                <div className="mb-1">
                  <span className="text-slate-500">{t("compare.salary")}:</span> {formatSalary(candidate) ?? t("analytics.noData")}
                </div>
                <div className="mb-1">
                  <span className="text-slate-500">{t("compare.decision")}:</span> {candidate.hire_outcome ? t(`outcomes.${candidate.hire_outcome}`) : t("compare.unreviewed")}
                </div>
                <div>
                  <span className="text-slate-500">{t("compare.flags")}:</span> {candidate.red_flag_count}
                </div>
              </div>
              {candidate.skill_tags && candidate.skill_tags.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {candidate.skill_tags.slice(0, 6).map((tag) => (
                    <span key={`${candidate.candidate_id}-${tag.skill}`} className="bg-slate-800 text-slate-300 text-xs px-2 py-0.5 rounded-full border border-slate-700">
                      {tag.skill}
                    </span>
                  ))}
                </div>
              )}
              {candidate.interview_summary && (
                <p className="text-slate-400 text-sm line-clamp-4">{candidate.interview_summary}</p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function CompanyDashboardPage() {
  const t = useTranslations("companyDashboard");
  const startT = useTranslations("interviewStart");
  const { user, loading: authLoading, logout } = useAuth({
    redirectTo: "/company/login",
    allowedRoles: ["company_admin", "company_member"],
    unauthorizedRedirectTo: "/candidate/dashboard",
  });
  const [tab, setTab] = useState<DashboardTab>("candidates");
  const [draftFilters, setDraftFilters] = useState<FilterDraft>(DEFAULT_FILTERS);
  const [filters, setFilters] = useState<CompanyCandidateSearchParams>({ sort: "score_desc" });
  const [candidates, setCandidates] = useState<CandidateListItem[]>([]);
  const [shortlists, setShortlists] = useState<CompanyShortlist[]>([]);
  const [selectedCandidateIds, setSelectedCandidateIds] = useState<string[]>([]);
  const [loadingCandidates, setLoadingCandidates] = useState(true);
  const [candidatesError, setCandidatesError] = useState("");
  const [shortlistsLoading, setShortlistsLoading] = useState(true);
  const [shortlistsError, setShortlistsError] = useState("");
  const [newShortlistName, setNewShortlistName] = useState("");
  const [creatingShortlist, setCreatingShortlist] = useState(false);
  const [analyticsOverview, setAnalyticsOverview] = useState<AnalyticsOverview | null>(null);
  const [analyticsFunnel, setAnalyticsFunnel] = useState<AnalyticsFunnel | null>(null);
  const [analyticsSalary, setAnalyticsSalary] = useState<AnalyticsSalary | null>(null);
  const [analyticsLoading, setAnalyticsLoading] = useState(false);
  const [analyticsError, setAnalyticsError] = useState("");
  const companyRole = user?.company_member_role ?? (user?.role === "company_admin" ? "admin" : null);
  const canManagePipeline = companyRole === "admin" || companyRole === "recruiter";
  const pageTitle = {
    candidates: t("tabs.candidates"),
    analytics: t("tabs.analytics"),
  } as const;
  const roleLabel = (value: string) => startT(`roles.${value}`);

  useEffect(() => {
    if (authLoading) return;
    setShortlistsLoading(true);
    setShortlistsError("");
    companyApi
      .listShortlists()
      .then(setShortlists)
      .catch((err) => setShortlistsError(normalizeDashboardError(err.message, t("errors.loadShortlists"))))
      .finally(() => setShortlistsLoading(false));
  }, [authLoading, t]);

  useEffect(() => {
    if (authLoading) return;
    setLoadingCandidates(true);
    setCandidatesError("");
    companyApi
      .listCandidates(filters)
      .then((items) => {
        setCandidates(items);
        setSelectedCandidateIds((current) => current.filter((id) => items.some((item) => item.candidate_id === id)));
      })
      .catch((err) => setCandidatesError(normalizeDashboardError(err.message, t("errors.loadCandidates"))))
      .finally(() => setLoadingCandidates(false));
  }, [authLoading, filters, t]);

  useEffect(() => {
    if (authLoading || tab !== "analytics") return;
    setAnalyticsLoading(true);
    setAnalyticsError("");
    Promise.all([
      companyApi.getAnalyticsOverview(),
      companyApi.getAnalyticsFunnel(),
      companyApi.getAnalyticsSalary({
        role: filters.role,
        shortlist_id: filters.shortlist_id,
      }),
    ])
      .then(([overview, funnel, salary]) => {
        setAnalyticsOverview(overview);
        setAnalyticsFunnel(funnel);
        setAnalyticsSalary(salary);
      })
      .catch((err) => setAnalyticsError(normalizeDashboardError(err.message, t("errors.loadAnalytics"))))
      .finally(() => setAnalyticsLoading(false));
  }, [authLoading, tab, filters.role, filters.shortlist_id, t]);

  async function refreshCandidateWorkspace() {
    const [candidateItems, shortlistItems] = await Promise.all([
      companyApi.listCandidates(filters),
      companyApi.listShortlists(),
    ]);
    setCandidates(candidateItems);
    setShortlists(shortlistItems);
    setSelectedCandidateIds((current) => current.filter((id) => candidateItems.some((item) => item.candidate_id === id)));
  }

  function toggleCandidate(candidateId: string) {
    setSelectedCandidateIds((current) => {
      if (current.includes(candidateId)) {
        return current.filter((id) => id !== candidateId);
      }
      if (current.length >= 3) {
        return [...current.slice(1), candidateId];
      }
      return [...current, candidateId];
    });
  }

  async function handleCreateShortlist(e: React.FormEvent) {
    e.preventDefault();
    if (!newShortlistName.trim()) return;
    if (!canManagePipeline) {
      setShortlistsError(t("errors.viewerReadonly"));
      return;
    }
    setCreatingShortlist(true);
    setShortlistsError("");
    try {
      const created = await companyApi.createShortlist(newShortlistName.trim());
      setShortlists((current) => [created, ...current]);
      setNewShortlistName("");
    } catch (err: unknown) {
      setShortlistsError(err instanceof Error ? normalizeDashboardError(err.message, t("errors.createShortlist")) : t("errors.createShortlist"));
    } finally {
      setCreatingShortlist(false);
    }
  }

  async function handleDeleteShortlist(shortlistId: string) {
    if (!canManagePipeline) {
      setShortlistsError(t("errors.viewerReadonly"));
      return;
    }
    try {
      await companyApi.deleteShortlist(shortlistId);
      if (filters.shortlist_id === shortlistId) {
        const nextDraft = { ...draftFilters, shortlistId: "" };
        setDraftFilters(nextDraft);
        setFilters(parseFilters(nextDraft));
      } else {
        await refreshCandidateWorkspace();
      }
      setShortlists((current) => current.filter((shortlist) => shortlist.shortlist_id !== shortlistId));
    } catch (err: unknown) {
      setShortlistsError(err instanceof Error ? normalizeDashboardError(err.message, t("errors.deleteShortlist")) : t("errors.deleteShortlist"));
    }
  }

  async function toggleShortlistMembership(candidateId: string, shortlistId: string, isMember: boolean) {
    if (!canManagePipeline) {
      setCandidatesError(t("errors.viewerReadonly"));
      return;
    }
    try {
      if (isMember) {
        await companyApi.removeCandidateFromShortlist(shortlistId, candidateId);
      } else {
        await companyApi.addCandidateToShortlist(shortlistId, candidateId);
      }
      await refreshCandidateWorkspace();
    } catch (err: unknown) {
      setCandidatesError(err instanceof Error ? normalizeDashboardError(err.message, t("errors.updateShortlist")) : t("errors.updateShortlist"));
    }
  }

  function applyFilters(e: React.FormEvent) {
    e.preventDefault();
    setFilters(parseFilters(draftFilters));
  }

  function resetFilters() {
    setDraftFilters(DEFAULT_FILTERS);
    setFilters({ sort: "score_desc" });
  }

  const selectedCandidates = candidates.filter((candidate) => selectedCandidateIds.includes(candidate.candidate_id));

  if (authLoading) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="text-slate-400">{t("loading")}</div>
      </div>
    );
  }

  return (
    <div className="ai-shell min-h-screen px-4 py-10">
      <div className="ai-section max-w-7xl mx-auto">
        <CompanyWorkspaceHeader onLogout={logout} />

        <div className="mb-8">
          <section className="ai-panel-strong rounded-[2rem] p-7">
            <div className="ai-kicker mb-5">{t("nav.workspace")}</div>
            <h1 className="text-3xl font-semibold tracking-[-0.03em] text-white">{t("title")}</h1>
            <p className="mt-2 max-w-3xl text-slate-400">{t("subtitle")}</p>
            {companyRole === "viewer" && (
              <p className="mt-2 text-sm text-amber-300">{t("viewerMode")}</p>
            )}
          </section>
        </div>

        <div className="mb-6 flex items-center gap-2">
          {(["candidates", "analytics"] as DashboardTab[]).map((value) => (
            <button
              key={value}
              onClick={() => setTab(value)}
              className={`rounded-xl px-4 py-2.5 text-sm font-medium transition-colors ${
                tab === value
                  ? "ai-button-primary text-white"
                  : "ai-panel border border-white/6 text-slate-400 hover:text-white"
              }`}
            >
              {pageTitle[value]}
            </button>
          ))}
        </div>

        {tab === "candidates" && (
          <>
            <div className="mb-6 grid gap-6 xl:grid-cols-[1.7fr,1fr]">
              <form onSubmit={applyFilters} className="ai-panel rounded-[1.8rem] p-6 space-y-4">
                <div className="flex items-center justify-between">
                  <h2 className="text-white font-semibold">{t("search.title")}</h2>
                  <button type="button" onClick={resetFilters} className="text-slate-400 hover:text-white text-sm transition-colors">
                    {t("search.reset")}
                  </button>
                </div>
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  <input
                    type="text"
                    placeholder={t("search.nameOrEmail")}
                    value={draftFilters.q}
                    onChange={(e) => setDraftFilters({ ...draftFilters, q: e.target.value })}
                    className="ai-input rounded-xl px-4 py-2.5 text-sm"
                  />
                  <DashboardSelect
                    value={draftFilters.role}
                    onChange={(e) => setDraftFilters({ ...draftFilters, role: e.target.value })}
                  >
                    <option value="">{t("search.allRoles")}</option>
                    {ROLE_VALUES.map((value) => (
                      <option key={value} value={value}>{roleLabel(value)}</option>
                    ))}
                  </DashboardSelect>
                  <input
                    type="text"
                    placeholder={t("search.skills")}
                    value={draftFilters.skills}
                    onChange={(e) => setDraftFilters({ ...draftFilters, skills: e.target.value })}
                    className="ai-input rounded-xl px-4 py-2.5 text-sm"
                  />
                  <input
                    type="number"
                    min="0"
                    max="10"
                    step="0.1"
                    placeholder={t("search.minScore")}
                    value={draftFilters.minScore}
                    onChange={(e) => setDraftFilters({ ...draftFilters, minScore: e.target.value })}
                    className="ai-input rounded-xl px-4 py-2.5 text-sm"
                  />
                  <DashboardSelect
                    value={draftFilters.recommendation}
                    onChange={(e) => setDraftFilters({ ...draftFilters, recommendation: e.target.value })}
                  >
                    <option value="">{t("search.allRecommendations")}</option>
                    <option value="strong_yes">{t("recommendations.strong_yes")}</option>
                    <option value="yes">{t("recommendations.yes")}</option>
                    <option value="maybe">{t("recommendations.maybe")}</option>
                    <option value="no">{t("recommendations.no")}</option>
                  </DashboardSelect>
                  <DashboardSelect
                    value={draftFilters.hireOutcome}
                    onChange={(e) => setDraftFilters({ ...draftFilters, hireOutcome: e.target.value })}
                  >
                    <option value="">{t("search.allDecisions")}</option>
                    <option value="hired">{t("outcomes.hired")}</option>
                    <option value="interviewing">{t("outcomes.interviewing")}</option>
                    <option value="rejected">{t("outcomes.rejected")}</option>
                    <option value="no_show">{t("outcomes.no_show")}</option>
                  </DashboardSelect>
                  <input
                    type="number"
                    min="0"
                    placeholder={t("search.salaryMin")}
                    value={draftFilters.salaryMin}
                    onChange={(e) => setDraftFilters({ ...draftFilters, salaryMin: e.target.value })}
                    className="ai-input rounded-xl px-4 py-2.5 text-sm"
                  />
                  <input
                    type="number"
                    min="0"
                    placeholder={t("search.salaryMax")}
                    value={draftFilters.salaryMax}
                    onChange={(e) => setDraftFilters({ ...draftFilters, salaryMax: e.target.value })}
                    className="ai-input rounded-xl px-4 py-2.5 text-sm"
                  />
                  <DashboardSelect
                    value={draftFilters.shortlistId}
                    onChange={(e) => setDraftFilters({ ...draftFilters, shortlistId: e.target.value })}
                  >
                    <option value="">{t("search.allShortlists")}</option>
                    {shortlists.map((shortlist) => (
                      <option key={shortlist.shortlist_id} value={shortlist.shortlist_id}>
                        {shortlist.name}
                      </option>
                    ))}
                  </DashboardSelect>
                  <DashboardSelect
                    value={draftFilters.sort}
                    onChange={(e) => setDraftFilters({ ...draftFilters, sort: e.target.value as DashboardSort })}
                  >
                    <option value="score_desc">{t("search.sortScoreDesc")}</option>
                    <option value="score_asc">{t("search.sortScoreAsc")}</option>
                    <option value="latest">{t("search.sortLatest")}</option>
                    <option value="salary_asc">{t("search.sortSalaryAsc")}</option>
                    <option value="salary_desc">{t("search.sortSalaryDesc")}</option>
                  </DashboardSelect>
                </div>
                <div className="flex items-center justify-between">
                  <p className="text-slate-500 text-sm">
                    {loadingCandidates ? t("search.refreshing") : t("search.resultCount", {count: candidates.length})}
                  </p>
                  <button
                    type="submit"
                    className="ai-button-primary rounded-xl px-4 py-2.5 text-sm font-medium text-white"
                  >
                    {t("search.apply")}
                  </button>
                </div>
              </form>

              <div className="ai-panel rounded-[1.8rem] p-6 space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <h2 className="text-white font-semibold">{t("shortlists.title")}</h2>
                    <p className="text-slate-400 text-sm">{t("shortlists.subtitle")}</p>
                  </div>
                </div>
                <form onSubmit={handleCreateShortlist} className="flex gap-2">
                  <input
                    type="text"
                    value={newShortlistName}
                    onChange={(e) => setNewShortlistName(e.target.value)}
                    placeholder={t("shortlists.placeholder")}
                    disabled={!canManagePipeline}
                    className="ai-input flex-1 rounded-xl px-4 py-2.5 text-sm"
                  />
                  <button
                    type="submit"
                    disabled={creatingShortlist || !canManagePipeline}
                    className="ai-button-primary rounded-xl px-4 py-2.5 text-sm font-medium text-white disabled:opacity-50"
                  >
                    {creatingShortlist ? t("shortlists.creating") : t("shortlists.create")}
                  </button>
                </form>
                {shortlistsError && <p className="text-red-400 text-sm">{shortlistsError}</p>}
                {shortlistsLoading ? (
                  <p className="text-slate-500 text-sm">{t("shortlists.loading")}</p>
                ) : shortlists.length === 0 ? (
                  <p className="text-slate-500 text-sm">{t("shortlists.empty")}</p>
                ) : (
                  <div className="space-y-2">
                    {shortlists.map((shortlist) => (
                      <div key={shortlist.shortlist_id} className="flex items-center justify-between rounded-xl border border-white/6 bg-slate-950/35 px-4 py-3">
                        <div>
                          <p className="text-white text-sm font-medium">{shortlist.name}</p>
                          <p className="text-slate-500 text-xs">{t("shortlists.candidateCount", { count: shortlist.candidate_count })}</p>
                        </div>
                        <button
                          onClick={() => handleDeleteShortlist(shortlist.shortlist_id)}
                          disabled={!canManagePipeline}
                          className="text-slate-500 hover:text-red-400 text-xs transition-colors"
                        >
                          {t("shortlists.delete")}
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            <ComparePanel
              candidates={selectedCandidates}
              onRemove={(candidateId) => setSelectedCandidateIds((current) => current.filter((id) => id !== candidateId))}
            />

            {candidatesError && (
              <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg px-4 py-3 mb-4">
                {candidatesError}
              </div>
            )}

            {loadingCandidates ? (
              <div className="text-center py-16 text-slate-400">{t("candidates.loading")}</div>
            ) : candidates.length === 0 ? (
              <div className="ai-panel rounded-[1.8rem] p-12 text-center">
                <h2 className="text-white font-semibold text-lg mb-2">{t("candidates.emptyTitle")}</h2>
                <p className="text-slate-400 text-sm max-w-lg mx-auto">
                  {t("candidates.emptyDescription")}
                </p>
              </div>
            ) : (
              <div className="space-y-4">
                {candidates.map((candidate) => {
                  const rec = REC_STYLES[candidate.hiring_recommendation] ?? REC_STYLES.maybe;
                  const selected = selectedCandidateIds.includes(candidate.candidate_id);
                  return (
                    <div key={candidate.candidate_id} className="ai-panel rounded-[1.8rem] p-5">
                      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-3 flex-wrap mb-2">
                            <h3 className="text-white font-semibold">{candidate.full_name}</h3>
                            <span className={`text-xs px-2 py-0.5 rounded-full border ${rec.className}`}>{t(`recommendations.${candidate.hiring_recommendation}`)}</span>
                            {candidate.hire_outcome && OUTCOME_LABELS[candidate.hire_outcome] && (
                              <span className={`text-xs px-2 py-0.5 rounded-full ${OUTCOME_LABELS[candidate.hire_outcome].cls}`}>
                                {t(`outcomes.${candidate.hire_outcome}`)}
                              </span>
                            )}
                            {candidate.cheat_risk_score != null && candidate.cheat_risk_score >= 0.7 && (
                              <span className="text-xs px-2 py-0.5 rounded-full bg-red-500/15 text-red-300 border border-red-500/20">
                                {t("candidates.highCheatRisk")}
                              </span>
                            )}
                          </div>
                          <p className="text-slate-400 text-sm">{candidate.email}</p>
                          <p className="text-slate-500 text-sm mt-1">
                            {roleLabel(candidate.target_role)} · {t("candidates.scoreLabel")} {candidate.overall_score != null ? candidate.overall_score.toFixed(1) : "—"} · {t("candidates.salaryLabel")} {formatSalary(candidate) ?? t("analytics.noData")}
                          </p>
                          {candidate.interview_summary && (
                            <p className="text-slate-300 text-sm mt-3 line-clamp-2">{candidate.interview_summary}</p>
                          )}
                          {candidate.skill_tags && candidate.skill_tags.length > 0 && (
                            <div className="flex flex-wrap gap-1.5 mt-3">
                              {candidate.skill_tags.map((tag) => (
                                <span key={`${candidate.candidate_id}-${tag.skill}`} className="bg-slate-900 text-slate-300 text-xs px-2 py-0.5 rounded-full border border-slate-700">
                                  {tag.skill}
                                </span>
                              ))}
                            </div>
                          )}
                          {candidate.shortlists.length > 0 && (
                            <div className="flex flex-wrap gap-1.5 mt-3">
                              {candidate.shortlists.map((membership) => (
                                <span key={membership.shortlist_id} className="bg-blue-500/10 border border-blue-500/20 text-blue-300 text-xs px-2 py-0.5 rounded-full">
                                  {membership.name}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>

                        <div className="xl:w-[320px] shrink-0 space-y-3">
                          <div className="flex items-center justify-between">
                            <Link
                              href={`/company/candidates/${candidate.candidate_id}`}
                              className="text-sm text-blue-400 hover:text-blue-300 transition-colors"
                            >
                              {t("candidates.openProfile")} →
                            </Link>
                            <button
                              onClick={() => toggleCandidate(candidate.candidate_id)}
                              className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${
                                selected
                                  ? "border-blue-500/30 bg-blue-500/10 text-blue-300"
                                  : "border-slate-600 text-slate-400 hover:text-white"
                              }`}
                            >
                              {selected ? t("candidates.selectedForCompare") : t("candidates.selectToCompare")}
                            </button>
                          </div>
                          <div className="rounded-xl border border-white/6 bg-slate-950/35 p-3">
                            <p className="text-slate-500 text-xs uppercase tracking-wide mb-2">{t("candidates.shortlistActions")}</p>
                            {shortlists.length === 0 ? (
                              <p className="text-slate-500 text-sm">{t("candidates.createShortlistPrompt")}</p>
                            ) : (
                              <div className="flex flex-wrap gap-2">
                                {shortlists.map((shortlist) => {
                                  const isMember = candidate.shortlists.some((membership) => membership.shortlist_id === shortlist.shortlist_id);
                                  return (
                                    <button
                                      key={shortlist.shortlist_id}
                                      onClick={() => toggleShortlistMembership(candidate.candidate_id, shortlist.shortlist_id, isMember)}
                                      disabled={!canManagePipeline}
                                      className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
                                        isMember
                                          ? "border-blue-500/30 bg-blue-500/10 text-blue-300"
                                          : "border-slate-600 text-slate-400 hover:text-white"
                                      }`}
                                    >
                                      {isMember ? t("candidates.removeFromShortlist", { name: shortlist.name }) : t("candidates.addToShortlist", { name: shortlist.name })}
                                    </button>
                                  );
                                })}
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </>
        )}

        {tab === "analytics" && (
          <>
            {analyticsError && (
              <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg px-4 py-3 mb-4">
                {analyticsError}
              </div>
            )}

            {analyticsLoading || !analyticsOverview || !analyticsFunnel || !analyticsSalary ? (
              <div className="text-center py-16 text-slate-400">{t("analytics.loading")}</div>
            ) : (
              <div className="space-y-6">
                <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                  <MetricCard label={t("analytics.metrics.marketplaceCandidates")} value={analyticsOverview.total_candidates.toString()} />
                  <MetricCard label={t("analytics.metrics.trackedReports")} value={analyticsOverview.total_reports.toString()} />
                  <MetricCard label={t("analytics.metrics.shortlisted")} value={analyticsOverview.shortlisted_candidates.toString()} tone="good" />
                  <MetricCard label={t("analytics.metrics.flaggedCandidates")} value={analyticsOverview.red_flag_summary.candidates_with_flags.toString()} tone="warn" />
                </div>

                <div className="grid gap-6 xl:grid-cols-2">
                  <div className="ai-panel rounded-[1.8rem] p-5">
                    <h2 className="text-white font-semibold mb-4">{t("analytics.roleBreakdown")}</h2>
                    <BreakdownList items={analyticsOverview.role_breakdown} />
                  </div>
                  <div className="ai-panel rounded-[1.8rem] p-5">
                    <h2 className="text-white font-semibold mb-4">{t("analytics.recommendationBreakdown")}</h2>
                    <BreakdownList items={analyticsOverview.recommendation_breakdown} />
                  </div>
                </div>

                <div className="grid gap-6 xl:grid-cols-2">
                  <div className="ai-panel rounded-[1.8rem] p-5">
                    <h2 className="text-white font-semibold mb-4">{t("analytics.cheatRiskDistribution")}</h2>
                    <BreakdownList items={analyticsOverview.cheat_risk_breakdown} />
                  </div>
                  <div className="ai-panel rounded-[1.8rem] p-5">
                    <h2 className="text-white font-semibold mb-4">{t("analytics.redFlagSummary")}</h2>
                    <div className="grid grid-cols-2 gap-3">
                      <MetricCard label={t("analytics.metrics.candidatesWithFlags")} value={analyticsOverview.red_flag_summary.candidates_with_flags.toString()} tone="warn" />
                      <MetricCard label={t("analytics.metrics.totalFlags")} value={analyticsOverview.red_flag_summary.total_flags.toString()} tone="warn" />
                    </div>
                  </div>
                </div>

                <div className="ai-panel rounded-[1.8rem] p-5">
                  <h2 className="text-white font-semibold mb-4">{t("analytics.funnelTitle")}</h2>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-slate-500 border-b border-slate-700">
                          <th className="text-left py-2 pr-4">{t("analytics.table.recommendation")}</th>
                          <th className="text-left py-2 pr-4">{t("analytics.table.total")}</th>
                          <th className="text-left py-2 pr-4">{t("analytics.table.unreviewed")}</th>
                          <th className="text-left py-2 pr-4">{t("analytics.table.interviewing")}</th>
                          <th className="text-left py-2 pr-4">{t("analytics.table.hired")}</th>
                          <th className="text-left py-2 pr-4">{t("analytics.table.rejected")}</th>
                          <th className="text-left py-2">{t("analytics.table.noShow")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {analyticsFunnel.rows.map((row) => (
                          <tr key={row.recommendation} className="border-b border-slate-800 last:border-b-0">
                            <td className="py-3 pr-4 text-white">{t(`recommendations.${row.recommendation}`)}</td>
                            <td className="py-3 pr-4 text-slate-300">{row.total}</td>
                            <td className="py-3 pr-4 text-slate-300">{row.unreviewed}</td>
                            <td className="py-3 pr-4 text-slate-300">{row.interviewing}</td>
                            <td className="py-3 pr-4 text-green-400">{row.hired}</td>
                            <td className="py-3 pr-4 text-red-400">{row.rejected}</td>
                            <td className="py-3 text-slate-300">{row.no_show}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                <div className="ai-panel rounded-[1.8rem] p-5">
                  <div className="flex items-center justify-between mb-4">
                    <div>
                      <h2 className="text-white font-semibold">{t("analytics.salaryInsights")}</h2>
                      <p className="text-slate-400 text-sm">
                        {filters.role ? t("analytics.filteredRole", { role: roleLabel(filters.role) }) : t("analytics.allRoles")}
                        {filters.shortlist_id ? t("analytics.activeShortlist") : ""}.
                      </p>
                    </div>
                  </div>
                  {analyticsSalary.roles.length === 0 ? (
                    <p className="text-slate-500 text-sm">{t("analytics.noSalaryData")}</p>
                  ) : (
                    <div className="space-y-5">
                      {analyticsSalary.roles.map((roleBlock) => (
                        <div key={roleBlock.role} className="rounded-xl border border-slate-700 bg-slate-900 p-4">
                          <div className="flex items-center justify-between mb-4">
                            <div>
                              <h3 className="text-white font-semibold">
                                {roleLabel(roleBlock.role)} <span className="text-slate-500">· {roleBlock.currency}</span>
                              </h3>
                              <p className="text-slate-500 text-sm">{t("analytics.candidatesWithSalary", { count: roleBlock.candidate_count })}</p>
                            </div>
                          </div>
                          <div className="grid gap-3 md:grid-cols-2 mb-4">
                            <MetricCard
                              label={t("analytics.marketBand")}
                              value={formatSalaryBand(roleBlock.market_band, roleBlock.currency) ?? t("analytics.noData")}
                            />
                            <MetricCard
                              label={t("analytics.shortlistSpread")}
                              value={formatSalaryBand(roleBlock.shortlisted_band, roleBlock.currency) ?? t("analytics.noData")}
                              tone="good"
                            />
                          </div>
                          <div className="grid gap-4 xl:grid-cols-2">
                            <div>
                              <p className="text-slate-500 text-xs uppercase tracking-wide mb-3">{t("analytics.scoreBuckets")}</p>
                              <div className="space-y-2">
                                {roleBlock.buckets.map((bucket) => (
                                  <div key={`${roleBlock.role}-${bucket.score_range}`} className="flex items-center justify-between rounded-lg border border-slate-700 px-3 py-2">
                                    <span className="text-slate-300 text-sm">{bucket.score_range}</span>
                                    <span className="text-slate-400 text-sm">
                                      {bucket.count === 0 || bucket.median_min == null || bucket.median_max == null
                                        ? t("analytics.noData")
                                        : `${Math.round(bucket.median_min).toLocaleString()}–${Math.round(bucket.median_max).toLocaleString()} ${roleBlock.currency}`}
                                    </span>
                                  </div>
                                ))}
                              </div>
                            </div>
                            <div>
                              <p className="text-slate-500 text-xs uppercase tracking-wide mb-3">{t("analytics.outcomeTrends")}</p>
                              <div className="space-y-2">
                                {roleBlock.outcome_trends.map((trend) => (
                                  <div key={`${roleBlock.role}-${trend.outcome}`} className="flex items-center justify-between rounded-lg border border-slate-700 px-3 py-2">
                                    <span className="text-slate-300 text-sm">{t(`outcomes.${trend.outcome as HireOutcome}`)}</span>
                                    <span className="text-slate-400 text-sm">
                                      {trend.count === 0 || trend.median_min == null || trend.median_max == null
                                        ? t("analytics.noData")
                                        : `${Math.round(trend.median_min).toLocaleString()}–${Math.round(trend.median_max).toLocaleString()} ${roleBlock.currency}`}
                                    </span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div className="bg-slate-800 border border-slate-700 rounded-xl p-5">
                  <h2 className="text-white font-semibold mb-4">{t("analytics.templatePerformance")}</h2>
                  {analyticsOverview.template_performance.length === 0 ? (
                    <p className="text-slate-500 text-sm">{t("analytics.noTemplateData")}</p>
                  ) : (
                    <div className="space-y-3">
                      {analyticsOverview.template_performance.map((template) => (
                        <div key={template.template_id} className="flex items-center justify-between rounded-lg border border-slate-700 bg-slate-900 px-4 py-3">
                          <div>
                            <p className="text-white font-medium">{template.template_name}</p>
                            <p className="text-slate-500 text-sm">{roleLabel(template.target_role)}</p>
                          </div>
                          <div className="text-right">
                            <p className="text-white font-semibold">{t("analytics.runs", { count: template.completed_count })}</p>
                            <p className="text-slate-500 text-sm">
                              {t("analytics.avgScore")} {template.average_score != null ? template.average_score.toFixed(2) : "—"}
                            </p>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function DashboardSelect({
  value,
  onChange,
  children,
}: {
  value: string;
  onChange: React.ChangeEventHandler<HTMLSelectElement>;
  children: React.ReactNode;
}) {
  return (
    <div className="relative">
      <select
        value={value}
        onChange={onChange}
        className="ai-select w-full appearance-none rounded-xl px-4 py-2.5 pr-12 text-sm"
      >
        {children}
      </select>
      <span className="pointer-events-none absolute inset-y-0 right-4 flex items-center text-slate-400">
        <svg className="h-4 w-4" viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <path d="M6 8l4 4 4-4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
    </div>
  );
}
