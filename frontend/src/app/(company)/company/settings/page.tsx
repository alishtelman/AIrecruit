"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { CompanyWorkspaceHeader } from "@/components/company-workspace-header";
import { Link } from "@/i18n/navigation";
import { useAuth } from "@/hooks/useAuth";
import { authApi } from "@/lib/api";

export default function CompanySettingsPage() {
  const t = useTranslations("companySettings");
  const { user, loading: authLoading, logout } = useAuth({
    redirectTo: "/company/login",
    allowedRoles: ["company_admin", "company_member"],
    unauthorizedRedirectTo: "/candidate/dashboard",
  });
  const [form, setForm] = useState({ current_password: "", new_password: "", confirm: "" });
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setSuccess(false);
    if (form.new_password !== form.confirm) {
      setError(t("errors.mismatch"));
      return;
    }
    if (form.new_password.length < 8) {
      setError(t("errors.minLength"));
      return;
    }
    setSaving(true);
    try {
      await authApi.changePassword({ current_password: form.current_password, new_password: form.new_password });
      setSuccess(true);
      setForm({ current_password: "", new_password: "", confirm: "" });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t("errors.failed"));
    } finally {
      setSaving(false);
    }
  }

  const companyRole = user?.company_member_role ?? (user?.role === "company_admin" ? "admin" : "viewer");

  if (authLoading) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="text-slate-400">{t("loading")}</div>
      </div>
    );
  }

  return (
    <div className="ai-shell min-h-screen px-4 py-10">
      <div className="ai-section mx-auto max-w-5xl">
        <CompanyWorkspaceHeader onLogout={logout} />
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
          <Link href="/company/dashboard" className="text-sm text-slate-400 transition-colors hover:text-white">
            ← {t("back")}
          </Link>
        </div>

        <div className="mb-6 grid gap-4 xl:grid-cols-[1.65fr_0.95fr]">
          <section className="ai-panel-strong rounded-[2rem] p-7">
            <div className="ai-kicker mb-5">{t("kicker")}</div>
            <h1 className="mb-2 text-3xl font-semibold tracking-[-0.03em] text-white">{t("title")}</h1>
            <p className="max-w-2xl text-slate-400">{t("subtitle")}</p>
          </section>

          <aside className="ai-panel rounded-[1.8rem] p-6">
            <h2 className="mb-4 text-sm font-semibold uppercase tracking-[0.18em] text-slate-300">{t("accountCardTitle")}</h2>
            <div className="space-y-4 text-sm">
              <div>
                <div className="mb-1 text-slate-500">{t("email")}</div>
                <div className="break-all text-white">{user?.email}</div>
              </div>
              <div>
                <div className="mb-1 text-slate-500">{t("access")}</div>
                <span className="inline-flex rounded-full border border-blue-500/20 bg-blue-500/10 px-2.5 py-1 text-xs font-medium text-blue-300">
                  {t(`roles.${companyRole}`)}
                </span>
              </div>
            </div>
          </aside>
        </div>

        <div className="grid gap-6 xl:grid-cols-[1.3fr_0.9fr]">
          <section className="ai-panel rounded-[1.8rem] p-6">
            <h2 className="mb-2 font-semibold text-white">{t("changePassword")}</h2>
            <p className="mb-5 text-sm text-slate-400">{t("passwordHint")}</p>

            {success && (
              <div className="mb-4 rounded-xl border border-green-500/30 bg-green-500/10 px-4 py-3 text-sm text-green-400">
                {t("success")}
              </div>
            )}
            {error && (
              <div className="mb-4 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">
                {error}
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="mb-1.5 block text-sm font-medium text-slate-300">{t("currentPassword")}</label>
                <input
                  type="password"
                  required
                  value={form.current_password}
                  onChange={(e) => setForm({ ...form, current_password: e.target.value })}
                  className="ai-input w-full rounded-xl px-4 py-3 text-sm"
                />
              </div>
              <div>
                <label className="mb-1.5 block text-sm font-medium text-slate-300">{t("newPassword")}</label>
                <input
                  type="password"
                  required
                  value={form.new_password}
                  onChange={(e) => setForm({ ...form, new_password: e.target.value })}
                  placeholder={t("minCharacters")}
                  className="ai-input w-full rounded-xl px-4 py-3 text-sm placeholder:text-slate-500"
                />
              </div>
              <div>
                <label className="mb-1.5 block text-sm font-medium text-slate-300">{t("confirmPassword")}</label>
                <input
                  type="password"
                  required
                  value={form.confirm}
                  onChange={(e) => setForm({ ...form, confirm: e.target.value })}
                  className="ai-input w-full rounded-xl px-4 py-3 text-sm"
                />
              </div>
              <button
                type="submit"
                disabled={saving}
                className="ai-button-primary w-full rounded-xl py-3 text-sm font-semibold text-white disabled:opacity-40"
              >
                {saving ? t("saving") : t("submit")}
              </button>
            </form>
          </section>

          <aside className="space-y-4">
            <section className="ai-panel rounded-[1.8rem] p-6">
              <h2 className="mb-2 font-semibold text-white">{t("securityCardTitle")}</h2>
              <p className="text-sm leading-6 text-slate-400">{t("securityCardBody")}</p>
            </section>
            <section className="ai-panel rounded-[1.8rem] p-6">
              <h2 className="mb-2 font-semibold text-white">{t("sessionCardTitle")}</h2>
              <p className="text-sm leading-6 text-slate-400">{t("sessionCardBody")}</p>
            </section>
          </aside>
        </div>
      </div>
    </div>
  );
}
