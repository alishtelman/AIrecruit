"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Link, useRouter } from "@/i18n/navigation";
import { authApi, companyAuthApi } from "@/lib/api";
import { getDefaultRouteForRole } from "@/lib/roleRedirect";
import { AuthError, AuthPanel, authButtonClass, authInputClass, authLabelClass } from "@/components/auth-panel";

export default function CompanyRegisterPage() {
  const t = useTranslations("companyAuth.register");
  const router = useRouter();
  const [form, setForm] = useState({ email: "", password: "", company_name: "" });

  useEffect(() => {
    authApi.me().then((user) => router.replace(getDefaultRouteForRole(user.role))).catch(() => null);
  }, [router]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await companyAuthApi.register(form);
      await authApi.login({ email: form.email, password: form.password, account_type: "company" });
      const user = await authApi.me();
      router.push(getDefaultRouteForRole(user.role));
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
          <Link href="/company/login" className="text-[#2F5BEA] hover:underline">
            {t("signIn")}
          </Link>
        </>
      }
    >
        <form onSubmit={handleSubmit} className="space-y-5">
          {error && <AuthError>{error}</AuthError>}
          <div>
            <label className={authLabelClass}>{t("companyName")}</label>
            <input
              type="text"
              required
              value={form.company_name}
              onChange={(e) => setForm({ ...form, company_name: e.target.value })}
              placeholder={t("companyName")}
              className={authInputClass}
            />
          </div>
          <div>
            <label className={authLabelClass}>{t("workEmail")}</label>
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
