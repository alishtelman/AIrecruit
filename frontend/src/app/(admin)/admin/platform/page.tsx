"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { AdminWorkspaceHeader } from "@/components/admin-workspace-header";
import { useAuth } from "@/hooks/useAuth";
import { adminApi } from "@/lib/api";
import type { PlatformSettings } from "@/lib/types";

type BooleanSettingKey =
  | "candidate_registration_enabled"
  | "company_registration_enabled"
  | "employee_invites_enabled"
  | "maintenance_mode_enabled";

function formatDate(value: string, locale: string) {
  return new Intl.DateTimeFormat(locale, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export default function AdminPlatformPage() {
  const t = useTranslations("admin.platform");
  const common = useTranslations("common");
  const locale = useLocale();
  const { loading: authLoading, logout } = useAuth({
    redirectTo: "/admin/login",
    allowedRoles: ["platform_admin"],
  });
  const [settings, setSettings] = useState<PlatformSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    if (authLoading) return;
    setLoading(true);
    setError("");
    adminApi
      .getPlatformSettings()
      .then(setSettings)
      .catch((err) => setError(err instanceof Error ? err.message : t("errors.load")))
      .finally(() => setLoading(false));
  }, [authLoading, t]);

  async function save() {
    if (!settings) return;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const payload = await adminApi.updatePlatformSettings({
        candidate_registration_enabled: settings.candidate_registration_enabled,
        company_registration_enabled: settings.company_registration_enabled,
        employee_invites_enabled: settings.employee_invites_enabled,
        maintenance_mode_enabled: settings.maintenance_mode_enabled,
      });
      setSettings(payload);
      setNotice(t("saved"));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("errors.save"));
    } finally {
      setSaving(false);
    }
  }

  function toggle(key: BooleanSettingKey) {
    setSettings((prev) => (prev ? { ...prev, [key]: !prev[key] } : prev));
  }

  return (
    <div className="ai-shell min-h-screen">
      <div className="ai-section mx-auto max-w-6xl px-4 py-6 sm:px-6 lg:px-8">
        <AdminWorkspaceHeader onLogout={logout} />

        <section className="ai-panel-strong rounded-[2rem] p-7 sm:p-8">
          <span className="ai-kicker">{t("title")}</span>
          <p className="mt-4 max-w-3xl text-lg leading-8 text-slate-300">{t("description")}</p>
        </section>

        {error && <div className="mt-6 rounded-2xl border border-red-500/25 bg-red-500/10 px-5 py-4 text-sm text-red-300">{error}</div>}
        {notice && <div className="mt-6 rounded-2xl border border-emerald-500/25 bg-emerald-500/10 px-5 py-4 text-sm text-emerald-300">{notice}</div>}

        {loading && <div className="mt-6 rounded-2xl border border-slate-700 bg-slate-900/60 px-5 py-8 text-center text-slate-400">{t("loading")}</div>}

        {!loading && settings && (
          <section className="ai-panel mt-6 rounded-[1.75rem] p-6">
            <div className="grid gap-4 md:grid-cols-2">
              {[
                ["candidate_registration_enabled", "candidateRegistration"],
                ["company_registration_enabled", "companyRegistration"],
                ["employee_invites_enabled", "employeeInvites"],
                ["maintenance_mode_enabled", "maintenanceMode"],
              ].map(([key, suffix]) => (
                <div key={key} className="rounded-3xl border border-slate-700 bg-slate-900/70 p-5">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <p className="text-base font-semibold text-white">{t(`fields.${suffix}.title`)}</p>
                      <p className="mt-2 text-sm leading-6 text-slate-400">{t(`fields.${suffix}.help`)}</p>
                    </div>
                    <button
                      type="button"
                      onClick={() => toggle(key as BooleanSettingKey)}
                      className={`rounded-full px-4 py-2 text-sm font-semibold transition ${
                        settings[key as BooleanSettingKey]
                          ? "bg-blue-500 text-white shadow-[0_0_24px_rgba(59,130,246,0.28)]"
                          : "bg-slate-800 text-slate-300"
                      }`}
                    >
                      {settings[key as BooleanSettingKey] ? "ON" : "OFF"}
                    </button>
                  </div>
                </div>
              ))}
            </div>

            <div className="mt-6 flex flex-col gap-3 border-t border-slate-800 pt-5 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-sm text-slate-500">
                {t("meta.updatedAt")}: {formatDate(settings.updated_at, locale)}
              </p>
              <button
                type="button"
                onClick={save}
                disabled={saving}
                className="ai-button-primary rounded-full px-5 py-3 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-60"
              >
                {saving ? common("actions.saving") : t("save")}
              </button>
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
