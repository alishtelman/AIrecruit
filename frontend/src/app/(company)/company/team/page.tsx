"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { CompanyWorkspaceHeader } from "@/components/company-workspace-header";
import { Link } from "@/i18n/navigation";
import { useAuth } from "@/hooks/useAuth";
import { companyApi } from "@/lib/api";
import type { CompanyMember } from "@/lib/types";

export default function TeamPage() {
  const t = useTranslations("companyTeam");
  const { user, loading: authLoading, logout } = useAuth({
    redirectTo: "/company/login",
    allowedRoles: ["company_admin", "company_member"],
    unauthorizedRedirectTo: "/candidate/dashboard",
  });
  const [members, setMembers] = useState<CompanyMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"recruiter" | "viewer">("recruiter");
  const [inviting, setInviting] = useState(false);
  const [inviteResult, setInviteResult] = useState<{ email: string; temp_password: string | null } | null>(null);
  const [formError, setFormError] = useState("");

  const companyRole = user?.company_member_role ?? (user?.role === "company_admin" ? "admin" : null);
  const isAdmin = companyRole === "admin";

  useEffect(() => {
    if (authLoading) return;
    companyApi
      .listMembers()
      .then(setMembers)
      .catch((e) => setError(e.message ?? t("errors.load")))
      .finally(() => setLoading(false));
  }, [authLoading, t]);

  async function handleInvite(e: React.FormEvent) {
    e.preventDefault();
    setFormError("");
    setInviteResult(null);
    setInviting(true);
    try {
      const res = await companyApi.inviteMemberWithRole(email, role);
      setMembers((prev) => [...prev, res.member]);
      setInviteResult({ email: res.member.email, temp_password: res.temp_password });
      setEmail("");
      setRole("recruiter");
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : t("errors.invite"));
    } finally {
      setInviting(false);
    }
  }

  async function handleRemove(userId: string) {
    try {
      await companyApi.removeMember(userId);
      setMembers((prev) => prev.filter((m) => m.user_id !== userId));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("errors.remove"));
    }
  }

  if (authLoading || loading) {
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

        <div className="mb-6 grid gap-4 xl:grid-cols-[1.55fr_1fr]">
          <section className="ai-panel-strong rounded-[2rem] p-7">
            <div className="ai-kicker mb-5">{t("kicker")}</div>
            <h1 className="mt-1 text-3xl font-semibold tracking-[-0.03em] text-white">{t("title")}</h1>
            <p className="mt-2 max-w-2xl text-slate-400">{isAdmin ? t("subtitleAdmin") : t("subtitleViewer")}</p>
          </section>

          <aside className="ai-panel rounded-[1.8rem] p-6">
            <h2 className="mb-4 text-sm font-semibold uppercase tracking-[0.18em] text-slate-300">{t("summary.title")}</h2>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
              <StatCard label={t("summary.members")} value={String(members.length)} />
              <StatCard label={t("summary.yourAccess")} value={t(`roles.${companyRole ?? "viewer"}`)} />
            </div>
          </aside>
        </div>

        {error && (
          <div className="mb-6 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">
            {error}
          </div>
        )}

        {isAdmin && (
          <form onSubmit={handleInvite} className="ai-panel rounded-[1.8rem] p-6 mb-6">
            <h2 className="mb-2 font-semibold text-white">{t("invite.title")}</h2>
            <p className="mb-4 text-sm text-slate-400">{t("invite.description")}</p>

            {formError && (
              <div className="mb-3 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">
                {formError}
              </div>
            )}

            {inviteResult && (
              <div className="mb-3 rounded-xl border border-green-500/30 bg-green-500/10 px-4 py-3 text-sm text-green-400">
                <div className="mb-1 font-medium">{t("invite.invited", { email: inviteResult.email })}</div>
                {inviteResult.temp_password ? (
                  <div>
                    {t("invite.tempPassword")}{" "}
                    <code className="rounded bg-green-500/20 px-2 py-0.5 font-mono">
                      {inviteResult.temp_password}
                    </code>
                    <span className="ml-2 text-xs text-green-500/70">{t("invite.shareOnce")}</span>
                  </div>
                ) : (
                  <div>{t("invite.existingUser")}</div>
                )}
              </div>
            )}

            <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_180px_auto]">
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder={t("invite.emailPlaceholder")}
                className="ai-input w-full rounded-xl px-4 py-3 text-sm placeholder:text-slate-500"
              />
              <div className="relative">
                <select
                  value={role}
                  onChange={(e) => setRole(e.target.value as "recruiter" | "viewer")}
                  className="ai-select w-full appearance-none rounded-xl px-4 py-3 pr-12 text-sm"
                >
                  <option value="recruiter">{t("roles.recruiter")}</option>
                  <option value="viewer">{t("roles.viewer")}</option>
                </select>
                <SelectChevron />
              </div>
              <button
                type="submit"
                disabled={inviting || !email.trim()}
                className="ai-button-primary rounded-xl px-5 py-3 text-sm font-semibold text-white disabled:opacity-40"
              >
                {inviting ? t("invite.submitting") : t("invite.submit")}
              </button>
            </div>
          </form>
        )}

        <section className="ai-panel rounded-[1.8rem] p-6">
          <div className="mb-4">
            <h2 className="font-semibold text-white">{t("members.title")}</h2>
            <p className="mt-1 text-sm text-slate-400">{t("members.subtitle")}</p>
          </div>

          <div className="space-y-3">
            {members.map((m) => (
              <div
                key={m.user_id}
                className="flex items-center justify-between gap-4 rounded-[1.4rem] border border-white/6 bg-slate-950/35 px-5 py-4"
              >
                <div>
                  <div className="text-sm font-medium text-white">{m.email}</div>
                  <div className="mt-1 flex items-center gap-2">
                    <span className={`rounded-full border px-2 py-0.5 text-xs ${
                      m.role === "admin"
                        ? "border-blue-500/20 bg-blue-500/10 text-blue-400"
                        : m.role === "recruiter"
                          ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-300"
                          : "border-slate-600/50 bg-slate-600/30 text-slate-300"
                    }`}>
                      {m.role === "admin" ? t("roles.admin") : m.role === "recruiter" ? t("roles.recruiter") : t("roles.viewer")}
                    </span>
                    <span className="text-xs text-slate-500">
                      {t("joined", { date: new Date(m.created_at).toLocaleDateString() })}
                    </span>
                  </div>
                </div>

                {isAdmin && m.role !== "admin" && m.user_id !== user?.id && (
                  <button
                    onClick={() => handleRemove(m.user_id)}
                    className="shrink-0 text-sm text-slate-500 transition-colors hover:text-red-400"
                  >
                    {t("remove")}
                  </button>
                )}
              </div>
            ))}

            {members.length === 0 && (
              <div className="rounded-[1.4rem] border border-dashed border-white/8 bg-slate-950/20 px-5 py-10 text-center text-sm text-slate-500">
                {t("empty")}
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[1.2rem] border border-white/6 bg-slate-950/35 px-4 py-4">
      <div className="mb-2 text-[11px] font-medium uppercase tracking-[0.18em] text-slate-500">{label}</div>
      <div className="text-lg font-semibold text-white">{value}</div>
    </div>
  );
}

function SelectChevron() {
  return (
    <span className="pointer-events-none absolute inset-y-0 right-4 flex items-center text-slate-400">
      <svg className="h-4 w-4" viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <path d="M6 8l4 4 4-4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </span>
  );
}
