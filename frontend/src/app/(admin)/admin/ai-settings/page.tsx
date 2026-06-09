"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { AdminWorkspaceHeader } from "@/components/admin-workspace-header";
import { useAuth } from "@/hooks/useAuth";
import { adminApi } from "@/lib/api";
import type { AdminLLMDiagnostics, AdminLLMPing, PlatformSettings } from "@/lib/types";

function formatDateTime(value: string | null | undefined, locale: string) {
  if (!value) return "—";
  return new Intl.DateTimeFormat(locale, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
}

export default function AdminAISettingsPage() {
  const t = useTranslations("admin.aiSettings");
  const common = useTranslations("common");
  const locale = useLocale();
  const { loading: authLoading, logout } = useAuth({
    redirectTo: "/admin/login",
    allowedRoles: ["platform_admin"],
  });
  const [settings, setSettings] = useState<PlatformSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [diagnostics, setDiagnostics] = useState<AdminLLMDiagnostics | null>(null);
  const [lastPing, setLastPing] = useState<AdminLLMPing | null>(null);

  const provider = settings?.llm_provider ?? "openai";
  const modelOptions = settings?.llm_model_options?.[provider] ?? [];

  useEffect(() => {
    if (authLoading) return;
    setLoading(true);
    setError("");
    Promise.all([adminApi.getPlatformSettings(), adminApi.getLLMDiagnostics()])
      .then(([settingsPayload, diagnosticsPayload]) => {
        setSettings(settingsPayload);
        setDiagnostics(diagnosticsPayload);
      })
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
      setDiagnostics(await adminApi.getLLMDiagnostics());
      setNotice(t("saved"));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("errors.save"));
    } finally {
      setSaving(false);
    }
  }

  async function testLLM() {
    setTesting(true);
    setError("");
    setNotice("");
    try {
      const payload = await adminApi.testLLM();
      setLastPing(payload);
      setDiagnostics(await adminApi.getLLMDiagnostics());
      setNotice(payload.ok ? t("diagnostics.testOk") : t("diagnostics.testFailed"));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("diagnostics.testFailed"));
    } finally {
      setTesting(false);
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
              <StatusCard label="TTS" value={`${settings.tts_provider ?? "disabled"} -> ${settings.tts_fallback_provider ?? "none"}`} />
            </div>

            <div className="mb-6 rounded-[1.5rem] border border-slate-800 bg-slate-950/35 p-5">
              <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                <div>
                  <h2 className="text-lg font-semibold text-white">{t("diagnostics.title")}</h2>
                  <p className="mt-1 text-sm leading-6 text-slate-400">{t("diagnostics.description")}</p>
                </div>
                <button
                  type="button"
                  onClick={testLLM}
                  disabled={testing}
                  className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-5 py-3 text-sm font-semibold text-emerald-200 transition hover:border-emerald-400/50 hover:text-white disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {testing ? t("diagnostics.testing") : t("diagnostics.test")}
                </button>
              </div>

              <div className="mt-5 grid gap-3 md:grid-cols-4">
                <StatusCard
                  label={t("diagnostics.configured")}
                  value={diagnostics?.configured ? t("diagnostics.ok") : t("diagnostics.needsAttention")}
                  tone={diagnostics?.configured ? "ok" : "warn"}
                />
                <StatusCard
                  label={t("diagnostics.runtime")}
                  value={`${diagnostics?.runtime_provider ?? "—"} / ${diagnostics?.runtime_model ?? "—"}`}
                />
                <StatusCard
                  label={t("diagnostics.timeout")}
                  value={`${diagnostics?.timeout_seconds ?? settings.llm_timeout_seconds}s · ${diagnostics?.max_retries ?? settings.llm_max_retries} retries`}
                />
                <StatusCard
                  label={t("diagnostics.checkedAt")}
                  value={formatDateTime(diagnostics?.checked_at, locale)}
                />
              </div>

              {(diagnostics?.last_success || diagnostics?.last_error || lastPing) && (
                <div className="mt-5 grid gap-3 lg:grid-cols-3">
                  <DiagnosticEvent
                    label={t("diagnostics.lastSuccess")}
                    value={diagnostics?.last_success?.at ? `${diagnostics.last_success.component ?? "ai"} · ${diagnostics.last_success.model ?? "model"} · ${formatDateTime(diagnostics.last_success.at, locale)}` : "—"}
                    tone="ok"
                  />
                  <DiagnosticEvent
                    label={t("diagnostics.lastError")}
                    value={diagnostics?.last_error?.error ? `${diagnostics.last_error.component ?? "ai"} · ${diagnostics.last_error.error}` : "—"}
                    tone={diagnostics?.last_error?.error ? "warn" : "default"}
                  />
                  <DiagnosticEvent
                    label={t("diagnostics.lastPing")}
                    value={lastPing ? `${lastPing.status} · ${lastPing.latency_ms ?? "—"}ms · ${lastPing.response_preview ?? lastPing.error ?? "—"}` : "—"}
                    tone={lastPing?.ok ? "ok" : lastPing ? "warn" : "default"}
                  />
                </div>
              )}
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
                <div className="ai-input flex min-h-12 w-full items-center rounded-2xl px-4 text-slate-200">
                  {settings.llm_provider}
                </div>
                <p className="mt-2 text-sm text-slate-500">OpenAI is the only supported LLM provider.</p>
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
                <p className="mt-2 text-sm text-slate-500">Only live OpenAI calls are used.</p>
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

function DiagnosticEvent({ label, value, tone = "default" }: { label: string; value: string; tone?: "default" | "ok" | "warn" }) {
  const toneClass = tone === "ok" ? "border-emerald-500/20 bg-emerald-500/5 text-emerald-100" : tone === "warn" ? "border-amber-500/20 bg-amber-500/5 text-amber-100" : "border-slate-800 bg-slate-950/40 text-slate-300";
  return (
    <div className={`rounded-2xl border p-4 ${toneClass}`}>
      <div className="mb-2 text-xs uppercase tracking-[0.18em] text-slate-500">{label}</div>
      <div className="line-clamp-3 break-words text-sm">{value}</div>
    </div>
  );
}
