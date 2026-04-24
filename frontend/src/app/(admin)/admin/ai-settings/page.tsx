"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { AdminWorkspaceHeader } from "@/components/admin-workspace-header";
import { useAuth } from "@/hooks/useAuth";
import { adminApi } from "@/lib/api";
import type { PlatformSettings } from "@/lib/types";

export default function AdminAISettingsPage() {
  const t = useTranslations("admin.aiSettings");
  const common = useTranslations("common");
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
      const payload = await adminApi.updateAISettings({
        proctoring_policy_mode: settings.proctoring_policy_mode as "observe_only" | "strict_flagging",
        interviewer_model_preference: settings.interviewer_model_preference,
        assessor_model_preference: settings.assessor_model_preference,
      });
      setSettings(payload);
      setNotice(t("saved"));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("errors.save"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="ai-shell min-h-screen">
      <div className="ai-section mx-auto max-w-5xl px-4 py-6 sm:px-6 lg:px-8">
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
            <div className="grid gap-5">
              <div>
                <label className="mb-2 block text-sm font-medium text-slate-300">{t("fields.policy")}</label>
                <select
                  className="ai-input min-h-12 w-full appearance-none rounded-2xl px-4 pr-12"
                  value={settings.proctoring_policy_mode}
                  onChange={(e) => setSettings({ ...settings, proctoring_policy_mode: e.target.value })}
                >
                  <option value="observe_only">{t("policyOptions.observe_only")}</option>
                  <option value="strict_flagging">{t("policyOptions.strict_flagging")}</option>
                </select>
                <p className="mt-2 text-sm text-slate-500">{t("hints.policy")}</p>
              </div>

              <div>
                <label className="mb-2 block text-sm font-medium text-slate-300">{t("fields.interviewerModel")}</label>
                <input
                  className="ai-input min-h-12 w-full rounded-2xl px-4"
                  value={settings.interviewer_model_preference ?? ""}
                  onChange={(e) => setSettings({ ...settings, interviewer_model_preference: e.target.value || null })}
                  placeholder="llama-3.1-8b-instant"
                />
                <p className="mt-2 text-sm text-slate-500">{t("hints.interviewerModel")}</p>
              </div>

              <div>
                <label className="mb-2 block text-sm font-medium text-slate-300">{t("fields.assessorModel")}</label>
                <input
                  className="ai-input min-h-12 w-full rounded-2xl px-4"
                  value={settings.assessor_model_preference ?? ""}
                  onChange={(e) => setSettings({ ...settings, assessor_model_preference: e.target.value || null })}
                  placeholder="llama-3.1-8b-instant"
                />
                <p className="mt-2 text-sm text-slate-500">{t("hints.assessorModel")}</p>
              </div>
            </div>

            <div className="mt-6 flex justify-end border-t border-slate-800 pt-5">
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
