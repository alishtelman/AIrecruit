"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/hooks/useAuth";
import { companyApi } from "@/lib/api";
import type { CompanyAssessment, TargetRole } from "@/lib/types";

const ROLES: { value: TargetRole; label: string }[] = [
  { value: "backend_engineer", label: "Backend Engineer" },
  { value: "frontend_engineer", label: "Frontend Engineer" },
  { value: "qa_engineer", label: "QA Engineer" },
  { value: "devops_engineer", label: "DevOps Engineer" },
  { value: "data_scientist", label: "Data Scientist" },
  { value: "product_manager", label: "Product Manager" },
  { value: "mobile_engineer", label: "Mobile Engineer" },
  { value: "designer", label: "UX/UI Designer" },
];
const ROLE_LABELS: Record<string, string> = Object.fromEntries(ROLES.map((r) => [r.value, r.label]));

const STATUS_STYLES: Record<string, string> = {
  pending: "bg-yellow-500/10 border-yellow-500/20 text-yellow-400",
  in_progress: "bg-blue-500/10 border-blue-500/20 text-blue-400",
  completed: "bg-green-500/10 border-green-500/20 text-green-400",
};

const BLANK = { employee_email: "", employee_name: "", target_role: "backend_engineer" as TargetRole };
const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";

export default function EmployeesPage() {
  const { loading: authLoading } = useAuth("/company/login");
  const [assessments, setAssessments] = useState<CompanyAssessment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(BLANK);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");
  const [createdInvite, setCreatedInvite] = useState<{ name: string; link: string } | null>(null);

  useEffect(() => {
    if (authLoading) return;
    companyApi
      .listAssessments()
      .then(setAssessments)
      .catch((e) => setError(e.message ?? "Failed to load"))
      .finally(() => setLoading(false));
  }, [authLoading]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setFormError("");
    setSaving(true);
    try {
      const created = await companyApi.createAssessment(form);
      setAssessments([created, ...assessments]);
      const link = `${window.location.origin}/employee/invite/${created.invite_token}`;
      setCreatedInvite({ name: created.employee_name, link });
      setShowForm(false);
      setForm(BLANK);
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : "Failed to create");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string) {
    try {
      await companyApi.deleteAssessment(id);
      setAssessments(assessments.filter((a) => a.id !== id));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to delete");
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
      <div className="max-w-3xl mx-auto">
        <div className="flex items-center justify-between mb-8">
          <div>
            <Link href="/company/dashboard" className="text-slate-400 hover:text-white text-sm transition-colors">
              ← Back to dashboard
            </Link>
            <h1 className="text-2xl font-bold text-white mt-3">Employee Assessments</h1>
            <p className="text-slate-400 text-sm mt-1">
              Send AI interview invites to employees for performance review or skill audit.
            </p>
          </div>
          <button
            onClick={() => { setShowForm(!showForm); setCreatedInvite(null); }}
            className="bg-blue-600 hover:bg-blue-500 text-white font-semibold px-4 py-2 rounded-lg transition-colors text-sm"
          >
            {showForm ? "Cancel" : "+ New Assessment"}
          </button>
        </div>

        {error && (
          <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg px-4 py-3 mb-6">
            {error}
          </div>
        )}

        {/* Invite link after creation */}
        {createdInvite && (
          <div className="bg-green-500/10 border border-green-500/30 rounded-xl p-5 mb-6">
            <div className="text-green-400 font-semibold mb-2">
              ✓ Assessment created for {createdInvite.name}
            </div>
            <div className="text-slate-300 text-sm mb-2">Share this link with the employee:</div>
            <div className="flex items-center gap-2">
              <code className="flex-1 bg-slate-800 rounded-lg px-3 py-2 text-xs text-slate-300 break-all">
                {createdInvite.link}
              </code>
              <button
                onClick={() => navigator.clipboard.writeText(createdInvite.link)}
                className="bg-slate-700 hover:bg-slate-600 text-slate-300 text-xs px-3 py-2 rounded-lg transition-colors shrink-0"
              >
                Copy
              </button>
            </div>
          </div>
        )}

        {/* Create form */}
        {showForm && (
          <form onSubmit={handleCreate} className="bg-slate-800 border border-slate-700 rounded-xl p-6 mb-6 space-y-4">
            <h2 className="text-white font-semibold">New Employee Assessment</h2>
            {formError && (
              <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg px-4 py-3">
                {formError}
              </div>
            )}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-1.5">Employee Name</label>
                <input
                  required
                  value={form.employee_name}
                  onChange={(e) => setForm({ ...form, employee_name: e.target.value })}
                  placeholder="Ivan Ivanov"
                  className="w-full bg-slate-700 border border-slate-600 text-white rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder-slate-400"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-1.5">Employee Email</label>
                <input
                  type="email"
                  required
                  value={form.employee_email}
                  onChange={(e) => setForm({ ...form, employee_email: e.target.value })}
                  placeholder="ivan@company.com"
                  className="w-full bg-slate-700 border border-slate-600 text-white rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder-slate-400"
                />
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1.5">Role to Assess</label>
              <select
                value={form.target_role}
                onChange={(e) => setForm({ ...form, target_role: e.target.value as TargetRole })}
                className="w-full bg-slate-700 border border-slate-600 text-white rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                {ROLES.map((r) => (
                  <option key={r.value} value={r.value}>{r.label}</option>
                ))}
              </select>
            </div>
            <button
              type="submit"
              disabled={saving}
              className="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white font-semibold py-2.5 rounded-lg transition-colors"
            >
              {saving ? "Creating…" : "Create & Get Invite Link"}
            </button>
          </form>
        )}

        {/* Assessment list */}
        {assessments.length === 0 && !showForm ? (
          <div className="bg-slate-800 border border-slate-700 rounded-xl p-12 text-center">
            <div className="text-4xl mb-4">👥</div>
            <h2 className="text-white font-semibold text-lg mb-2">No assessments yet</h2>
            <p className="text-slate-400 text-sm max-w-sm mx-auto">
              Create an assessment to send an AI interview invite to an employee.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {assessments.map((a) => {
              const inviteLink = `${window.location.origin}/employee/invite/${a.invite_token}`;
              return (
                <div key={a.id} className="bg-slate-800 border border-slate-700 rounded-xl p-5">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-white font-semibold">{a.employee_name}</span>
                        <span className="text-slate-400 text-sm">{a.employee_email}</span>
                        <span className={`text-xs px-2 py-0.5 rounded-full border ${STATUS_STYLES[a.status]}`}>
                          {a.status.replace("_", " ")}
                        </span>
                      </div>
                      <p className="text-slate-400 text-sm mt-0.5">
                        {ROLE_LABELS[a.target_role] ?? a.target_role} · {new Date(a.created_at).toLocaleDateString()}
                      </p>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      {a.status === "completed" && a.report_id ? (
                        <Link
                          href={`/company/reports/${a.report_id}`}
                          className="text-xs bg-green-500/10 border border-green-500/20 text-green-400 hover:bg-green-500/20 px-3 py-1.5 rounded-lg transition-colors"
                        >
                          View Report
                        </Link>
                      ) : a.status === "pending" ? (
                        <button
                          onClick={() => navigator.clipboard.writeText(inviteLink)}
                          className="text-xs bg-slate-700 hover:bg-slate-600 text-slate-300 px-3 py-1.5 rounded-lg transition-colors"
                        >
                          Copy Link
                        </button>
                      ) : null}
                      {a.status === "pending" && (
                        <button
                          onClick={() => handleDelete(a.id)}
                          className="text-slate-500 hover:text-red-400 text-sm transition-colors"
                        >
                          Delete
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
