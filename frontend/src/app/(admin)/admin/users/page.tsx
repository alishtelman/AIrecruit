"use client";

import { useCallback, useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { AdminWorkspaceHeader } from "@/components/admin-workspace-header";
import { useAuth } from "@/hooks/useAuth";
import { adminApi } from "@/lib/api";
import type { AdminUserListItem } from "@/lib/types";

function formatDate(value: string, locale: string) {
  return new Intl.DateTimeFormat(locale, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export default function AdminUsersPage() {
  const t = useTranslations("admin.users");
  const dashboard = useTranslations("admin.dashboard");
  const locale = useLocale();
  const { loading: authLoading, logout } = useAuth({
    redirectTo: "/admin/login",
    allowedRoles: ["platform_admin"],
  });
  const [items, setItems] = useState<AdminUserListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const payload = await adminApi.listUsers({ q, limit: 100 });
      setItems(payload.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("errors.load"));
    } finally {
      setLoading(false);
    }
  }, [q, t]);

  useEffect(() => {
    if (authLoading) return;
    void load();
  }, [authLoading, load]);

  async function toggleUser(userId: string, nextActive: boolean) {
    setBusyId(userId);
    setError("");
    try {
      await adminApi.setUserStatus(userId, nextActive);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("errors.update"));
    } finally {
      setBusyId(null);
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
          <div className="grid gap-4 lg:grid-cols-[1fr_auto]">
            <input
              className="ai-input min-h-12 rounded-2xl px-4"
              placeholder={t("filters.search")}
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
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
            <div className="grid grid-cols-[1.4fr_0.9fr_0.8fr_1fr_0.9fr] gap-4 border-b border-slate-800 px-6 py-4 text-xs uppercase tracking-[0.22em] text-slate-500">
              <div>{t("table.email")}</div>
              <div>{t("table.role")}</div>
              <div>{t("table.status")}</div>
              <div>{t("table.created")}</div>
              <div />
            </div>
            <div className="divide-y divide-slate-800">
              {items.map((item) => (
                <div key={item.id} className="grid grid-cols-[1.4fr_0.9fr_0.8fr_1fr_0.9fr] gap-4 px-6 py-4 text-sm">
                  <div className="font-medium text-white">{item.email}</div>
                  <div className="text-slate-300">{dashboard(`roles.${item.role}` as never)}</div>
                  <div className={item.is_active ? "text-emerald-300" : "text-slate-500"}>
                    {item.is_active ? dashboard("active") : dashboard("inactive")}
                  </div>
                  <div className="text-slate-400">{formatDate(item.created_at, locale)}</div>
                  <div className="flex justify-end">
                    <button
                      type="button"
                      onClick={() => toggleUser(item.id, !item.is_active)}
                      disabled={busyId === item.id}
                      className="rounded-full border border-white/10 px-4 py-2 text-xs font-semibold text-slate-200 transition hover:border-white/20 hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {busyId === item.id
                        ? t("actions.updating")
                        : item.is_active
                          ? t("actions.deactivate")
                          : t("actions.activate")}
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
