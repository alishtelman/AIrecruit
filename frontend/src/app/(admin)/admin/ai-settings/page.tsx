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

  const provider = settings?.llm_provider ?? "groq";
  const modelOptions = settings?.llm_model_options?.[provider] ?? [];

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
        llm_provider: settings.llm_provider,
        interviewer_model: settings.interviewer_model,
        assessor_model: settings.assessor_model,
        interviewer_prompt_override: settings.interviewer_prompt_override,
        assessor_prompt_override: settings.assessor_prompt_override,
        llm_timeout_seconds: settings.llm_timeout_seconds,
        llm_max_retries: settings.llm_max_retries,
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
            <div className="mb-6 grid gap-3 md:grid-cols-3">
              <StatusCard label="Active provider" value={settings.llm_provider} />
              <StatusCard label="Interviewer model" value={settings.interviewer_model} />
              <StatusCard label="Assessor model" value={settings.assessor_model} />
              <StatusCard
                label="Required API key"
                value={settings.llm_api_key_available ? `${settings.llm_required_api_key} available` : `${settings.llm_required_api_key ?? "API key"} missing`}
                tone={settings.llm_api_key_available ? "ok" : "warn"}
              />
              <StatusCard label="Mock AI" value={settings.mock_ai_enabled ? "Enabled" : "Disabled"} />
              <StatusCard label="TTS" value={`${settings.tts_provider ?? "disabled"} -> ${settings.tts_fallback_provider ?? "none"}`} />
            </div>
            {settings.llm_configuration_warning && (
              <div className="mb-6 rounded-2xl border border-amber-500/25 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
                {settings.llm_configuration_warning}
              </div>
            )}

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
                <label className="mb-2 block text-sm font-medium text-slate-300">LLM provider</label>
                <select
                  className="ai-input min-h-12 w-full appearance-none rounded-2xl px-4 pr-12"
                  value={settings.llm_provider}
                  onChange={(e) => {
                    const nextProvider = e.target.value;
                    const nextModels = settings.llm_model_options[nextProvider] ?? [];
                    const nextModel = nextModels[0] ?? "";
                    setSettings({
                      ...settings,
                      llm_provider: nextProvider,
                      interviewer_model: nextModel,
                      assessor_model: nextModel,
                    });
                  }}
                >
                  {Object.keys(settings.llm_model_options).map((option) => (
                    <option key={option} value={option}>{option}</option>
                  ))}
                </select>
                <p className="mt-2 text-sm text-slate-500">Provider is platform-wide and hidden from company users.</p>
              </div>

              <div>
                <label className="mb-2 block text-sm font-medium text-slate-300">{t("fields.interviewerModel")}</label>
                <select
                  className="ai-input min-h-12 w-full appearance-none rounded-2xl px-4 pr-12"
                  value={settings.interviewer_model}
                  onChange={(e) => setSettings({ ...settings, interviewer_model: e.target.value })}
                >
                  {modelOptions.map((option) => (
                    <option key={option} value={option}>{option}</option>
                  ))}
                </select>
                <p className="mt-2 text-sm text-slate-500">Model list is curated for the selected provider.</p>
              </div>

              <div>
                <label className="mb-2 block text-sm font-medium text-slate-300">{t("fields.assessorModel")}</label>
                <select
                  className="ai-input min-h-12 w-full appearance-none rounded-2xl px-4 pr-12"
                  value={settings.assessor_model}
                  onChange={(e) => setSettings({ ...settings, assessor_model: e.target.value })}
                >
                  {modelOptions.map((option) => (
                    <option key={option} value={option}>{option}</option>
                  ))}
                </select>
                <p className="mt-2 text-sm text-slate-500">No cross-provider fallback is used.</p>
              </div>

              <div className="grid gap-5 md:grid-cols-2">
                <div>
                  <label className="mb-2 block text-sm font-medium text-slate-300">Timeout seconds</label>
                  <input
                    type="number"
                    min={5}
                    max={120}
                    className="ai-input min-h-12 w-full rounded-2xl px-4"
                    value={settings.llm_timeout_seconds}
                    onChange={(e) => setSettings({ ...settings, llm_timeout_seconds: Number(e.target.value) })}
                  />
                </div>
                <div>
                  <label className="mb-2 block text-sm font-medium text-slate-300">Max retries</label>
                  <input
                    type="number"
                    min={0}
                    max={5}
                    className="ai-input min-h-12 w-full rounded-2xl px-4"
                    value={settings.llm_max_retries}
                    onChange={(e) => setSettings({ ...settings, llm_max_retries: Number(e.target.value) })}
                  />
                </div>
              </div>

              <div>
                <label className="mb-2 block text-sm font-medium text-slate-300">Interviewer prompt override</label>
                <textarea
                  className="ai-input min-h-36 w-full rounded-2xl px-4 py-3"
                  value={settings.interviewer_prompt_override ?? ""}
                  onChange={(e) => setSettings({ ...settings, interviewer_prompt_override: e.target.value || null })}
                  placeholder="Empty value uses the code default prompt."
                />
                <p className="mt-2 text-sm text-slate-500">Audit logs record only that the prompt changed, not the prompt body.</p>
              </div>

              <div>
                <label className="mb-2 block text-sm font-medium text-slate-300">Assessor prompt override</label>
                <textarea
                  className="ai-input min-h-36 w-full rounded-2xl px-4 py-3"
                  value={settings.assessor_prompt_override ?? ""}
                  onChange={(e) => setSettings({ ...settings, assessor_prompt_override: e.target.value || null })}
                  placeholder="Empty value uses the code default prompt."
                />
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

function StatusCard({ label, value, tone = "default" }: { label: string; value: string; tone?: "default" | "ok" | "warn" }) {
  const toneClass = tone === "ok" ? "text-emerald-300" : tone === "warn" ? "text-amber-300" : "text-white";
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-950/40 p-4">
      <div className="mb-1 text-xs uppercase tracking-[0.18em] text-slate-500">{label}</div>
      <div className={`break-words text-sm font-medium ${toneClass}`}>{value}</div>
    </div>
  );
}
