"use client";

import { useCallback, useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { AdminWorkspaceHeader } from "@/components/admin-workspace-header";
import { Link } from "@/i18n/navigation";
import { useAuth } from "@/hooks/useAuth";
import { adminApi } from "@/lib/api";
import type { AdminInterviewListItem } from "@/lib/types";

function formatDate(value: string, locale: string) {
  return new Intl.DateTimeFormat(locale, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export default function AdminInterviewsPage() {
  const t = useTranslations("admin.interviews");
  const dashboard = useTranslations("admin.dashboard");
  const locale = useLocale();
  const { loading: authLoading, logout } = useAuth({
    redirectTo: "/admin/login",
    allowedRoles: ["platform_admin"],
  });
  const [items, setItems] = useState<AdminInterviewListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const payload = await adminApi.listInterviews({ q, status, limit: 50 });
      setItems(payload.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("errors.load"));
    } finally {
      setLoading(false);
    }
  }, [q, status, t]);

  useEffect(() => {
    if (authLoading) return;
    void load();
  }, [authLoading, load]);

  async function requeue(interviewId: string) {
    if (!window.confirm(t("confirmRequeue"))) return;
    setBusyId(interviewId);
    setError("");
    try {
      await adminApi.requeueInterviewReport(interviewId);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("errors.requeue"));
    } finally {
      setBusyId(null);
    }
  }

  function formatInterviewStatus(statusValue: string) {
    switch (statusValue) {
      case "created":
        return "created";
      case "in_progress":
        return "in_progress";
      case "completed":
        return "completed";
      case "report_generated":
        return "report_generated";
      case "failed":
        return "failed";
      default:
        return statusValue;
    }
  }

  return (
    <div className="ai-shell min-h-screen">
      <div className="ai-section mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
        <AdminWorkspaceHeader onLogout={logout} />

        <section className="ai-panel-strong rounded-[2rem] p-7 sm:p-8">
          <span className="ai-kicker">{t("title")}</span>
          <p className="mt-4 max-w-3xl text-lg leading-8 text-slate-300">{t("description")}</p>
        </section>

        {error && <div className="mt-6 rounded-2xl border border-red-500/25 bg-red-500/10 px-5 py-4 text-sm text-red-300">{error}</div>}

        <section className="ai-panel mt-6 rounded-[1.75rem] p-6">
          <div className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr_auto]">
            <input
              className="ai-input min-h-12 rounded-2xl px-4"
              placeholder={t("filters.search")}
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
            <select
              className="ai-input min-h-12 appearance-none rounded-2xl px-4 pr-12"
              value={status}
              onChange={(e) => setStatus(e.target.value)}
            >
              <option value="">{t("filters.all")}</option>
              <option value="created">{dashboard("statuses.created")}</option>
              <option value="in_progress">{dashboard("statuses.in_progress")}</option>
              <option value="completed">{dashboard("statuses.completed")}</option>
              <option value="report_generated">{dashboard("statuses.report_generated")}</option>
              <option value="failed">{dashboard("statuses.failed")}</option>
            </select>
            <button type="button" onClick={load} className="ai-button-primary rounded-full px-5 py-3 text-sm font-semibold">
              {t("actions.refresh")}
            </button>
          </div>
        </section>

        {loading ? (
          <div className="mt-6 rounded-2xl border border-slate-700 bg-slate-900/60 px-5 py-8 text-center text-slate-400">{t("loading")}</div>
        ) : items.length === 0 ? (
          <div className="mt-6 rounded-2xl border border-slate-700 bg-slate-900/60 px-5 py-8 text-center text-slate-400">{t("empty")}</div>
        ) : (
          <section className="ai-panel mt-6 overflow-hidden rounded-[1.75rem]">
            <div className="grid grid-cols-[1.4fr_1fr_0.9fr_0.9fr_0.7fr_1fr_1.1fr] gap-4 border-b border-slate-800 px-6 py-4 text-xs uppercase tracking-[0.22em] text-slate-500">
              <div>{t("table.candidate")}</div>
              <div>{t("table.role")}</div>
              <div>{t("table.status")}</div>
              <div>{t("table.report")}</div>
              <div>{t("table.score")}</div>
              <div>{t("table.created")}</div>
              <div />
            </div>
            <div className="divide-y divide-slate-800">
              {items.map((item) => (
                <div key={item.id} className="grid grid-cols-[1.4fr_1fr_0.9fr_0.9fr_0.7fr_1fr_1.1fr] gap-4 px-6 py-4 text-sm">
                  <div>
                    <p className="font-medium text-white">{item.candidate_name}</p>
                    <p className="mt-1 text-slate-500">{item.candidate_email}</p>
                  </div>
                  <div className="text-slate-300">{item.target_role}</div>
                  <div className="text-slate-300">{dashboard(`statuses.${formatInterviewStatus(item.status)}` as never) || item.status}</div>
                  <div className="text-slate-300">{t(`processing.${item.processing_state}` as never) || item.processing_state}</div>
                  <div className="text-white">{item.overall_score != null ? item.overall_score.toFixed(1) : "—"}</div>
                  <div className="text-slate-400">{formatDate(item.created_at, locale)}</div>
                  <div className="flex justify-end gap-2">
                    {item.report_id && (
                      <Link
                        href={`/admin/reports/${item.report_id}`}
                        className="rounded-full border border-blue-500/30 bg-blue-500/10 px-4 py-2 text-xs font-semibold text-blue-200 transition hover:border-blue-400/50 hover:text-white"
                      >
                        {t("actions.openReport")}
                      </Link>
                    )}
                    <button
                      type="button"
                      onClick={() => requeue(item.id)}
                      disabled={busyId === item.id || item.status === "in_progress" || item.status === "created"}
                      className="rounded-full border border-white/10 px-4 py-2 text-xs font-semibold text-slate-200 transition hover:border-white/20 hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {busyId === item.id ? t("actions.requeueing") : t("actions.requeue")}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
