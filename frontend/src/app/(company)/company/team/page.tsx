"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { useAuth } from "@/hooks/useAuth";
import { companyApi } from "@/lib/api";
import type { CompanyMember } from "@/lib/types";

export default function TeamPage() {
  const t = useTranslations("companyTeam");
  const { user, loading: authLoading } = useAuth("/company/login");
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
  }, [authLoading]);

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
    <div className="min-h-screen bg-slate-900 px-4 py-8">
      <div className="max-w-2xl mx-auto">
        <div className="mb-8">
            <Link href="/company/dashboard" className="text-slate-400 hover:text-white text-sm transition-colors">
            ← {t("back")}
          </Link>
          <h1 className="text-2xl font-bold text-white mt-3">{t("title")}</h1>
          <p className="text-slate-400 text-sm mt-1">
            {isAdmin ? t("subtitleAdmin") : t("subtitleViewer")}
          </p>
        </div>

        {error && (
          <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg px-4 py-3 mb-6">
            {error}
          </div>
        )}

        {/* Invite form — admin only */}
        {isAdmin && (
          <form onSubmit={handleInvite} className="bg-slate-800 border border-slate-700 rounded-xl p-5 mb-6">
            <h2 className="text-white font-semibold mb-3">{t("invite.title")}</h2>
            {formError && (
              <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg px-4 py-3 mb-3">
                {formError}
              </div>
            )}
            {inviteResult && (
              <div className="bg-green-500/10 border border-green-500/30 text-green-400 text-sm rounded-lg px-4 py-3 mb-3">
                <div className="font-medium mb-1">{t("invite.invited", {email: inviteResult.email})}</div>
                {inviteResult.temp_password ? (
                  <div>
                    {t("invite.tempPassword")}{" "}
                    <code className="bg-green-500/20 px-2 py-0.5 rounded font-mono">
                      {inviteResult.temp_password}
                    </code>
                    <span className="text-green-500/70 ml-2 text-xs">{t("invite.shareOnce")}</span>
                  </div>
                ) : (
                  <div>{t("invite.existingUser")}</div>
                )}
              </div>
            )}
            <div className="flex gap-3">
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder={t("invite.emailPlaceholder")}
                className="flex-1 bg-slate-700 border border-slate-600 text-white rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder-slate-400"
              />
              <select
                value={role}
                onChange={(e) => setRole(e.target.value as "recruiter" | "viewer")}
                className="bg-slate-700 border border-slate-600 text-white rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="recruiter">{t("roles.recruiter")}</option>
                <option value="viewer">{t("roles.viewer")}</option>
              </select>
              <button
                type="submit"
                disabled={inviting || !email.trim()}
                className="bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white font-semibold px-5 py-2.5 rounded-lg transition-colors text-sm"
              >
                {inviting ? t("invite.submitting") : t("invite.submit")}
              </button>
            </div>
          </form>
        )}

        {/* Members list */}
        <div className="space-y-2">
          {members.map((m) => (
            <div
              key={m.user_id}
              className="bg-slate-800 border border-slate-700 rounded-xl px-5 py-4 flex items-center justify-between gap-4"
            >
              <div>
                <div className="text-white text-sm font-medium">{m.email}</div>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className={`text-xs px-2 py-0.5 rounded-full border ${
                    m.role === "admin"
                      ? "bg-blue-500/10 border-blue-500/20 text-blue-400"
                      : m.role === "recruiter"
                      ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-300"
                      : "bg-slate-600/30 border-slate-600/50 text-slate-300"
                  }`}>
                    {m.role === "admin" ? t("roles.admin") : m.role === "recruiter" ? t("roles.recruiter") : t("roles.viewer")}
                  </span>
                  <span className="text-slate-500 text-xs">
                    {t("joined", {date: new Date(m.created_at).toLocaleDateString()})}
                  </span>
                </div>
              </div>
              {isAdmin && m.role !== "admin" && m.user_id !== user?.id && (
                <button
                  onClick={() => handleRemove(m.user_id)}
                  className="text-slate-500 hover:text-red-400 text-sm transition-colors shrink-0"
                >
                  {t("remove")}
                </button>
              )}
            </div>
          ))}
          {members.length === 0 && (
            <div className="text-slate-500 text-sm text-center py-8">{t("empty")}</div>
          )}
        </div>
      </div>
    </div>
  );
}
