"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { AdminWorkspaceHeader } from "@/components/admin-workspace-header";
import { useAuth } from "@/hooks/useAuth";
import { adminApi } from "@/lib/api";
import type { AdminOverview, AdminRecentCompany, AdminRecentInterview, AdminRecentReport, AdminRecentUser } from "@/lib/types";

function formatDate(value: string) {
  return new Intl.DateTimeFormat("ru-RU", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatInterviewStatus(status: string, t: ReturnType<typeof useTranslations<"admin.dashboard">>) {
  switch (status) {
    case "created":
      return t("statuses.created");
    case "in_progress":
      return t("statuses.in_progress");
    case "completed":
      return t("statuses.completed");
    case "report_generated":
      return t("statuses.report_generated");
    case "failed":
      return t("statuses.failed");
    default:
      return status;
  }
}

function MetricCard({ label, value, helper }: { label: string; value: string; helper: string }) {
  return (
    <div className="ai-stat rounded-3xl p-5">
      <p className="text-xs uppercase tracking-[0.22em] text-slate-500">{label}</p>
      <p className="mt-3 text-3xl font-semibold text-white">{value}</p>
      <p className="mt-2 text-sm text-slate-400">{helper}</p>
    </div>
  );
}

function SectionCard({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <section className="ai-panel rounded-[1.75rem] p-6">
      <div className="mb-5">
        <h2 className="text-xl font-semibold text-white">{title}</h2>
        <p className="mt-1 text-sm text-slate-400">{subtitle}</p>
      </div>
      {children}
    </section>
  );
}

export default function AdminDashboardPage() {
  const t = useTranslations("admin.dashboard");
  const { user, loading: authLoading, logout } = useAuth({
    redirectTo: "/admin/login",
    allowedRoles: ["platform_admin"],
  });
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (authLoading) return;
    setLoading(true);
    setError("");
    adminApi
      .getOverview()
      .then(setOverview)
      .catch((err) => setError(err instanceof Error ? err.message : t("errors.load")))
      .finally(() => setLoading(false));
  }, [authLoading, t]);

  const metrics = overview?.metrics;
  const runtime = overview?.runtime;

  return (
    <div className="ai-shell min-h-screen">
      <div className="ai-section mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
        <AdminWorkspaceHeader onLogout={logout} />

        <section className="ai-panel-strong mb-6 rounded-[2rem] p-7 sm:p-8">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <span className="ai-kicker">{t("hero.badge")}</span>
              <h1 className="mt-5 text-4xl font-semibold leading-tight text-white sm:text-5xl">
                {t("hero.title")}
              </h1>
              <p className="mt-4 max-w-3xl text-lg leading-8 text-slate-300">{t("hero.description")}</p>
            </div>
            <div className="ai-panel rounded-3xl px-5 py-4">
              <p className="text-xs uppercase tracking-[0.22em] text-slate-500">{t("hero.session")}</p>
              <p className="mt-2 text-base font-medium text-white">{user?.email}</p>
              <p className="mt-1 text-sm text-slate-400">{t("hero.role")}</p>
            </div>
          </div>
        </section>

        {error && (
          <div className="mb-6 rounded-[1.4rem] border border-red-500/25 bg-red-500/10 px-5 py-4 text-sm text-red-300">
            {error}
          </div>
        )}

        {loading && (
          <div className="rounded-[1.4rem] border border-slate-700 bg-slate-900/60 px-5 py-10 text-center text-slate-400">
            {t("loading")}
          </div>
        )}

        {!loading && overview && (
          <div className="space-y-6">
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <MetricCard label={t("metrics.users")} value={String(metrics?.total_users ?? 0)} helper={t("metrics.usersHelp")} />
              <MetricCard label={t("metrics.candidates")} value={String(metrics?.active_candidates ?? 0)} helper={t("metrics.candidatesHelp")} />
              <MetricCard label={t("metrics.companies")} value={String(metrics?.active_companies ?? 0)} helper={t("metrics.companiesHelp")} />
              <MetricCard label={t("metrics.reports")} value={String(metrics?.reports_generated ?? 0)} helper={t("metrics.reportsHelp")} />
            </div>

            <div className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
              <SectionCard title={t("runtime.title")} subtitle={t("runtime.subtitle")}>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="rounded-2xl border border-slate-700 bg-slate-900/70 p-4">
                    <p className="text-xs uppercase tracking-[0.22em] text-slate-500">{t("runtime.environment")}</p>
                    <p className="mt-2 text-lg font-semibold text-white">{runtime?.app_env ?? "—"}</p>
                  </div>
                  <div className="rounded-2xl border border-slate-700 bg-slate-900/70 p-4">
                    <p className="text-xs uppercase tracking-[0.22em] text-slate-500">{t("runtime.mockAi")}</p>
                    <p className="mt-2 text-lg font-semibold text-white">
                      {runtime?.mock_ai_enabled ? t("runtime.enabled") : t("runtime.disabled")}
                    </p>
                  </div>
                  <div className="rounded-2xl border border-slate-700 bg-slate-900/70 p-4">
                    <p className="text-xs uppercase tracking-[0.22em] text-slate-500">{t("runtime.rateLimit")}</p>
                    <p className="mt-2 text-lg font-semibold text-white">
                      {runtime?.rate_limit_enabled ? t("runtime.enabled") : t("runtime.disabled")}
                    </p>
                  </div>
                  <div className="rounded-2xl border border-slate-700 bg-slate-900/70 p-4">
                    <p className="text-xs uppercase tracking-[0.22em] text-slate-500">{t("runtime.bootstrap")}</p>
                    <p className="mt-2 text-lg font-semibold text-white">
                      {runtime?.platform_admin_bootstrap_enabled ? t("runtime.enabled") : t("runtime.disabled")}
                    </p>
                  </div>
                </div>
              </SectionCard>

              <SectionCard title={t("throughput.title")} subtitle={t("throughput.subtitle")}>
                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="rounded-2xl border border-slate-700 bg-slate-900/70 p-4">
                    <p className="text-xs uppercase tracking-[0.22em] text-slate-500">{t("throughput.interviews")}</p>
                    <p className="mt-2 text-2xl font-semibold text-white">{metrics?.interviews_total ?? 0}</p>
                  </div>
                  <div className="rounded-2xl border border-slate-700 bg-slate-900/70 p-4">
                    <p className="text-xs uppercase tracking-[0.22em] text-slate-500">{t("throughput.completed")}</p>
                    <p className="mt-2 text-2xl font-semibold text-white">{metrics?.interviews_completed ?? 0}</p>
                  </div>
                  <div className="rounded-2xl border border-slate-700 bg-slate-900/70 p-4">
                    <p className="text-xs uppercase tracking-[0.22em] text-slate-500">{t("throughput.members")}</p>
                    <p className="mt-2 text-2xl font-semibold text-white">{metrics?.company_members ?? 0}</p>
                  </div>
                </div>
              </SectionCard>
            </div>

            <div className="grid gap-6 xl:grid-cols-2">
              <SectionCard title={t("recentUsers.title")} subtitle={t("recentUsers.subtitle")}>
                <div className="space-y-3">
                  {overview.recent_users.map((item: AdminRecentUser) => (
                    <div key={item.id} className="rounded-2xl border border-slate-700 bg-slate-900/70 p-4">
                      <div className="flex items-start justify-between gap-4">
                        <div>
                          <p className="text-white font-medium">{item.email}</p>
                          <p className="mt-1 text-sm text-slate-400">{t(`roles.${item.role}`)}</p>
                        </div>
                        <div className="text-right text-sm text-slate-500">
                          <p>{item.is_active ? t("active") : t("inactive")}</p>
                          <p className="mt-1">{formatDate(item.created_at)}</p>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </SectionCard>

              <SectionCard title={t("recentCompanies.title")} subtitle={t("recentCompanies.subtitle")}>
                <div className="space-y-3">
                  {overview.recent_companies.map((item: AdminRecentCompany) => (
                    <div key={item.id} className="rounded-2xl border border-slate-700 bg-slate-900/70 p-4">
                      <div className="flex items-start justify-between gap-4">
                        <div>
                          <p className="text-white font-medium">{item.name}</p>
                          <p className="mt-1 text-sm text-slate-400">{item.owner_email ?? t("noOwner")}</p>
                        </div>
                        <div className="text-right text-sm text-slate-500">
                          <p>{item.is_active ? t("active") : t("inactive")}</p>
                          <p className="mt-1">{formatDate(item.created_at)}</p>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </SectionCard>
            </div>

            <div className="grid gap-6 xl:grid-cols-2">
              <SectionCard title={t("recentInterviews.title")} subtitle={t("recentInterviews.subtitle")}>
                <div className="space-y-3">
                  {overview.recent_interviews.map((item: AdminRecentInterview) => (
                    <div key={item.id} className="rounded-2xl border border-slate-700 bg-slate-900/70 p-4">
                      <div className="flex items-start justify-between gap-4">
                        <div>
                          <p className="text-white font-medium">{item.candidate_name}</p>
                          <p className="mt-1 text-sm text-slate-400">
                            {item.target_role} · {formatInterviewStatus(item.status, t)}
                          </p>
                        </div>
                        <div className="text-right text-sm text-slate-500">
                          <p>{item.report_ready ? t("reportReady") : t("reportPending")}</p>
                          <p className="mt-1">{formatDate(item.created_at)}</p>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </SectionCard>

              <SectionCard title={t("recentReports.title")} subtitle={t("recentReports.subtitle")}>
                <div className="space-y-3">
                  {overview.recent_reports.map((item: AdminRecentReport) => (
                    <div key={item.id} className="rounded-2xl border border-slate-700 bg-slate-900/70 p-4">
                      <div className="flex items-start justify-between gap-4">
                        <div>
                          <p className="text-white font-medium">{item.candidate_name}</p>
                          <p className="mt-1 text-sm text-slate-400">{item.target_role}</p>
                        </div>
                        <div className="text-right">
                          <p className="text-white font-semibold">
                            {item.overall_score != null ? item.overall_score.toFixed(1) : "—"}
                          </p>
                          <p className="mt-1 text-sm text-slate-500">{formatDate(item.created_at)}</p>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </SectionCard>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
