"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Link, useRouter } from "@/i18n/navigation";
import { authApi } from "@/lib/api";
import { isAccountTypeMismatchError } from "@/lib/authErrors";
import { getDefaultRouteForRole } from "@/lib/roleRedirect";
import { AuthError, AuthPanel, authButtonClass, authInputClass, authLabelClass } from "@/components/auth-panel";

export default function CompanyLoginPage() {
  const t = useTranslations("companyAuth.login");
  const router = useRouter();
  const [form, setForm] = useState({ email: "", password: "" });

  useEffect(() => {
    authApi
      .me()
      .then((user) => router.replace(getDefaultRouteForRole(user.role)))
      .catch(() => null);
  }, [router]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await authApi.login({ ...form, account_type: "company" });
      const user = await authApi.me();
      if (user.role !== "company_admin" && user.role !== "company_member") {
        setError(t("roleMismatch"));
        await authApi.logout().catch(() => null);
        return;
      }
      router.push(getDefaultRouteForRole(user.role));
    } catch (err: unknown) {
      setError(isAccountTypeMismatchError(err) ? t("roleMismatch") : t("failed"));
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
          <Link href="/company/register" className="text-[#2F5BEA] hover:underline">
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
              placeholder="team@company.com"
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
