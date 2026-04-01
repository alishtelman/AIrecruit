"use client";

import { CompanyWorkspaceHeader } from "@/components/company-workspace-header";
import { Link } from "@/i18n/navigation";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useAuth } from "@/hooks/useAuth";
import { companyApi } from "@/lib/api";
import type { AssessmentType, CompanyAssessment, InterviewTemplate, TargetRole } from "@/lib/types";

const ROLES: TargetRole[] = [
  "backend_engineer",
  "frontend_engineer",
  "qa_engineer",
  "devops_engineer",
  "data_scientist",
  "product_manager",
  "mobile_engineer",
  "designer",
];
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

export default function EmployeesPage() {
  const t = useTranslations("companyEmployees");
  const roleT = useTranslations("interviewStart.roles");
  const { user, loading: authLoading, logout } = useAuth({
    redirectTo: "/company/login",
    allowedRoles: ["company_admin", "company_member"],
    unauthorizedRedirectTo: "/candidate/dashboard",
  });
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
      .catch((e: unknown) => setError(e instanceof Error ? e.message : t("errors.load")))
      .finally(() => setLoading(false));
  }, [authLoading, t]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!canManageCampaigns) {
      setFormError(t("errors.adminOnlyCreate"));
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
      setFormError(err instanceof Error ? err.message : t("errors.create"));
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string) {
    if (!canManageCampaigns) {
      setError(t("errors.adminOnlyDelete"));
      return;
    }
    try {
      await companyApi.deleteAssessment(id);
      setAssessments(assessments.filter((assessment) => assessment.id !== id));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("errors.delete"));
    }
  }

  const pendingCount = assessments.filter((assessment) => assessment.status === "pending").length;
  const openedCount = assessments.filter((assessment) => assessment.status === "opened").length;
  const inProgressCount = assessments.filter((assessment) => assessment.status === "in_progress").length;
  const completedCount = assessments.filter((assessment) => assessment.status === "completed").length;
  const completionRate = assessments.length === 0 ? 0 : Math.round((completedCount / assessments.length) * 100);
  const selectedTemplate = templates.find((template) => template.template_id === form.template_id);
  const formatDate = (value: string | null): string => {
    if (!value) return t("meta.notSet");
    return new Date(value).toLocaleString();
  };
  const statusLabel = (status: CompanyAssessment["status"]): string => t(`status.${status}`);

  if (authLoading || loading) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <div className="text-slate-400">{t("loading")}</div>
      </div>
    );
  }

  return (
    <div className="ai-shell min-h-screen px-4 py-10">
      <div className="ai-section mx-auto max-w-6xl space-y-8">
        <CompanyWorkspaceHeader onLogout={logout} />
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
          <Link href="/company/dashboard" className="text-sm text-slate-400 transition-colors hover:text-white">
              ← {t("back")}
          </Link>
        </div>

        <div className="grid gap-4 xl:grid-cols-[1.55fr_1fr]">
          <section className="ai-panel-strong rounded-[2rem] p-7">
            <div className="ai-kicker mb-5">{t("title")}</div>
            <h1 className="text-3xl font-semibold tracking-[-0.03em] text-white">{t("title")}</h1>
            <p className="mt-2 max-w-2xl text-sm text-slate-400">{t("subtitle")}</p>
            {!canManageCampaigns && <p className="mt-3 text-sm text-amber-300">{t("readonly")}</p>}
          </section>
          <aside className="ai-panel rounded-[1.8rem] p-6">
            <button
              onClick={() => {
                setShowForm(!showForm);
                setCreatedInvite(null);
                setFormError("");
              }}
              disabled={!canManageCampaigns}
              className="ai-button-primary w-full rounded-xl px-4 py-2.5 text-sm font-semibold text-white transition-colors disabled:opacity-50"
            >
              {showForm ? t("closeForm") : t("new")}
            </button>
          </aside>
        </div>

        <div className="grid gap-4 md:grid-cols-4">
          <SummaryCard label={t("summary.total")} value={String(assessments.length)} accent="slate" />
          <SummaryCard label={t("summary.completed")} value={String(completedCount)} accent="green" />
          <SummaryCard label={t("summary.openedInProgress")} value={`${openedCount + inProgressCount}`} accent="blue" />
          <SummaryCard label={t("summary.completionRate")} value={`${completionRate}%`} accent="amber" />
        </div>

        {error && (
          <div className="rounded-2xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
            {error}
          </div>
        )}

        {createdInvite && (
          <div className="rounded-3xl border border-emerald-500/30 bg-emerald-500/10 p-5">
            <div className="mb-2 text-sm font-semibold text-emerald-300">
              {t("invite.createdFor", { label: createdInvite.label })}
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
                  {t("invite.copy")}
                </button>
                <a
                  href={createdInvite.link}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded-xl bg-emerald-500/20 px-3 py-2 text-xs font-medium text-emerald-200 transition-colors hover:bg-emerald-500/30"
                >
                  {t("invite.open")}
                </a>
              </div>
            </div>
          </div>
        )}

        {showForm && (
          <form onSubmit={handleCreate} className="grid gap-6 rounded-[1.8rem] border border-white/6 bg-slate-900/70 p-6 lg:grid-cols-[1.3fr_0.9fr]">
            <div className="space-y-5">
              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <label className="mb-1.5 block text-sm text-slate-300">{t("form.inviteType")}</label>
                  <SelectField value={form.assessment_type} onChange={(e) => setForm({ ...form, assessment_type: e.target.value as AssessmentType })}>
                    <option value="employee_internal">{t("labels.employeeInternal")}</option>
                    <option value="candidate_external">{t("labels.candidateExternal")}</option>
                  </SelectField>
                </div>
                <div>
                  <label className="mb-1.5 block text-sm text-slate-300">{t("form.targetRole")}</label>
                  <SelectField
                    value={form.target_role}
                    onChange={(e) => {
                      const nextRole = e.target.value as TargetRole;
                      const nextTemplateId =
                        selectedTemplate && selectedTemplate.target_role !== nextRole ? "" : form.template_id;
                      setForm({ ...form, target_role: nextRole, template_id: nextTemplateId });
                    }}
                  >
                    {ROLES.map((role) => (
                      <option key={role} value={role}>
                        {roleT(role)}
                      </option>
                    ))}
                  </SelectField>
                </div>
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <Field
                  label={form.assessment_type === "employee_internal" ? t("form.employeeName") : t("form.candidateName")}
                  value={form.employee_name}
                  onChange={(value) => setForm({ ...form, employee_name: value })}
                  placeholder={form.assessment_type === "employee_internal" ? "Aruzhan Sadykova" : "Maksim Petrov"}
                  required
                />
                <Field
                  label={form.assessment_type === "employee_internal" ? t("form.employeeEmail") : t("form.candidateEmail")}
                  type="email"
                  value={form.employee_email}
                  onChange={(value) => setForm({ ...form, employee_email: value })}
                  placeholder="invitee@example.com"
                  required
                />
              </div>

              <div>
                <label className="mb-1.5 block text-sm text-slate-300">{t("form.optionalTemplate")}</label>
                <SelectField
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
                >
                  <option value="">{t("form.defaultAdaptive")}</option>
                  {templates
                    .filter((template) => template.target_role === form.target_role || template.template_id === form.template_id)
                    .map((template) => (
                      <option key={template.template_id} value={template.template_id}>
                        {template.name} · {roleT(template.target_role)}
                      </option>
                    ))}
                </SelectField>
                {selectedTemplate && (
                  <p className="mt-2 text-xs text-slate-500">
                    {t("form.templateLocked", {
                      count: selectedTemplate.questions.length,
                      role: roleT(selectedTemplate.target_role),
                    })}
                  </p>
                )}
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <Field
                  label={t("form.deadline")}
                  type="datetime-local"
                  value={form.deadline_at}
                  onChange={(value) => setForm({ ...form, deadline_at: value })}
                />
                <Field
                  label={t("form.expiresAt")}
                  type="datetime-local"
                  value={form.expires_at}
                  onChange={(value) => setForm({ ...form, expires_at: value })}
                />
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <Field
                  label={t("form.brandingName")}
                  value={form.branding_name}
                  onChange={(value) => setForm({ ...form, branding_name: value })}
                  placeholder="Engineering Hiring Sprint"
                />
                <Field
                  label={t("form.brandingLogoUrl")}
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
                className="ai-button-primary w-full rounded-2xl py-3 text-sm font-semibold text-white disabled:opacity-50"
              >
                {saving ? t("form.creating") : t("form.submit")}
              </button>
            </div>

            <div className="rounded-[1.6rem] border border-white/6 bg-slate-950/60 p-5">
              <div className="text-sm font-semibold text-white">{t("guide.title")}</div>
              <ul className="mt-4 space-y-3 text-sm text-slate-400">
                <li>{t("guide.private")}</li>
                <li>{t("guide.opened")}</li>
                <li>{t("guide.deadline")}</li>
                <li>{t("guide.completed")}</li>
                <li>{t("guide.branding")}</li>
              </ul>
            </div>
          </form>
        )}

        {assessments.length === 0 && !showForm ? (
          <div className="ai-panel rounded-[1.8rem] p-16 text-center">
            <h2 className="mt-4 text-xl font-semibold text-white">{t("empty.title")}</h2>
            <p className="mx-auto mt-2 max-w-lg text-sm text-slate-400">
              {t("empty.description")}
            </p>
          </div>
        ) : (
          <div className="grid gap-4">
            {assessments.map((assessment) => {
              const invitePath = `/employee/invite/${assessment.invite_token}`;
              const canDelete = assessment.status !== "completed" && assessment.status !== "in_progress";
              return (
                <div key={assessment.id} className="ai-panel rounded-[1.8rem] p-6">
                  <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <div className="text-lg font-semibold text-white">{assessment.employee_name}</div>
                        <span className="rounded-full border border-slate-700 px-2.5 py-1 text-xs text-slate-300">
                          {assessment.assessment_type === "employee_internal" ? t("labels.employeeInternal") : t("labels.candidateExternal")}
                        </span>
                        <span className={`rounded-full border px-2.5 py-1 text-xs ${STATUS_STYLES[assessment.status]}`}>
                          {statusLabel(assessment.status)}
                        </span>
                      </div>
                      <div className="mt-1 text-sm text-slate-400">{assessment.employee_email}</div>
                      <div className="mt-4 grid gap-3 text-sm text-slate-400 md:grid-cols-2 xl:grid-cols-4">
                        <Meta label={t("meta.role")} value={roleT(assessment.target_role)} />
                        <Meta label={t("meta.template")} value={assessment.template_name ?? t("meta.adaptiveDefault")} />
                        <Meta label={t("meta.created")} value={formatDate(assessment.created_at)} />
                        <Meta label={t("meta.brand")} value={assessment.branding_name ?? t("meta.companyDefault")} />
                        <Meta label={t("meta.deadline")} value={formatDate(assessment.deadline_at)} />
                        <Meta label={t("meta.expires")} value={formatDate(assessment.expires_at)} />
                        <Meta label={t("meta.opened")} value={formatDate(assessment.opened_at)} />
                        <Meta label={t("meta.completed")} value={formatDate(assessment.completed_at)} />
                      </div>
                    </div>

                    <div className="flex flex-wrap gap-2 lg:max-w-sm lg:justify-end">
                      {(assessment.status === "pending" || assessment.status === "opened") && (
                        <>
                          <button
                            onClick={() => navigator.clipboard.writeText(`${window.location.origin}${invitePath}`)}
                          className="rounded-xl bg-slate-800 px-3 py-2 text-xs font-medium text-slate-200 transition-colors hover:bg-slate-700"
                        >
                            {t("invite.copy")}
                          </button>
                          <a
                            href={invitePath}
                            target="_blank"
                            rel="noreferrer"
                          className="rounded-xl bg-slate-800 px-3 py-2 text-xs font-medium text-slate-200 transition-colors hover:bg-slate-700"
                        >
                            {t("invite.open")}
                          </a>
                        </>
                      )}
                      {assessment.status === "completed" && assessment.report_id && (
                        <Link
                          href={`/company/reports/${assessment.report_id}`}
                          className="rounded-xl bg-emerald-500/15 px-3 py-2 text-xs font-medium text-emerald-200 transition-colors hover:bg-emerald-500/25"
                        >
                          {t("actions.viewReport")}
                        </Link>
                      )}
                      {assessment.status === "completed" && assessment.interview_id && (
                        <Link
                          href={`/company/interviews/${assessment.interview_id}/replay`}
                          className="rounded-xl bg-blue-500/15 px-3 py-2 text-xs font-medium text-blue-200 transition-colors hover:bg-blue-500/25"
                        >
                          {t("actions.viewReplay")}
                        </Link>
                      )}
                      {canDelete && canManageCampaigns && (
                        <button
                          onClick={() => handleDelete(assessment.id)}
                          className="rounded-xl border border-rose-500/20 px-3 py-2 text-xs font-medium text-rose-300 transition-colors hover:bg-rose-500/10"
                        >
                          {t("actions.delete")}
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
            {t("pendingNotice", { count: pendingCount })}
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
        className="ai-input w-full rounded-xl px-4 py-2.5 text-sm placeholder:text-slate-500"
      />
    </div>
  );
}

function SelectField({
  value,
  onChange,
  children,
}: {
  value: string;
  onChange: React.ChangeEventHandler<HTMLSelectElement>;
  children: React.ReactNode;
}) {
  return (
    <div className="relative">
      <select
        value={value}
        onChange={onChange}
        className="ai-select w-full appearance-none rounded-xl px-4 py-2.5 pr-12 text-sm"
      >
        {children}
      </select>
      <span className="pointer-events-none absolute inset-y-0 right-4 flex items-center text-slate-400">
        <svg className="h-4 w-4" viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <path d="M6 8l4 4 4-4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
    </div>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-sm text-slate-300">{value}</div>
    </div>
  );
}
