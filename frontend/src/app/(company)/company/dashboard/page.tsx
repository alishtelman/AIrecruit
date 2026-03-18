"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
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

const OUTCOME_LABELS: Record<string, { label: string; cls: string }> = {
  hired: { label: "Hired", cls: "bg-green-500/20 text-green-400" },
  rejected: { label: "Rejected", cls: "bg-red-500/20 text-red-400" },
  interviewing: { label: "Interviewing", cls: "bg-blue-500/20 text-blue-400" },
  no_show: { label: "No Show", cls: "bg-slate-500/20 text-slate-400" },
};

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
  yes: { label: "Yes", className: "bg-blue-500/15 text-blue-400 border-blue-500/30" },
  maybe: { label: "Maybe", className: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30" },
  no: { label: "No", className: "bg-red-500/15 text-red-400 border-red-500/30" },
};

const PAGE_TITLE = {
  candidates: "Candidates",
  analytics: "Analytics",
} as const;

type DashboardTab = keyof typeof PAGE_TITLE;

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
  sort: CompanyCandidateSearchParams["sort"];
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
    return "Not provided";
  }
  const low = candidate.salary_min ?? candidate.salary_max;
  const high = candidate.salary_max ?? candidate.salary_min;
  if (low == null || high == null) return "Not provided";
  return low === high
    ? `${low.toLocaleString()} ${candidate.salary_currency}`
    : `${low.toLocaleString()}–${high.toLocaleString()} ${candidate.salary_currency}`;
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
  if (items.length === 0) {
    return <p className="text-slate-500 text-sm">No data yet.</p>;
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
  if (candidates.length < 2) return null;

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 mb-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-white font-semibold">Compare Candidates</h2>
          <p className="text-slate-400 text-sm">Side-by-side view of your selected shortlist picks.</p>
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
                  <p className="text-slate-400 text-sm">{ROLE_LABELS[candidate.target_role] ?? candidate.target_role}</p>
                </div>
                <button
                  onClick={() => onRemove(candidate.candidate_id)}
                  className="text-slate-500 hover:text-white text-xs transition-colors"
                >
                  Remove
                </button>
              </div>
              <div className="flex items-center gap-3">
                <span className={`text-xs px-2 py-0.5 rounded-full border ${rec.className}`}>{rec.label}</span>
                <span className="text-white font-semibold">
                  {candidate.overall_score != null ? `${candidate.overall_score.toFixed(1)} / 10` : "No score"}
                </span>
              </div>
              <div className="text-sm text-slate-300">
                <div className="mb-1">
                  <span className="text-slate-500">Salary:</span> {formatSalary(candidate)}
                </div>
                <div className="mb-1">
                  <span className="text-slate-500">Decision:</span> {candidate.hire_outcome ? OUTCOME_LABELS[candidate.hire_outcome]?.label ?? candidate.hire_outcome : "Unreviewed"}
                </div>
                <div>
                  <span className="text-slate-500">Flags:</span> {candidate.red_flag_count}
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
  const { user, loading: authLoading, logout } = useAuth("/company/login");
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

  useEffect(() => {
    if (authLoading) return;
    setShortlistsLoading(true);
    setShortlistsError("");
    companyApi
      .listShortlists()
      .then(setShortlists)
      .catch((err) => setShortlistsError(err.message ?? "Failed to load shortlists"))
      .finally(() => setShortlistsLoading(false));
  }, [authLoading]);

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
      .catch((err) => setCandidatesError(err.message ?? "Failed to load candidates"))
      .finally(() => setLoadingCandidates(false));
  }, [authLoading, filters]);

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
      .catch((err) => setAnalyticsError(err.message ?? "Failed to load analytics"))
      .finally(() => setAnalyticsLoading(false));
  }, [authLoading, tab, filters.role, filters.shortlist_id]);

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
      setShortlistsError("Viewer access is read-only");
      return;
    }
    setCreatingShortlist(true);
    setShortlistsError("");
    try {
      const created = await companyApi.createShortlist(newShortlistName.trim());
      setShortlists((current) => [created, ...current]);
      setNewShortlistName("");
    } catch (err: unknown) {
      setShortlistsError(err instanceof Error ? err.message : "Failed to create shortlist");
    } finally {
      setCreatingShortlist(false);
    }
  }

  async function handleDeleteShortlist(shortlistId: string) {
    if (!canManagePipeline) {
      setShortlistsError("Viewer access is read-only");
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
      setShortlistsError(err instanceof Error ? err.message : "Failed to delete shortlist");
    }
  }

  async function toggleShortlistMembership(candidateId: string, shortlistId: string, isMember: boolean) {
    if (!canManagePipeline) {
      setCandidatesError("Viewer access is read-only");
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
      setCandidatesError(err instanceof Error ? err.message : "Failed to update shortlist");
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
        <div className="text-slate-400">Loading company workspace…</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-900 px-4 py-8">
      <div className="max-w-7xl mx-auto">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-white">Company Hiring OS</h1>
            <p className="text-slate-400 text-sm mt-1">Search, shortlist, compare, and analyze verified AI interview results.</p>
            {companyRole === "viewer" && (
              <p className="text-amber-300 text-sm mt-2">Viewer mode: reports, replay, and analytics are available read-only.</p>
            )}
          </div>
          <div className="flex items-center gap-3 flex-wrap">
            <Link href="/company/templates" className="text-slate-400 hover:text-white text-sm transition-colors">Templates</Link>
            <Link href="/company/employees" className="text-slate-400 hover:text-white text-sm transition-colors">Employees</Link>
            <Link href="/company/team" className="text-slate-400 hover:text-white text-sm transition-colors">Team</Link>
            <Link href="/company/settings" className="text-slate-400 hover:text-white text-sm transition-colors">Settings</Link>
            <button onClick={logout} className="text-slate-400 hover:text-white text-sm transition-colors">Sign out</button>
          </div>
        </div>

        <div className="flex items-center gap-2 mb-6">
          {(["candidates", "analytics"] as DashboardTab[]).map((value) => (
            <button
              key={value}
              onClick={() => setTab(value)}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                tab === value
                  ? "bg-blue-600 text-white"
                  : "bg-slate-800 text-slate-400 hover:text-white"
              }`}
            >
              {PAGE_TITLE[value]}
            </button>
          ))}
        </div>

        {tab === "candidates" && (
          <>
            <div className="grid gap-6 xl:grid-cols-[1.7fr,1fr] mb-6">
              <form onSubmit={applyFilters} className="bg-slate-800 border border-slate-700 rounded-xl p-5 space-y-4">
                <div className="flex items-center justify-between">
                  <h2 className="text-white font-semibold">Server-side Candidate Search</h2>
                  <button type="button" onClick={resetFilters} className="text-slate-400 hover:text-white text-sm transition-colors">
                    Reset
                  </button>
                </div>
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  <input
                    type="text"
                    placeholder="Name or email"
                    value={draftFilters.q}
                    onChange={(e) => setDraftFilters({ ...draftFilters, q: e.target.value })}
                    className="bg-slate-700 border border-slate-600 text-white rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                  <select
                    value={draftFilters.role}
                    onChange={(e) => setDraftFilters({ ...draftFilters, role: e.target.value })}
                    className="bg-slate-700 border border-slate-600 text-white rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="">All roles</option>
                    {Object.entries(ROLE_LABELS).map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </select>
                  <input
                    type="text"
                    placeholder="Skills, comma separated"
                    value={draftFilters.skills}
                    onChange={(e) => setDraftFilters({ ...draftFilters, skills: e.target.value })}
                    className="bg-slate-700 border border-slate-600 text-white rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                  <input
                    type="number"
                    min="0"
                    max="10"
                    step="0.1"
                    placeholder="Min score"
                    value={draftFilters.minScore}
                    onChange={(e) => setDraftFilters({ ...draftFilters, minScore: e.target.value })}
                    className="bg-slate-700 border border-slate-600 text-white rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                  <select
                    value={draftFilters.recommendation}
                    onChange={(e) => setDraftFilters({ ...draftFilters, recommendation: e.target.value })}
                    className="bg-slate-700 border border-slate-600 text-white rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="">All recommendations</option>
                    <option value="strong_yes">Strong Yes</option>
                    <option value="yes">Yes</option>
                    <option value="maybe">Maybe</option>
                    <option value="no">No</option>
                  </select>
                  <select
                    value={draftFilters.hireOutcome}
                    onChange={(e) => setDraftFilters({ ...draftFilters, hireOutcome: e.target.value })}
                    className="bg-slate-700 border border-slate-600 text-white rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="">All decisions</option>
                    <option value="hired">Hired</option>
                    <option value="interviewing">Interviewing</option>
                    <option value="rejected">Rejected</option>
                    <option value="no_show">No Show</option>
                  </select>
                  <input
                    type="number"
                    min="0"
                    placeholder="Salary min"
                    value={draftFilters.salaryMin}
                    onChange={(e) => setDraftFilters({ ...draftFilters, salaryMin: e.target.value })}
                    className="bg-slate-700 border border-slate-600 text-white rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                  <input
                    type="number"
                    min="0"
                    placeholder="Salary max"
                    value={draftFilters.salaryMax}
                    onChange={(e) => setDraftFilters({ ...draftFilters, salaryMax: e.target.value })}
                    className="bg-slate-700 border border-slate-600 text-white rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                  <select
                    value={draftFilters.shortlistId}
                    onChange={(e) => setDraftFilters({ ...draftFilters, shortlistId: e.target.value })}
                    className="bg-slate-700 border border-slate-600 text-white rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="">All shortlists</option>
                    {shortlists.map((shortlist) => (
                      <option key={shortlist.shortlist_id} value={shortlist.shortlist_id}>
                        {shortlist.name}
                      </option>
                    ))}
                  </select>
                  <select
                    value={draftFilters.sort}
                    onChange={(e) => setDraftFilters({ ...draftFilters, sort: e.target.value as FilterDraft["sort"] })}
                    className="bg-slate-700 border border-slate-600 text-white rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="score_desc">Sort: Score desc</option>
                    <option value="score_asc">Sort: Score asc</option>
                    <option value="latest">Sort: Latest</option>
                    <option value="salary_asc">Sort: Salary asc</option>
                    <option value="salary_desc">Sort: Salary desc</option>
                  </select>
                </div>
                <div className="flex items-center justify-between">
                  <p className="text-slate-500 text-sm">
                    {loadingCandidates ? "Refreshing server-side results…" : `${candidates.length} candidates in result set`}
                  </p>
                  <button
                    type="submit"
                    className="bg-blue-600 hover:bg-blue-500 text-white font-medium text-sm px-4 py-2 rounded-lg transition-colors"
                  >
                    Apply Filters
                  </button>
                </div>
              </form>

              <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <h2 className="text-white font-semibold">Shortlists</h2>
                    <p className="text-slate-400 text-sm">Create named buckets and reuse them across filters and compare flows.</p>
                  </div>
                </div>
                <form onSubmit={handleCreateShortlist} className="flex gap-2">
                  <input
                    type="text"
                    value={newShortlistName}
                    onChange={(e) => setNewShortlistName(e.target.value)}
                    placeholder="e.g. Backend Finalists"
                    disabled={!canManagePipeline}
                    className="flex-1 bg-slate-700 border border-slate-600 text-white rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                  <button
                    type="submit"
                    disabled={creatingShortlist || !canManagePipeline}
                    className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
                  >
                    {creatingShortlist ? "Creating…" : "Create"}
                  </button>
                </form>
                {shortlistsError && <p className="text-red-400 text-sm">{shortlistsError}</p>}
                {shortlistsLoading ? (
                  <p className="text-slate-500 text-sm">Loading shortlists…</p>
                ) : shortlists.length === 0 ? (
                  <p className="text-slate-500 text-sm">No shortlists yet.</p>
                ) : (
                  <div className="space-y-2">
                    {shortlists.map((shortlist) => (
                      <div key={shortlist.shortlist_id} className="flex items-center justify-between rounded-lg border border-slate-700 bg-slate-900 px-3 py-2">
                        <div>
                          <p className="text-white text-sm font-medium">{shortlist.name}</p>
                          <p className="text-slate-500 text-xs">{shortlist.candidate_count} candidate{shortlist.candidate_count !== 1 ? "s" : ""}</p>
                        </div>
                        <button
                          onClick={() => handleDeleteShortlist(shortlist.shortlist_id)}
                          disabled={!canManagePipeline}
                          className="text-slate-500 hover:text-red-400 text-xs transition-colors"
                        >
                          Delete
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
              <div className="text-center py-16 text-slate-400">Loading candidates…</div>
            ) : candidates.length === 0 ? (
              <div className="bg-slate-800 border border-slate-700 rounded-xl p-12 text-center">
                <h2 className="text-white font-semibold text-lg mb-2">No candidates found</h2>
                <p className="text-slate-400 text-sm max-w-lg mx-auto">
                  Adjust the server-side filters or wait for more candidates to complete AI interviews.
                </p>
              </div>
            ) : (
              <div className="space-y-4">
                {candidates.map((candidate) => {
                  const rec = REC_STYLES[candidate.hiring_recommendation] ?? REC_STYLES.maybe;
                  const selected = selectedCandidateIds.includes(candidate.candidate_id);
                  return (
                    <div key={candidate.candidate_id} className="bg-slate-800 border border-slate-700 rounded-xl p-5">
                      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-3 flex-wrap mb-2">
                            <h3 className="text-white font-semibold">{candidate.full_name}</h3>
                            <span className={`text-xs px-2 py-0.5 rounded-full border ${rec.className}`}>{rec.label}</span>
                            {candidate.hire_outcome && OUTCOME_LABELS[candidate.hire_outcome] && (
                              <span className={`text-xs px-2 py-0.5 rounded-full ${OUTCOME_LABELS[candidate.hire_outcome].cls}`}>
                                {OUTCOME_LABELS[candidate.hire_outcome].label}
                              </span>
                            )}
                            {candidate.cheat_risk_score != null && candidate.cheat_risk_score >= 0.7 && (
                              <span className="text-xs px-2 py-0.5 rounded-full bg-red-500/15 text-red-300 border border-red-500/20">
                                High cheat risk
                              </span>
                            )}
                          </div>
                          <p className="text-slate-400 text-sm">{candidate.email}</p>
                          <p className="text-slate-500 text-sm mt-1">
                            {ROLE_LABELS[candidate.target_role] ?? candidate.target_role} · Score {candidate.overall_score != null ? candidate.overall_score.toFixed(1) : "—"} · Salary {formatSalary(candidate)}
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
                              Open profile →
                            </Link>
                            <button
                              onClick={() => toggleCandidate(candidate.candidate_id)}
                              className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${
                                selected
                                  ? "border-blue-500/30 bg-blue-500/10 text-blue-300"
                                  : "border-slate-600 text-slate-400 hover:text-white"
                              }`}
                            >
                              {selected ? "Selected for compare" : "Select to compare"}
                            </button>
                          </div>
                          <div className="rounded-lg border border-slate-700 bg-slate-900 p-3">
                            <p className="text-slate-500 text-xs uppercase tracking-wide mb-2">Shortlist Actions</p>
                            {shortlists.length === 0 ? (
                              <p className="text-slate-500 text-sm">Create a shortlist to start organizing candidates.</p>
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
                                      {isMember ? `Remove ${shortlist.name}` : `Add ${shortlist.name}`}
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
              <div className="text-center py-16 text-slate-400">Loading analytics…</div>
            ) : (
              <div className="space-y-6">
                <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                  <MetricCard label="Marketplace Candidates" value={analyticsOverview.total_candidates.toString()} />
                  <MetricCard label="Tracked Reports" value={analyticsOverview.total_reports.toString()} />
                  <MetricCard label="Shortlisted" value={analyticsOverview.shortlisted_candidates.toString()} tone="good" />
                  <MetricCard label="Flagged Candidates" value={analyticsOverview.red_flag_summary.candidates_with_flags.toString()} tone="warn" />
                </div>

                <div className="grid gap-6 xl:grid-cols-2">
                  <div className="bg-slate-800 border border-slate-700 rounded-xl p-5">
                    <h2 className="text-white font-semibold mb-4">Role Breakdown</h2>
                    <BreakdownList items={analyticsOverview.role_breakdown} />
                  </div>
                  <div className="bg-slate-800 border border-slate-700 rounded-xl p-5">
                    <h2 className="text-white font-semibold mb-4">Recommendation Breakdown</h2>
                    <BreakdownList items={analyticsOverview.recommendation_breakdown} />
                  </div>
                </div>

                <div className="grid gap-6 xl:grid-cols-2">
                  <div className="bg-slate-800 border border-slate-700 rounded-xl p-5">
                    <h2 className="text-white font-semibold mb-4">Cheat Risk Distribution</h2>
                    <BreakdownList items={analyticsOverview.cheat_risk_breakdown} />
                  </div>
                  <div className="bg-slate-800 border border-slate-700 rounded-xl p-5">
                    <h2 className="text-white font-semibold mb-4">Red Flag Summary</h2>
                    <div className="grid grid-cols-2 gap-3">
                      <MetricCard label="Candidates with Flags" value={analyticsOverview.red_flag_summary.candidates_with_flags.toString()} tone="warn" />
                      <MetricCard label="Total Flags" value={analyticsOverview.red_flag_summary.total_flags.toString()} tone="warn" />
                    </div>
                  </div>
                </div>

                <div className="bg-slate-800 border border-slate-700 rounded-xl p-5">
                  <h2 className="text-white font-semibold mb-4">Recommendation to Outcome Funnel</h2>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-slate-500 border-b border-slate-700">
                          <th className="text-left py-2 pr-4">Recommendation</th>
                          <th className="text-left py-2 pr-4">Total</th>
                          <th className="text-left py-2 pr-4">Unreviewed</th>
                          <th className="text-left py-2 pr-4">Interviewing</th>
                          <th className="text-left py-2 pr-4">Hired</th>
                          <th className="text-left py-2 pr-4">Rejected</th>
                          <th className="text-left py-2">No Show</th>
                        </tr>
                      </thead>
                      <tbody>
                        {analyticsFunnel.rows.map((row) => (
                          <tr key={row.recommendation} className="border-b border-slate-800 last:border-b-0">
                            <td className="py-3 pr-4 text-white">{REC_STYLES[row.recommendation]?.label ?? row.recommendation}</td>
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

                <div className="bg-slate-800 border border-slate-700 rounded-xl p-5">
                  <div className="flex items-center justify-between mb-4">
                    <div>
                      <h2 className="text-white font-semibold">Salary Insights</h2>
                      <p className="text-slate-400 text-sm">
                        {filters.role ? `Filtered to ${ROLE_LABELS[filters.role] ?? filters.role}` : "All roles"}{filters.shortlist_id ? " and active shortlist filter" : ""}.
                      </p>
                    </div>
                  </div>
                  {analyticsSalary.roles.length === 0 ? (
                    <p className="text-slate-500 text-sm">No salary data yet for the current analytics filter.</p>
                  ) : (
                    <div className="space-y-5">
                      {analyticsSalary.roles.map((roleBlock) => (
                        <div key={roleBlock.role} className="rounded-xl border border-slate-700 bg-slate-900 p-4">
                          <div className="flex items-center justify-between mb-4">
                            <div>
                              <h3 className="text-white font-semibold">{ROLE_LABELS[roleBlock.role] ?? roleBlock.role}</h3>
                              <p className="text-slate-500 text-sm">{roleBlock.candidate_count} candidates with salary data</p>
                            </div>
                          </div>
                          <div className="grid gap-4 xl:grid-cols-2">
                            <div>
                              <p className="text-slate-500 text-xs uppercase tracking-wide mb-3">Score Buckets</p>
                              <div className="space-y-2">
                                {roleBlock.buckets.map((bucket) => (
                                  <div key={`${roleBlock.role}-${bucket.score_range}`} className="flex items-center justify-between rounded-lg border border-slate-700 px-3 py-2">
                                    <span className="text-slate-300 text-sm">{bucket.score_range}</span>
                                    <span className="text-slate-400 text-sm">
                                      {bucket.count === 0 || bucket.median_min == null || bucket.median_max == null
                                        ? "No data"
                                        : `${Math.round(bucket.median_min).toLocaleString()}–${Math.round(bucket.median_max).toLocaleString()}`}
                                    </span>
                                  </div>
                                ))}
                              </div>
                            </div>
                            <div>
                              <p className="text-slate-500 text-xs uppercase tracking-wide mb-3">Outcome Trends</p>
                              <div className="space-y-2">
                                {roleBlock.outcome_trends.map((trend) => (
                                  <div key={`${roleBlock.role}-${trend.outcome}`} className="flex items-center justify-between rounded-lg border border-slate-700 px-3 py-2">
                                    <span className="text-slate-300 text-sm">{OUTCOME_LABELS[trend.outcome as HireOutcome]?.label ?? trend.outcome}</span>
                                    <span className="text-slate-400 text-sm">
                                      {trend.count === 0 || trend.median_min == null || trend.median_max == null
                                        ? "No data"
                                        : `${Math.round(trend.median_min).toLocaleString()}–${Math.round(trend.median_max).toLocaleString()}`}
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
                  <h2 className="text-white font-semibold mb-4">Template Performance</h2>
                  {analyticsOverview.template_performance.length === 0 ? (
                    <p className="text-slate-500 text-sm">No template-linked public interview data yet.</p>
                  ) : (
                    <div className="space-y-3">
                      {analyticsOverview.template_performance.map((template) => (
                        <div key={template.template_id} className="flex items-center justify-between rounded-lg border border-slate-700 bg-slate-900 px-4 py-3">
                          <div>
                            <p className="text-white font-medium">{template.template_name}</p>
                            <p className="text-slate-500 text-sm">{ROLE_LABELS[template.target_role] ?? template.target_role}</p>
                          </div>
                          <div className="text-right">
                            <p className="text-white font-semibold">{template.completed_count} runs</p>
                            <p className="text-slate-500 text-sm">
                              Avg score {template.average_score != null ? template.average_score.toFixed(2) : "—"}
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
