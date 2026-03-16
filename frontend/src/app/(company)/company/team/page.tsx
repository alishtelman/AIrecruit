"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/hooks/useAuth";
import { companyApi } from "@/lib/api";
import type { CompanyMember } from "@/lib/types";

export default function TeamPage() {
  const { user, loading: authLoading } = useAuth("/company/login");
  const [members, setMembers] = useState<CompanyMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [email, setEmail] = useState("");
  const [inviting, setInviting] = useState(false);
  const [inviteResult, setInviteResult] = useState<{ email: string; temp_password: string | null } | null>(null);
  const [formError, setFormError] = useState("");

  const isAdmin = user?.role === "company_admin";

  useEffect(() => {
    if (authLoading) return;
    companyApi
      .listMembers()
      .then(setMembers)
      .catch((e) => setError(e.message ?? "Failed to load team"))
      .finally(() => setLoading(false));
  }, [authLoading]);

  async function handleInvite(e: React.FormEvent) {
    e.preventDefault();
    setFormError("");
    setInviteResult(null);
    setInviting(true);
    try {
      const res = await companyApi.inviteMember(email);
      setMembers((prev) => [...prev, res.member]);
      setInviteResult({ email: res.member.email, temp_password: res.temp_password });
      setEmail("");
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : "Failed to invite");
    } finally {
      setInviting(false);
    }
  }

  async function handleRemove(userId: string) {
    try {
      await companyApi.removeMember(userId);
      setMembers((prev) => prev.filter((m) => m.user_id !== userId));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to remove member");
    }
  }

  if (authLoading || loading) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="text-slate-400">Loading…</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-900 px-4 py-8">
      <div className="max-w-2xl mx-auto">
        <div className="mb-8">
          <Link href="/company/dashboard" className="text-slate-400 hover:text-white text-sm transition-colors">
            ← Back to dashboard
          </Link>
          <h1 className="text-2xl font-bold text-white mt-3">Team</h1>
          <p className="text-slate-400 text-sm mt-1">
            {isAdmin ? "Manage who has access to your company account." : "Members of your company account."}
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
            <h2 className="text-white font-semibold mb-3">Invite Member</h2>
            {formError && (
              <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg px-4 py-3 mb-3">
                {formError}
              </div>
            )}
            {inviteResult && (
              <div className="bg-green-500/10 border border-green-500/30 text-green-400 text-sm rounded-lg px-4 py-3 mb-3">
                <div className="font-medium mb-1">✓ Invited {inviteResult.email}</div>
                {inviteResult.temp_password ? (
                  <div>
                    Temporary password:{" "}
                    <code className="bg-green-500/20 px-2 py-0.5 rounded font-mono">
                      {inviteResult.temp_password}
                    </code>
                    <span className="text-green-500/70 ml-2 text-xs">Share this once — it won't be shown again.</span>
                  </div>
                ) : (
                  <div>User already existed and has been added to your team.</div>
                )}
              </div>
            )}
            <div className="flex gap-3">
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="colleague@company.com"
                className="flex-1 bg-slate-700 border border-slate-600 text-white rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder-slate-400"
              />
              <button
                type="submit"
                disabled={inviting || !email.trim()}
                className="bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white font-semibold px-5 py-2.5 rounded-lg transition-colors text-sm"
              >
                {inviting ? "Inviting…" : "Invite"}
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
                      : "bg-slate-600/30 border-slate-600/50 text-slate-400"
                  }`}>
                    {m.role === "admin" ? "Admin" : "Member"}
                  </span>
                  <span className="text-slate-500 text-xs">
                    Joined {new Date(m.created_at).toLocaleDateString()}
                  </span>
                </div>
              </div>
              {isAdmin && m.role !== "admin" && m.user_id !== user?.id && (
                <button
                  onClick={() => handleRemove(m.user_id)}
                  className="text-slate-500 hover:text-red-400 text-sm transition-colors shrink-0"
                >
                  Remove
                </button>
              )}
            </div>
          ))}
          {members.length === 0 && (
            <div className="text-slate-500 text-sm text-center py-8">No team members yet.</div>
          )}
        </div>
      </div>
    </div>
  );
}
