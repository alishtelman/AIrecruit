"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Link, useRouter } from "@/i18n/navigation";
import { authApi } from "@/lib/api";
import { getDefaultRouteForRole } from "@/lib/roleRedirect";

export default function AdminLoginPage() {
  const t = useTranslations("admin.login");
  const router = useRouter();
  const [form, setForm] = useState({ email: "", password: "" });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    authApi.me().then((user) => router.replace(getDefaultRouteForRole(user.role))).catch(() => null);
  }, [router]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await authApi.login(form);
      const user = await authApi.me();
      router.push(getDefaultRouteForRole(user.role));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("failed"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="ai-shell min-h-screen px-4 py-10">
      <div className="mx-auto flex min-h-[80vh] w-full max-w-5xl items-center justify-center">
        <div className="grid w-full gap-8 lg:grid-cols-[1.1fr_0.9fr]">
          <section className="ai-panel-strong rounded-[2rem] p-8 lg:p-10">
            <span className="ai-kicker">{t("badge")}</span>
            <h1 className="mt-6 text-4xl font-semibold leading-tight text-white lg:text-5xl">
              {t("title")}
            </h1>
            <p className="mt-4 max-w-xl text-lg leading-8 text-slate-300">
              {t("description")}
            </p>
            <div className="mt-8 grid gap-4 sm:grid-cols-2">
              <div className="ai-stat rounded-3xl p-5">
                <p className="text-sm uppercase tracking-[0.22em] text-slate-500">{t("feature1Title")}</p>
                <p className="mt-3 text-sm leading-7 text-slate-300">{t("feature1Body")}</p>
              </div>
              <div className="ai-stat rounded-3xl p-5">
                <p className="text-sm uppercase tracking-[0.22em] text-slate-500">{t("feature2Title")}</p>
                <p className="mt-3 text-sm leading-7 text-slate-300">{t("feature2Body")}</p>
              </div>
            </div>
          </section>

          <section className="ai-panel rounded-[2rem] p-8">
            <div className="mb-8">
              <p className="text-2xl font-semibold text-white">{t("formTitle")}</p>
              <p className="mt-2 text-sm leading-6 text-slate-400">{t("formSubtitle")}</p>
            </div>
            <form onSubmit={handleSubmit} className="space-y-5">
              {error && (
                <div className="rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
                  {error}
                </div>
              )}
              <div>
                <label className="mb-1.5 block text-sm font-medium text-slate-300">{t("email")}</label>
                <input
                  type="email"
                  required
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                  placeholder="admin@airecruit.dev"
                  className="ai-input w-full rounded-2xl px-4 py-3"
                />
              </div>
              <div>
                <label className="mb-1.5 block text-sm font-medium text-slate-300">{t("password")}</label>
                <input
                  type="password"
                  required
                  value={form.password}
                  onChange={(e) => setForm({ ...form, password: e.target.value })}
                  placeholder="••••••••"
                  className="ai-input w-full rounded-2xl px-4 py-3"
                />
              </div>
              <button
                type="submit"
                disabled={loading}
                className="ai-button-primary w-full rounded-2xl px-5 py-3 text-base font-semibold disabled:cursor-not-allowed disabled:opacity-60"
              >
                {loading ? t("submitting") : t("submit")}
              </button>
            </form>
            <p className="mt-6 text-sm text-slate-500">
              {t("note")}{" "}
              <Link href="/" className="text-blue-300 transition-colors hover:text-blue-200">
                {t("backHome")}
              </Link>
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}
