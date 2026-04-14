"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Link, useRouter } from "@/i18n/navigation";
import { authApi } from "@/lib/api";
import { getDefaultRouteForRole } from "@/lib/roleRedirect";
import { getSafeRedirect } from "@/lib/safeRedirect";

function LoginPageInner() {
  const t = useTranslations("auth.login");
  const router = useRouter();
  const searchParams = useSearchParams();
  const redirect = getSafeRedirect(searchParams.get("redirect"), "/candidate/dashboard");
  const [form, setForm] = useState({ email: "", password: "" });

  useEffect(() => {
    authApi
      .me()
      .then((user) => router.replace(user.role === "candidate" ? redirect : getDefaultRouteForRole(user.role)))
      .catch(() => null);
  }, [router, redirect]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await authApi.login(form);
      const user = await authApi.me();
      router.push(user.role === "candidate" ? redirect : getDefaultRouteForRole(user.role));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("invalid"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-slate-900 flex items-center justify-center px-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-white">{t("title")}</h1>
          <p className="text-slate-400 mt-2">{t("subtitle")}</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5 rounded-2xl border border-[color:var(--color-border)] bg-[color:var(--color-surface-elevated)] p-8 shadow-[var(--shadow-panel)] backdrop-blur">
          {error && (
            <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg px-4 py-3">
              {error}
            </div>
          )}
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1.5">{t("email")}</label>
            <input
              type="email"
              required
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
              placeholder="name@example.com"
              className="w-full bg-slate-700 border border-slate-600 text-white rounded-lg px-4 py-2.5 focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder-slate-400"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1.5">{t("password")}</label>
            <input
              type="password"
              required
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              placeholder="••••••••"
              className="w-full bg-slate-700 border border-slate-600 text-white rounded-lg px-4 py-2.5 focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder-slate-400"
            />
          </div>
          <button
            type="submit"
            disabled={loading}
            className="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold py-2.5 rounded-lg transition-colors"
          >
            {loading ? t("submitting") : t("submit")}
          </button>
        </form>

        <p className="text-center text-slate-400 mt-6 text-sm">
          {t("noAccount")}{" "}
          <Link
            href={redirect !== "/candidate/dashboard" ? `/candidate/register?redirect=${encodeURIComponent(redirect)}` : "/candidate/register"}
            className="text-blue-400 hover:underline"
          >
            {t("register")}
          </Link>
        </p>
      </div>
    </div>
  );
}

import { Suspense } from "react";
export default function LoginPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-slate-900" />}>
      <LoginPageInner />
    </Suspense>
  );
}
