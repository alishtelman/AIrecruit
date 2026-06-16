"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Link, useRouter } from "@/i18n/navigation";
import { authApi } from "@/lib/api";
import { isAccountTypeMismatchError } from "@/lib/authErrors";
import { getDefaultRouteForRole } from "@/lib/roleRedirect";
import { getSafeRedirect } from "@/lib/safeRedirect";
import { AuthError, AuthPanel, authButtonClass, authInputClass, authLabelClass } from "@/components/auth-panel";

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
      await authApi.login({ ...form, account_type: "candidate" });
      const user = await authApi.me();
      if (user.role !== "candidate") {
        setError(t("roleMismatch"));
        await authApi.logout().catch(() => null);
        return;
      }
      router.push(redirect);
    } catch (err: unknown) {
      setError(isAccountTypeMismatchError(err) ? t("roleMismatch") : t("invalid"));
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
          {t("noAccount")}{" "}
          <Link
            href={redirect !== "/candidate/dashboard" ? `/candidate/register?redirect=${encodeURIComponent(redirect)}` : "/candidate/register"}
            className="text-[#2F5BEA] hover:underline"
          >
            {t("register")}
          </Link>
        </>
      }
    >
        <form onSubmit={handleSubmit} className="space-y-5">
          {error && <AuthError>{error}</AuthError>}
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
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              placeholder="••••••••"
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

import { Suspense } from "react";
export default function LoginPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-[#F4F5F7]" />}>
      <LoginPageInner />
    </Suspense>
  );
}
