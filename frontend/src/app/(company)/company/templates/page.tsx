"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { CompanyWorkspaceHeader } from "@/components/company-workspace-header";
import { Link } from "@/i18n/navigation";
import { useAuth } from "@/hooks/useAuth";
import { companyApi } from "@/lib/api";
import type { InterviewTemplate, TargetRole } from "@/lib/types";

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

const BLANK_FORM = {
  name: "",
  target_role: "backend_engineer" as TargetRole,
  description: "",
  questions: [""],
  is_public: false,
};

export default function TemplatesPage() {
  const t = useTranslations("companyTemplates");
  const startT = useTranslations("interviewStart");
  const { user, loading: authLoading, logout } = useAuth({
    redirectTo: "/company/login",
    allowedRoles: ["company_admin", "company_member"],
    unauthorizedRedirectTo: "/candidate/dashboard",
  });
  const [templates, setTemplates] = useState<InterviewTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(BLANK_FORM);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");
  const canManageTemplates = (user?.company_member_role ?? (user?.role === "company_admin" ? "admin" : null)) === "admin";

  useEffect(() => {
    if (authLoading) return;
    companyApi
      .listTemplates()
      .then(setTemplates)
      .catch((err) => setError(err.message ?? t("errors.load")))
      .finally(() => setLoading(false));
  }, [authLoading, t]);

  function setQuestion(idx: number, val: string) {
    const qs = [...form.questions];
    qs[idx] = val;
    setForm({ ...form, questions: qs });
  }

  function addQuestion() {
    setForm({ ...form, questions: [...form.questions, ""] });
  }

  function removeQuestion(idx: number) {
    if (form.questions.length <= 1) return;
    setForm({ ...form, questions: form.questions.filter((_, i) => i !== idx) });
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!canManageTemplates) {
      setFormError(t("errors.adminOnly"));
      return;
    }
    setFormError("");
    const validQuestions = form.questions.map((q) => q.trim()).filter(Boolean);
    if (validQuestions.length === 0) {
      setFormError(t("errors.noQuestions"));
      return;
    }
    setSaving(true);
    try {
      const created = await companyApi.createTemplate({
        name: form.name,
        target_role: form.target_role,
        description: form.description || null,
        questions: validQuestions,
        is_public: form.is_public,
      });
      setTemplates([created, ...templates]);
      setShowForm(false);
      setForm(BLANK_FORM);
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : t("errors.create"));
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(templateId: string) {
    if (!canManageTemplates) {
      setError(t("errors.adminOnly"));
      return;
    }
    try {
      await companyApi.deleteTemplate(templateId);
      setTemplates(templates.filter((t) => t.template_id !== templateId));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("errors.delete"));
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
      <div className="ai-section max-w-5xl mx-auto">
        <CompanyWorkspaceHeader onLogout={logout} />
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
          <Link href="/company/dashboard" className="text-slate-400 hover:text-white text-sm transition-colors">
              ← {t("back")}
          </Link>
        </div>

        <div className="mb-6 grid gap-4 xl:grid-cols-[1.55fr_1fr]">
          <section className="ai-panel-strong rounded-[2rem] p-7">
            <div className="ai-kicker mb-5">{t("title")}</div>
            <h1 className="text-3xl font-semibold tracking-[-0.03em] text-white">{t("title")}</h1>
            <p className="mt-2 max-w-2xl text-slate-400">{t("subtitle")}</p>
            {!canManageTemplates && <p className="mt-3 text-sm text-amber-300">{t("readonly")}</p>}
          </section>

          <aside className="ai-panel rounded-[1.8rem] p-6">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-[0.18em] text-slate-300">{t("new")}</h2>
            <p className="mb-4 text-sm text-slate-400">{t("empty.description")}</p>
          <button
            onClick={() => setShowForm(!showForm)}
            disabled={!canManageTemplates}
            className="ai-button-primary w-full rounded-xl px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
          >
            {showForm ? t("cancel") : t("new")}
          </button>
          </aside>
        </div>

        {error && (
          <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg px-4 py-3 mb-6">
            {error}
          </div>
        )}

        {/* Create form */}
        {showForm && (
          <form onSubmit={handleCreate} className="ai-panel rounded-[1.8rem] p-6 mb-6 space-y-4">
            <h2 className="text-white font-semibold">{t("form.title")}</h2>
            {formError && (
              <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg px-4 py-3">
                {formError}
              </div>
            )}
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1.5">{t("form.name")}</label>
              <input
                required
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder={t("form.namePlaceholder")}
                className="ai-input w-full rounded-xl px-4 py-2.5 text-sm placeholder:text-slate-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1.5">{t("form.targetRole")}</label>
              <SelectField value={form.target_role} onChange={(e) => setForm({ ...form, target_role: e.target.value as TargetRole })}>
                {ROLES.map((r) => (
                  <option key={r} value={r}>{startT(`roles.${r}`)}</option>
                ))}
              </SelectField>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1.5">{t("form.description")}</label>
              <input
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                placeholder={t("form.descriptionPlaceholder")}
                className="ai-input w-full rounded-xl px-4 py-2.5 text-sm placeholder:text-slate-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">{t("form.questions")}</label>
              <div className="space-y-2">
                {form.questions.map((q, idx) => (
                  <div key={idx} className="flex gap-2">
                    <input
                      value={q}
                      onChange={(e) => setQuestion(idx, e.target.value)}
                      placeholder={t("form.questionPlaceholder", {number: idx + 1})}
                      className="ai-input flex-1 rounded-xl px-4 py-2.5 text-sm placeholder:text-slate-500"
                    />
                    <button
                      type="button"
                      onClick={() => removeQuestion(idx)}
                      disabled={form.questions.length <= 1}
                      className="text-slate-500 hover:text-red-400 disabled:opacity-30 transition-colors px-2"
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
              <button
                type="button"
                onClick={addQuestion}
                className="mt-2 text-blue-400 hover:text-blue-300 text-sm transition-colors"
              >
                {t("form.addQuestion")}
              </button>
            </div>
            <label className="flex items-center gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={form.is_public}
                onChange={(e) => setForm({ ...form, is_public: e.target.checked })}
                className="rounded border-white/10 bg-slate-950/30"
              />
              <span className="text-sm text-slate-300">
                {t("form.makePublic")}
              </span>
            </label>
            <button
              type="submit"
              disabled={saving}
              className="ai-button-primary w-full rounded-xl py-2.5 text-white font-semibold disabled:opacity-40"
            >
              {saving ? t("form.creating") : t("form.submit")}
            </button>
          </form>
        )}

        {/* Template list */}
        {templates.length === 0 && !showForm ? (
          <div className="ai-panel rounded-[1.8rem] p-12 text-center">
            <h2 className="text-white font-semibold text-lg mb-2">{t("empty.title")}</h2>
            <p className="text-slate-400 text-sm max-w-sm mx-auto">
              {t("empty.description")}
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {templates.map((tmpl) => (
              <div
                key={tmpl.template_id}
                className="ai-panel rounded-[1.8rem] p-5"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-white font-semibold">{tmpl.name}</span>
                      {tmpl.is_public && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-green-500/10 border border-green-500/20 text-green-400">
                          {t("public")}
                        </span>
                      )}
                    </div>
                    <p className="text-slate-400 text-sm mt-0.5">
                      {startT(`roles.${tmpl.target_role}.label`)} · {t("questionCount", {count: tmpl.questions.length})}
                    </p>
                    {tmpl.description && (
                      <p className="text-slate-500 text-xs mt-1">{tmpl.description}</p>
                    )}
                  </div>
                  <button
                    onClick={() => handleDelete(tmpl.template_id)}
                    disabled={!canManageTemplates}
                    className="text-slate-500 hover:text-red-400 text-sm transition-colors shrink-0"
                  >
                    {t("delete")}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
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
