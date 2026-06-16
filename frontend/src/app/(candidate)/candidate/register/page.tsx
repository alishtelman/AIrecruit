"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Link, useRouter } from "@/i18n/navigation";
import { authApi } from "@/lib/api";
import { getSafeRedirect } from "@/lib/safeRedirect";
import { AuthError, AuthPanel, authButtonClass, authInputClass, authLabelClass } from "@/components/auth-panel";

function RegisterPageInner() {
  const t = useTranslations("auth.register");
  const router = useRouter();
  const searchParams = useSearchParams();
  const redirect = getSafeRedirect(searchParams.get("redirect"), "/candidate/dashboard");
  const [form, setForm] = useState({ full_name: "", email: "", password: "" });

  useEffect(() => {
    authApi
      .me()
      .then(async (user) => {
        if (user.role === "candidate") {
          router.replace(redirect);
          return;
        }
        await authApi.logout().catch(() => null);
      })
      .catch(() => null);
  }, [router, redirect]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await authApi.register(form);
      // Auto-login after register
      await authApi.login({
        email: form.email,
        password: form.password,
        account_type: "candidate",
      });
      const user = await authApi.me();
      if (user.role !== "candidate") {
        await authApi.logout().catch(() => null);
        setError(t("failed"));
        return;
      }
      router.push(redirect);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("failed"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthPanel
      title={t("title")}
      subtitle={t("subtitle")}
      footer={
        <>
          {t("hasAccount")}{" "}
          <Link
            href={redirect !== "/candidate/dashboard" ? `/candidate/login?redirect=${encodeURIComponent(redirect)}` : "/candidate/login"}
            className="text-[#2F5BEA] hover:underline"
          >
            {t("signIn")}
          </Link>
        </>
      }
    >
        <form onSubmit={handleSubmit} className="space-y-5">
          {error && <AuthError>{error}</AuthError>}
          <div>
            <label className={authLabelClass}>{t("fullName")}</label>
            <input
              type="text"
              required
              value={form.full_name}
              onChange={(e) => setForm({ ...form, full_name: e.target.value })}
              placeholder={t("fullName")}
              className={authInputClass}
            />
          </div>
          <div>
            <label className={authLabelClass}>{t("email")}</label>
            <input
              type="email"
              required
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
              placeholder="name@example.com"
              className={authInputClass}
            />
          </div>
          <div>
            <label className={authLabelClass}>{t("password")}</label>
            <input
              type="password"
              required
              minLength={8}
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              placeholder={t("passwordHint")}
              className={authInputClass}
            />
          </div>
          <button
            type="submit"
            disabled={loading}
            className={authButtonClass}
          >
            {loading ? t("submitting") : t("submit")}
          </button>
        </form>
    </AuthPanel>
  );
}

export default function RegisterPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-[#F4F5F7]" />}>
      <RegisterPageInner />
    </Suspense>
  );
}
