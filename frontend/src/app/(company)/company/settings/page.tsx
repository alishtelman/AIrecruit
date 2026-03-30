"use client";

import { useState } from "react";
import { Link } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { useAuth } from "@/hooks/useAuth";
import { authApi } from "@/lib/api";

export default function CompanySettingsPage() {
  const t = useTranslations("companySettings");
  const { user, loading: authLoading } = useAuth("/company/login");
  const [form, setForm] = useState({ current_password: "", new_password: "", confirm: "" });
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(""); setSuccess(false);
    if (form.new_password !== form.confirm) { setError(t("errors.mismatch")); return; }
    if (form.new_password.length < 8) { setError(t("errors.minLength")); return; }
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

  if (authLoading) return <div className="min-h-screen bg-slate-900 flex items-center justify-center"><div className="text-slate-400">{t("loading")}</div></div>;

  return (
    <div className="min-h-screen bg-slate-900 px-4 py-8">
      <div className="max-w-md mx-auto">
        <Link href="/company/dashboard" className="text-slate-400 hover:text-white text-sm transition-colors">
          ← {t("back")}
        </Link>
        <h1 className="text-2xl font-bold text-white mt-3 mb-1">{t("title")}</h1>
        <p className="text-slate-400 text-sm mb-8">{user?.email}</p>

        <div className="bg-slate-800 border border-slate-700 rounded-xl p-6">
          <h2 className="text-white font-semibold mb-4">{t("changePassword")}</h2>
          {success && (
            <div className="bg-green-500/10 border border-green-500/30 text-green-400 text-sm rounded-lg px-4 py-3 mb-4">
              {t("success")}
            </div>
          )}
          {error && (
            <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg px-4 py-3 mb-4">
              {error}
            </div>
          )}
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1.5">{t("currentPassword")}</label>
              <input
                type="password" required value={form.current_password}
                onChange={(e) => setForm({ ...form, current_password: e.target.value })}
                className="w-full bg-slate-700 border border-slate-600 text-white rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1.5">{t("newPassword")}</label>
              <input
                type="password" required value={form.new_password}
                onChange={(e) => setForm({ ...form, new_password: e.target.value })}
                placeholder={t("minCharacters")}
                className="w-full bg-slate-700 border border-slate-600 text-white rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder-slate-400"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1.5">{t("confirmPassword")}</label>
              <input
                type="password" required value={form.confirm}
                onChange={(e) => setForm({ ...form, confirm: e.target.value })}
                className="w-full bg-slate-700 border border-slate-600 text-white rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <button
              type="submit" disabled={saving}
              className="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white font-semibold py-2.5 rounded-lg transition-colors"
            >
              {saving ? t("saving") : t("submit")}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
