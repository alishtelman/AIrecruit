"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { LocaleSwitcher } from "@/components/locale-switcher";
import { Link } from "@/i18n/navigation";
import { useAuth } from "@/hooks/useAuth";
import { candidateApi } from "@/lib/api";
import type { CandidateAccessRequest, CandidatePrivacy, ProfileVisibility } from "@/lib/types";

interface Stats {
  has_resume: boolean;
  interview_count: number;
  completed_count: number;
  latest_report_id: string | null;
}

interface Salary {
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string;
}

export default function DashboardPage() {
  const t = useTranslations("candidateDashboard");
  const common = useTranslations("common");
  const { user, loading, logout } = useAuth();
  const [stats, setStats] = useState<Stats | null>(null);
  const [salary, setSalary] = useState<Salary>({ salary_min: null, salary_max: null, salary_currency: "USD" });
  const [salaryMin, setSalaryMin] = useState("");
  const [salaryMax, setSalaryMax] = useState("");
  const [salaryCurrency, setSalaryCurrency] = useState("USD");
  const [savingSalary, setSavingSalary] = useState(false);
  const [salarySaved, setSalarySaved] = useState(false);
  const [privacy, setPrivacy] = useState<CandidatePrivacy>({ visibility: "marketplace", share_token: null });
  const [savingPrivacy, setSavingPrivacy] = useState(false);
  const [privacySaved, setPrivacySaved] = useState(false);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const [accessRequests, setAccessRequests] = useState<CandidateAccessRequest[]>([]);
  const [accessActionId, setAccessActionId] = useState<string | null>(null);

  useEffect(() => {
    if (loading) return;
    candidateApi.stats().then(setStats).catch(() => null);
    candidateApi.getSalary().then((s) => {
      setSalary(s);
      setSalaryMin(s.salary_min?.toString() ?? "");
      setSalaryMax(s.salary_max?.toString() ?? "");
      setSalaryCurrency(s.salary_currency ?? "USD");
    }).catch(() => null);
    candidateApi.getPrivacy().then(setPrivacy).catch(() => null);
    candidateApi.listAccessRequests().then(setAccessRequests).catch(() => null);
  }, [loading]);

  async function handleSaveSalary() {
    setSavingSalary(true);
    try {
      const updated = await candidateApi.updateSalary({
        salary_min: salaryMin ? parseInt(salaryMin) : null,
        salary_max: salaryMax ? parseInt(salaryMax) : null,
        currency: salaryCurrency,
      });
      setSalary(updated);
      setSalarySaved(true);
      setTimeout(() => setSalarySaved(false), 2000);
    } catch {
      // ignore
    } finally {
      setSavingSalary(false);
    }
  }

  async function handleSavePrivacy() {
    setSavingPrivacy(true);
    try {
      const updated = await candidateApi.updatePrivacy(privacy.visibility);
      setPrivacy(updated);
      setPrivacySaved(true);
      setTimeout(() => setPrivacySaved(false), 2000);
    } catch {
      // ignore
    } finally {
      setSavingPrivacy(false);
    }
  }

  async function handleCopyShareLink() {
    if (!privacy.share_token || typeof window === "undefined") return;
    try {
      await navigator.clipboard.writeText(`${window.location.origin}/candidate/share/${privacy.share_token}`);
      setCopyState("copied");
      setTimeout(() => setCopyState("idle"), 2000);
    } catch {
      setCopyState("failed");
      setTimeout(() => setCopyState("idle"), 2000);
    }
  }

  async function handleAccessRequestAction(requestId: string, action: "approve" | "deny") {
    setAccessActionId(requestId);
    try {
      const updated = action === "approve"
        ? await candidateApi.approveAccessRequest(requestId)
        : await candidateApi.denyAccessRequest(requestId);
      setAccessRequests((current) => current.map((item) => (item.request_id === requestId ? updated : item)));
    } catch {
      // ignore
    } finally {
      setAccessActionId(null);
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-900 px-4 py-10">
        <div className="max-w-4xl mx-auto space-y-4">
          <div className="h-7 w-48 bg-slate-800 rounded animate-pulse" />
          <div className="h-4 w-72 bg-slate-800 rounded animate-pulse" />
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-6">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="h-20 bg-slate-800 rounded-xl animate-pulse" />
            ))}
          </div>
          <div className="h-48 bg-slate-800 rounded-xl animate-pulse mt-4" />
        </div>
      </div>
    );
  }

  const step1Done = stats?.has_resume ?? false;
  const step2Done = (stats?.interview_count ?? 0) > 0;
  const step3Done = (stats?.completed_count ?? 0) > 0;
  const visibilityHelp: Record<ProfileVisibility, { title: string; body: string }> = {
    private: {
      title: t("privacy.help.private.title"),
      body: t("privacy.help.private.body"),
    },
    marketplace: {
      title: t("privacy.help.marketplace.title"),
      body: t("privacy.help.marketplace.body"),
    },
    direct_link: {
      title: t("privacy.help.directLink.title"),
      body: t("privacy.help.directLink.body"),
    },
    request_only: {
      title: t("privacy.help.requestOnly.title"),
      body: t("privacy.help.requestOnly.body"),
    },
  };

  return (
    <div className="ai-shell min-h-screen">
      {/* Nav */}
      <header className="ai-section border-b border-slate-800/80 bg-[rgba(5,12,24,0.72)] px-6 py-4 backdrop-blur-xl">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-blue-400/20 bg-blue-500/10 text-sm font-semibold tracking-[0.16em] text-blue-200">
              AR
            </div>
            <div>
              <div className="text-white font-semibold">{common("appName")}</div>
              <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">{t("workspaceLabel")}</div>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <LocaleSwitcher />
            <span className="text-slate-400 text-sm">{user?.email}</span>
            <Link href="/candidate/profile" className="text-slate-400 hover:text-white text-sm transition-colors">
              {t("nav.profile")}
            </Link>
            <button onClick={logout} className="text-slate-400 hover:text-white text-sm transition-colors">
              {common("actions.signOut")}
            </button>
          </div>
        </div>
      </header>

      <main className="ai-section max-w-5xl mx-auto px-4 py-10">
        <div className="mb-8 grid gap-6 lg:grid-cols-[1.15fr_0.85fr] lg:items-start">
          <div className="ai-panel-strong rounded-[2rem] p-7">
            <div className="ai-kicker mb-5">{t("workspaceKicker")}</div>
            <h1 className="text-3xl font-semibold tracking-[-0.03em] text-white mb-2">{t("title")}</h1>
            <p className="max-w-xl text-slate-400">{t("subtitle")}</p>
          </div>
          <div className="ai-panel rounded-[2rem] p-6">
            <p className="text-xs uppercase tracking-[0.24em] text-slate-500">{t("statusTitle")}</p>
            <div className="mt-4 space-y-3">
              <div className="flex items-center justify-between rounded-2xl border border-white/6 bg-white/[0.03] px-4 py-3">
                <span className="text-sm text-slate-400">{t("profileState")}</span>
                <span className="rounded-full border border-emerald-400/20 bg-emerald-400/10 px-2.5 py-1 text-xs font-semibold text-emerald-300">
                  {t("active")}
                </span>
              </div>
              <div className="flex items-center justify-between rounded-2xl border border-white/6 bg-white/[0.03] px-4 py-3">
                <span className="text-sm text-slate-400">{t("privacy.visibility")}</span>
                <span className="text-sm font-medium text-white">{t(`privacy.${privacy.visibility === "direct_link" ? "directLink" : privacy.visibility === "request_only" ? "requestOnly" : privacy.visibility}`)}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Progress summary */}
        {stats && (
          <div className="grid grid-cols-1 gap-4 mb-8 md:grid-cols-3">
            <StatBadge label={t("stats.resume")} done={step1Done} value={step1Done ? t("stats.uploaded") : t("stats.missing")} />
            <StatBadge label={t("stats.interviews")} done={step2Done} value={t("stats.started", {count: stats.interview_count})} />
            <StatBadge label={t("stats.reports")} done={step3Done} value={t("stats.completed", {count: stats.completed_count})} />
          </div>
        )}

        {/* Salary Expectations */}
        <div className="ai-panel rounded-[1.8rem] p-6 mb-6">
          <h2 className="text-white font-semibold mb-4 text-sm uppercase tracking-[0.18em] text-slate-300">{t("salary.title")}</h2>
          <div className="flex flex-wrap gap-3 items-end">
            <div>
              <label className="text-slate-400 text-xs mb-1 block">{t("salary.min")}</label>
              <input
                type="number"
                placeholder="80000"
                value={salaryMin}
                onChange={(e) => setSalaryMin(e.target.value)}
                className="ai-input w-36 rounded-xl px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="text-slate-400 text-xs mb-1 block">{t("salary.max")}</label>
              <input
                type="number"
                placeholder="120000"
                value={salaryMax}
                onChange={(e) => setSalaryMax(e.target.value)}
                className="ai-input w-36 rounded-xl px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="text-slate-400 text-xs mb-1 block">{t("salary.currency")}</label>
              <div className="relative">
                <select
                  value={salaryCurrency}
                  onChange={(e) => setSalaryCurrency(e.target.value)}
                  className="ai-select w-[136px] appearance-none rounded-xl px-3 py-2 pr-12 text-sm"
                >
                  {["USD", "EUR", "GBP", "RUB", "KZT"].map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
                <SelectChevron />
              </div>
            </div>
            <button
              onClick={handleSaveSalary}
              disabled={savingSalary}
              className="ai-button-primary rounded-xl px-4 py-2 text-sm text-white disabled:opacity-50"
            >
              {salarySaved ? t("salary.saved") : savingSalary ? common("actions.saving") : common("actions.save")}
            </button>
          </div>
        </div>

        <div className="ai-panel rounded-[1.8rem] p-6 mb-6">
          <h2 className="text-white font-semibold mb-4 text-sm uppercase tracking-[0.18em] text-slate-300">{t("privacy.title")}</h2>
          <div className="flex flex-wrap gap-3 items-end">
            <div className="min-w-[280px] max-w-md flex-1">
              <label className="text-slate-400 text-xs mb-1 block">{t("privacy.visibility")}</label>
              <div className="relative">
                <select
                  value={privacy.visibility}
                  onChange={(e) => setPrivacy((current) => ({ ...current, visibility: e.target.value as ProfileVisibility }))}
                  className="ai-select w-full appearance-none rounded-xl px-4 py-2 pr-12 text-sm"
                >
                  <option value="marketplace">{t("privacy.marketplace")}</option>
                  <option value="direct_link">{t("privacy.directLink")}</option>
                  <option value="request_only">{t("privacy.requestOnly")}</option>
                  <option value="private">{t("privacy.private")}</option>
                </select>
                <SelectChevron />
              </div>
            </div>
            <button
              onClick={handleSavePrivacy}
              disabled={savingPrivacy}
              className="ai-button-primary rounded-xl px-4 py-2 text-sm text-white disabled:opacity-50"
            >
              {privacySaved ? t("salary.saved") : savingPrivacy ? common("actions.saving") : common("actions.save")}
            </button>
          </div>
          <div className="mt-4 rounded-2xl border border-white/6 bg-slate-950/40 px-4 py-4">
            <p className="text-white text-sm font-medium">{visibilityHelp[privacy.visibility].title}</p>
            <p className="text-slate-400 text-sm mt-1">{visibilityHelp[privacy.visibility].body}</p>
          </div>
          {(privacy.visibility === "direct_link" || privacy.visibility === "request_only") && privacy.share_token && (
            <div className="mt-4 rounded-2xl border border-blue-500/20 bg-blue-500/5 px-4 py-4">
              <p className="text-blue-300 text-sm font-medium mb-1">
                {privacy.visibility === "direct_link" ? t("privacy.shareableLink") : t("privacy.requestLink")}
              </p>
              <p className="text-slate-300 text-sm break-all">/candidate/share/{privacy.share_token}</p>
              <p className="text-slate-400 text-sm mt-2">
                {privacy.visibility === "direct_link"
                  ? t("privacy.shareHelp.directLink")
                  : t("privacy.shareHelp.requestOnly")}
              </p>
              <div className="mt-3 flex flex-wrap gap-3">
                <button
                  onClick={handleCopyShareLink}
                  className="ai-button-primary rounded-xl px-3 py-2 text-sm text-white"
                >
                  {copyState === "copied" ? common("status.copied") : copyState === "failed" ? common("status.copyFailed") : t("privacy.copyLink")}
                </button>
                <Link
                  href={`/candidate/share/${privacy.share_token}`}
                  target="_blank"
                  className="ai-button-secondary rounded-xl px-3 py-2 text-sm"
                >
                  {t("privacy.openSharedProfile")}
                </Link>
              </div>
            </div>
          )}
        </div>

        <div className="ai-panel rounded-[1.8rem] p-6 mb-6">
          <h2 className="text-white font-semibold mb-4 text-sm uppercase tracking-[0.18em] text-slate-300">{t("accessRequests.title")}</h2>
          <p className="mb-4 max-w-3xl text-sm leading-6 text-slate-400">{t("accessRequests.description")}</p>
          {accessRequests.length === 0 ? (
            <p className="text-slate-500 text-sm">{t("accessRequests.empty")}</p>
          ) : (
            <div className="space-y-3">
              {accessRequests.map((request) => (
                <div key={request.request_id} className="rounded-2xl border border-white/6 bg-slate-950/40 px-4 py-4">
                  <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                    <div>
                      <p className="text-white text-sm font-medium">{request.company_name}</p>
                      <p className="text-slate-400 text-xs mt-1">
                        {t("accessRequests.requestedBy", {
                          email: request.requested_by_email ?? t("accessRequests.companyMember"),
                          date: new Date(request.updated_at).toLocaleString(),
                        })}
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className={`px-2.5 py-1 rounded-full text-xs border ${
                        request.status === "approved"
                          ? "bg-green-500/15 text-green-400 border-green-500/30"
                          : request.status === "denied"
                            ? "bg-red-500/15 text-red-400 border-red-500/30"
                            : "bg-blue-500/15 text-blue-400 border-blue-500/30"
                      }`}>
                        {request.status === "approved"
                          ? t("accessRequests.status.approved")
                          : request.status === "denied"
                            ? t("accessRequests.status.denied")
                            : t("accessRequests.status.pending")}
                      </span>
                      {request.status === "pending" && (
                        <>
                          <button
                            onClick={() => handleAccessRequestAction(request.request_id, "approve")}
                            disabled={accessActionId === request.request_id}
                            className="rounded-xl bg-green-600 px-3 py-2 text-xs text-white transition-colors hover:bg-green-500 disabled:opacity-50"
                          >
                            {t("accessRequests.approve")}
                          </button>
                          <button
                            onClick={() => handleAccessRequestAction(request.request_id, "deny")}
                            disabled={accessActionId === request.request_id}
                            className="rounded-xl bg-slate-700 px-3 py-2 text-xs text-white transition-colors hover:bg-slate-600 disabled:opacity-50"
                          >
                            {t("accessRequests.deny")}
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="grid gap-4">
          <StepCard
            step={1}
            href="/candidate/resume"
            icon="CV"
            label={t("steps.uploadResume")}
            desc={t("steps.uploadResumeDesc")}
            done={step1Done}
          />
          <StepCard
            step={2}
            href="/candidate/interview/start"
            icon="AI"
            label={t("steps.startInterview")}
            desc={t("steps.startInterviewDesc")}
            done={step2Done}
            locked={!step1Done}
          />
          <StepCard
            step={3}
            href={stats?.latest_report_id ? `/candidate/reports/${stats.latest_report_id}` : "/candidate/reports"}
            icon="REP"
            label={t("steps.viewReports")}
            desc={step3Done ? t("steps.reportsReady", {count: stats!.completed_count}) : t("steps.viewReportsDesc")}
            done={step3Done}
            locked={!step2Done}
          />
        </div>
      </main>
    </div>
  );
}

function StatBadge({ label, done, value }: { label: string; done: boolean; value: string }) {
  return (
    <div className={`ai-stat rounded-[1.5rem] p-5 text-center ${done ? "border-green-500/20 bg-green-500/8" : ""}`}>
      <div className={`text-[11px] font-medium uppercase tracking-[0.22em] mb-2 ${done ? "text-green-400" : "text-slate-500"}`}>{label}</div>
      <div className={`text-sm font-semibold ${done ? "text-green-300" : "text-slate-300"}`}>{value}</div>
    </div>
  );
}

function StepCard({
  step, href, icon, label, desc, done = false, locked = false,
}: {
  step: number; href: string; icon: string; label: string;
  desc: string; done?: boolean; locked?: boolean;
}) {
  const base = "flex items-center gap-4 border rounded-[1.6rem] p-5 transition-all duration-200 group";
  const style = locked
    ? `${base} border-slate-800 bg-slate-950/60 opacity-50 cursor-not-allowed pointer-events-none`
    : done
    ? `${base} ai-panel border-green-500/20 bg-green-500/5 hover:bg-green-500/10`
    : `${base} ai-panel hover:-translate-y-1 hover:border-slate-500`;

  return (
    <Link href={locked ? "#" : href} className={style}>
      <div className={`w-10 h-10 rounded-full flex items-center justify-center text-sm font-bold shrink-0 border ${
        done ? "bg-green-500/20 border-green-500/40 text-green-400" : "bg-blue-500/10 border-blue-500/20 text-blue-400"
      }`}>
        {done ? "OK" : step}
      </div>
      <span className="rounded-xl border border-white/6 bg-slate-950/50 px-2.5 py-1.5 text-xs font-semibold tracking-[0.18em] text-slate-300">{icon}</span>
      <div className="flex-1">
        <div className={`font-semibold transition-colors ${done ? "text-green-300" : "text-white group-hover:text-blue-400"}`}>{label}</div>
        <div className="text-slate-400 text-sm">{desc}</div>
      </div>
      {!locked && <span className={`text-lg transition-colors ${done ? "text-green-500" : "text-slate-600 group-hover:text-blue-400"}`}>›</span>}
    </Link>
  );
}

function SelectChevron() {
  return (
    <span className="pointer-events-none absolute inset-y-0 right-4 flex items-center text-slate-400">
      <svg className="h-4 w-4" viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <path d="M6 8l4 4 4-4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </span>
  );
}
