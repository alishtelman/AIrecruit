"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAuth } from "@/hooks/useAuth";
import { companyApi } from "@/lib/api";
import type { AssessmentType, CompanyAssessment, InterviewTemplate, TargetRole } from "@/lib/types";

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

const ROLE_LABELS: Record<string, string> = Object.fromEntries(ROLES.map((role) => [role.value, role.label]));
const ASSESSMENT_TYPE_LABELS: Record<AssessmentType, string> = {
  employee_internal: "Internal employee",
  candidate_external: "External candidate",
};
const STATUS_STYLES: Record<CompanyAssessment["status"], string> = {
  pending: "bg-amber-500/10 border-amber-500/30 text-amber-300",
  opened: "bg-cyan-500/10 border-cyan-500/30 text-cyan-300",
  in_progress: "bg-blue-500/10 border-blue-500/30 text-blue-300",
  completed: "bg-emerald-500/10 border-emerald-500/30 text-emerald-300",
  expired: "bg-rose-500/10 border-rose-500/30 text-rose-300",
};

type AssessmentFormState = {
  employee_email: string;
  employee_name: string;
  assessment_type: AssessmentType;
  target_role: TargetRole;
  template_id: string;
  deadline_at: string;
  expires_at: string;
  branding_name: string;
  branding_logo_url: string;
};

const BLANK_FORM: AssessmentFormState = {
  employee_email: "",
  employee_name: "",
  assessment_type: "employee_internal",
  target_role: "backend_engineer",
  template_id: "",
  deadline_at: "",
  expires_at: "",
  branding_name: "",
  branding_logo_url: "",
};

function formatDate(value: string | null): string {
  if (!value) return "Not set";
  return new Date(value).toLocaleString();
}

function statusLabel(status: CompanyAssessment["status"]): string {
  return status.replace("_", " ");
}

export default function EmployeesPage() {
  const { user, loading: authLoading } = useAuth("/company/login");
  const [assessments, setAssessments] = useState<CompanyAssessment[]>([]);
  const [templates, setTemplates] = useState<InterviewTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<AssessmentFormState>(BLANK_FORM);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");
  const [createdInvite, setCreatedInvite] = useState<{ label: string; link: string } | null>(null);
  const canManageCampaigns = (user?.company_member_role ?? (user?.role === "company_admin" ? "admin" : null)) === "admin";

  useEffect(() => {
    if (authLoading) return;
    setLoading(true);
    Promise.all([companyApi.listAssessments(), companyApi.listTemplates()])
      .then(([assessmentRows, templateRows]) => {
        setAssessments(assessmentRows);
        setTemplates(templateRows);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Failed to load campaigns"))
      .finally(() => setLoading(false));
  }, [authLoading]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!canManageCampaigns) {
      setFormError("Only admins can create campaigns");
      return;
    }
    setFormError("");
    setSaving(true);

    try {
      const created = await companyApi.createAssessment({
        employee_email: form.employee_email,
        employee_name: form.employee_name,
        assessment_type: form.assessment_type,
        target_role: form.target_role,
        template_id: form.template_id || null,
        deadline_at: form.deadline_at || null,
        expires_at: form.expires_at || null,
        branding_name: form.branding_name || null,
        branding_logo_url: form.branding_logo_url || null,
      });
      setAssessments([created, ...assessments]);
      setCreatedInvite({
        label: created.employee_name,
        link: `${window.location.origin}/employee/invite/${created.invite_token}`,
      });
      setShowForm(false);
      setForm(BLANK_FORM);
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : "Failed to create campaign");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string) {
    if (!canManageCampaigns) {
      setError("Only admins can delete campaigns");
      return;
    }
    try {
      await companyApi.deleteAssessment(id);
      setAssessments(assessments.filter((assessment) => assessment.id !== id));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to delete campaign");
    }
  }

  const pendingCount = assessments.filter((assessment) => assessment.status === "pending").length;
  const openedCount = assessments.filter((assessment) => assessment.status === "opened").length;
  const inProgressCount = assessments.filter((assessment) => assessment.status === "in_progress").length;
  const completedCount = assessments.filter((assessment) => assessment.status === "completed").length;
  const completionRate = assessments.length === 0 ? 0 : Math.round((completedCount / assessments.length) * 100);
  const selectedTemplate = templates.find((template) => template.template_id === form.template_id);

  if (authLoading || loading) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <div className="text-slate-400">Loading campaigns…</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950 px-4 py-8">
      <div className="mx-auto max-w-6xl space-y-8">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <Link href="/company/dashboard" className="text-sm text-slate-400 transition-colors hover:text-white">
              ← Back to dashboard
            </Link>
            <h1 className="mt-3 text-3xl font-semibold text-white">Assessment Campaigns</h1>
            <p className="mt-2 max-w-2xl text-sm text-slate-400">
              Run private AI assessment campaigns for employees or external candidates, attach a template, set a
              deadline, and track invite lifecycle through completion.
            </p>
            {!canManageCampaigns && (
              <p className="mt-2 text-sm text-amber-300">Read-only mode: only admins can create or delete campaigns.</p>
            )}
          </div>
          <button
            onClick={() => {
              setShowForm(!showForm);
              setCreatedInvite(null);
              setFormError("");
            }}
            disabled={!canManageCampaigns}
            className="rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-blue-500 disabled:opacity-50"
          >
            {showForm ? "Close form" : "New campaign"}
          </button>
        </div>

        <div className="grid gap-4 md:grid-cols-4">
          <SummaryCard label="Total campaigns" value={String(assessments.length)} accent="slate" />
          <SummaryCard label="Completed" value={String(completedCount)} accent="green" />
          <SummaryCard label="Opened / In progress" value={`${openedCount + inProgressCount}`} accent="blue" />
          <SummaryCard label="Completion rate" value={`${completionRate}%`} accent="amber" />
        </div>

        {error && (
          <div className="rounded-2xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
            {error}
          </div>
        )}

        {createdInvite && (
          <div className="rounded-3xl border border-emerald-500/30 bg-emerald-500/10 p-5">
            <div className="mb-2 text-sm font-semibold text-emerald-300">
              Campaign created for {createdInvite.label}
            </div>
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
              <code className="flex-1 overflow-hidden rounded-2xl bg-slate-900 px-3 py-2 text-xs text-slate-200">
                {createdInvite.link}
              </code>
              <div className="flex gap-2">
                <button
                  onClick={() => navigator.clipboard.writeText(createdInvite.link)}
                  className="rounded-xl bg-slate-800 px-3 py-2 text-xs font-medium text-slate-200 transition-colors hover:bg-slate-700"
                >
                  Copy link
                </button>
                <a
                  href={createdInvite.link}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded-xl bg-emerald-500/20 px-3 py-2 text-xs font-medium text-emerald-200 transition-colors hover:bg-emerald-500/30"
                >
                  Open invite
                </a>
              </div>
            </div>
          </div>
        )}

        {showForm && (
          <form onSubmit={handleCreate} className="grid gap-6 rounded-3xl border border-slate-800 bg-slate-900/80 p-6 lg:grid-cols-[1.3fr_0.9fr]">
            <div className="space-y-5">
              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <label className="mb-1.5 block text-sm text-slate-300">Invite type</label>
                  <select
                    value={form.assessment_type}
                    onChange={(e) => setForm({ ...form, assessment_type: e.target.value as AssessmentType })}
                    className="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-2.5 text-sm text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="employee_internal">Internal employee</option>
                    <option value="candidate_external">External candidate</option>
                  </select>
                </div>
                <div>
                  <label className="mb-1.5 block text-sm text-slate-300">Target role</label>
                  <select
                    value={form.target_role}
                    onChange={(e) => {
                      const nextRole = e.target.value as TargetRole;
                      const nextTemplateId =
                        selectedTemplate && selectedTemplate.target_role !== nextRole ? "" : form.template_id;
                      setForm({ ...form, target_role: nextRole, template_id: nextTemplateId });
                    }}
                    className="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-2.5 text-sm text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    {ROLES.map((role) => (
                      <option key={role.value} value={role.value}>
                        {role.label}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <Field
                  label={form.assessment_type === "employee_internal" ? "Employee name" : "Candidate name"}
                  value={form.employee_name}
                  onChange={(value) => setForm({ ...form, employee_name: value })}
                  placeholder={form.assessment_type === "employee_internal" ? "Aruzhan Sadykova" : "Maksim Petrov"}
                  required
                />
                <Field
                  label={form.assessment_type === "employee_internal" ? "Employee email" : "Candidate email"}
                  type="email"
                  value={form.employee_email}
                  onChange={(value) => setForm({ ...form, employee_email: value })}
                  placeholder="invitee@example.com"
                  required
                />
              </div>

              <div>
                <label className="mb-1.5 block text-sm text-slate-300">Optional template</label>
                <select
                  value={form.template_id}
                  onChange={(e) => {
                    const templateId = e.target.value;
                    const template = templates.find((item) => item.template_id === templateId);
                    setForm({
                      ...form,
                      template_id: templateId,
                      target_role: (template?.target_role as TargetRole | undefined) ?? form.target_role,
                    });
                  }}
                  className="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-2.5 text-sm text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">Default adaptive interview</option>
                  {templates
                    .filter((template) => template.target_role === form.target_role || template.template_id === form.template_id)
                    .map((template) => (
                      <option key={template.template_id} value={template.template_id}>
                        {template.name} · {ROLE_LABELS[template.target_role] ?? template.target_role}
                      </option>
                    ))}
                </select>
                {selectedTemplate && (
                  <p className="mt-2 text-xs text-slate-500">
                    Template questions: {selectedTemplate.questions.length}. Role is locked to{" "}
                    {ROLE_LABELS[selectedTemplate.target_role] ?? selectedTemplate.target_role}.
                  </p>
                )}
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <Field
                  label="Deadline"
                  type="datetime-local"
                  value={form.deadline_at}
                  onChange={(value) => setForm({ ...form, deadline_at: value })}
                />
                <Field
                  label="Expires at"
                  type="datetime-local"
                  value={form.expires_at}
                  onChange={(value) => setForm({ ...form, expires_at: value })}
                />
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <Field
                  label="Branding name"
                  value={form.branding_name}
                  onChange={(value) => setForm({ ...form, branding_name: value })}
                  placeholder="Engineering Hiring Sprint"
                />
                <Field
                  label="Branding logo URL"
                  value={form.branding_logo_url}
                  onChange={(value) => setForm({ ...form, branding_logo_url: value })}
                  placeholder="https://cdn.example.com/logo.png"
                />
              </div>

              {formError && (
                <div className="rounded-2xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
                  {formError}
                </div>
              )}

              <button
                type="submit"
                disabled={saving}
                className="w-full rounded-2xl bg-blue-600 py-3 text-sm font-semibold text-white transition-colors hover:bg-blue-500 disabled:opacity-50"
              >
                {saving ? "Creating campaign…" : "Create private campaign"}
              </button>
            </div>

            <div className="rounded-3xl border border-slate-800 bg-slate-950/80 p-5">
              <div className="text-sm font-semibold text-white">How this campaign behaves</div>
              <ul className="mt-4 space-y-3 text-sm text-slate-400">
                <li>The invite remains private and never appears in the public marketplace.</li>
                <li>`opened` means the landing page was viewed but the interview has not started yet.</li>
                <li>`deadline` and `expires_at` both block new starts once the timestamp is reached.</li>
                <li>Completed campaigns expose company-scoped report and replay links directly from this page.</li>
                <li>Branding only changes the invite experience; report visibility still stays company-scoped.</li>
              </ul>
            </div>
          </form>
        )}

        {assessments.length === 0 && !showForm ? (
          <div className="rounded-3xl border border-slate-800 bg-slate-900/80 p-16 text-center">
            <div className="text-5xl">🎯</div>
            <h2 className="mt-4 text-xl font-semibold text-white">No assessment campaigns yet</h2>
            <p className="mx-auto mt-2 max-w-lg text-sm text-slate-400">
              Create a private campaign for an employee or external candidate, optionally attach a custom template,
              and track invite lifecycle through completion.
            </p>
          </div>
        ) : (
          <div className="grid gap-4">
            {assessments.map((assessment) => {
              const invitePath = `/employee/invite/${assessment.invite_token}`;
              const canDelete = assessment.status !== "completed" && assessment.status !== "in_progress";
              return (
                <div key={assessment.id} className="rounded-3xl border border-slate-800 bg-slate-900/80 p-6">
                  <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <div className="text-lg font-semibold text-white">{assessment.employee_name}</div>
                        <span className="rounded-full border border-slate-700 px-2.5 py-1 text-xs text-slate-300">
                          {ASSESSMENT_TYPE_LABELS[assessment.assessment_type]}
                        </span>
                        <span className={`rounded-full border px-2.5 py-1 text-xs ${STATUS_STYLES[assessment.status]}`}>
                          {statusLabel(assessment.status)}
                        </span>
                      </div>
                      <div className="mt-1 text-sm text-slate-400">{assessment.employee_email}</div>
                      <div className="mt-4 grid gap-3 text-sm text-slate-400 md:grid-cols-2 xl:grid-cols-4">
                        <Meta label="Role" value={ROLE_LABELS[assessment.target_role] ?? assessment.target_role} />
                        <Meta label="Template" value={assessment.template_name ?? "Adaptive default"} />
                        <Meta label="Created" value={formatDate(assessment.created_at)} />
                        <Meta label="Brand" value={assessment.branding_name ?? "Company default"} />
                        <Meta label="Deadline" value={formatDate(assessment.deadline_at)} />
                        <Meta label="Expires" value={formatDate(assessment.expires_at)} />
                        <Meta label="Opened" value={formatDate(assessment.opened_at)} />
                        <Meta label="Completed" value={formatDate(assessment.completed_at)} />
                      </div>
                    </div>

                    <div className="flex flex-wrap gap-2 lg:max-w-sm lg:justify-end">
                      {(assessment.status === "pending" || assessment.status === "opened") && (
                        <>
                          <button
                            onClick={() => navigator.clipboard.writeText(`${window.location.origin}${invitePath}`)}
                            className="rounded-xl bg-slate-800 px-3 py-2 text-xs font-medium text-slate-200 transition-colors hover:bg-slate-700"
                          >
                            Copy link
                          </button>
                          <a
                            href={invitePath}
                            target="_blank"
                            rel="noreferrer"
                            className="rounded-xl bg-slate-800 px-3 py-2 text-xs font-medium text-slate-200 transition-colors hover:bg-slate-700"
                          >
                            Open invite
                          </a>
                        </>
                      )}
                      {assessment.status === "completed" && assessment.report_id && (
                        <Link
                          href={`/company/reports/${assessment.report_id}`}
                          className="rounded-xl bg-emerald-500/15 px-3 py-2 text-xs font-medium text-emerald-200 transition-colors hover:bg-emerald-500/25"
                        >
                          View report
                        </Link>
                      )}
                      {assessment.status === "completed" && assessment.interview_id && (
                        <Link
                          href={`/company/interviews/${assessment.interview_id}/replay`}
                          className="rounded-xl bg-blue-500/15 px-3 py-2 text-xs font-medium text-blue-200 transition-colors hover:bg-blue-500/25"
                        >
                          View replay
                        </Link>
                      )}
                      {canDelete && canManageCampaigns && (
                        <button
                          onClick={() => handleDelete(assessment.id)}
                          className="rounded-xl border border-rose-500/20 px-3 py-2 text-xs font-medium text-rose-300 transition-colors hover:bg-rose-500/10"
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

        {pendingCount > 0 && (
          <div className="rounded-2xl border border-amber-500/20 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
            {pendingCount} campaigns have not been opened yet. These are still good candidates for follow-up.
          </div>
        )}
      </div>
    </div>
  );
}

function SummaryCard({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent: "slate" | "green" | "blue" | "amber";
}) {
  const accentStyles = {
    slate: "border-slate-800 bg-slate-900/80 text-white",
    green: "border-emerald-500/20 bg-emerald-500/10 text-emerald-200",
    blue: "border-blue-500/20 bg-blue-500/10 text-blue-200",
    amber: "border-amber-500/20 bg-amber-500/10 text-amber-200",
  }[accent];

  return (
    <div className={`rounded-3xl border p-5 ${accentStyles}`}>
      <div className="text-xs uppercase tracking-[0.16em] text-slate-400">{label}</div>
      <div className="mt-3 text-3xl font-semibold">{value}</div>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
  required = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: string;
  required?: boolean;
}) {
  return (
    <div>
      <label className="mb-1.5 block text-sm text-slate-300">{label}</label>
      <input
        required={required}
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-2.5 text-sm text-white placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
    </div>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-[0.16em] text-slate-500">{label}</div>
      <div className="mt-1 text-sm text-slate-200">{value}</div>
    </div>
  );
}
