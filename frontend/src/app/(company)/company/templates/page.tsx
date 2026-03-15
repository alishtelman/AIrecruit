"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/hooks/useAuth";
import { companyApi } from "@/lib/api";
import type { InterviewTemplate, TargetRole } from "@/lib/types";

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

const ROLE_LABELS: Record<string, string> = Object.fromEntries(
  ROLES.map((r) => [r.value, r.label])
);

const BLANK_FORM = {
  name: "",
  target_role: "backend_engineer" as TargetRole,
  description: "",
  questions: [""],
  is_public: false,
};

export default function TemplatesPage() {
  const { loading: authLoading } = useAuth("/company/login");
  const [templates, setTemplates] = useState<InterviewTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(BLANK_FORM);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");

  useEffect(() => {
    if (authLoading) return;
    companyApi
      .listTemplates()
      .then(setTemplates)
      .catch((err) => setError(err.message ?? "Failed to load templates"))
      .finally(() => setLoading(false));
  }, [authLoading]);

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
    setFormError("");
    const validQuestions = form.questions.map((q) => q.trim()).filter(Boolean);
    if (validQuestions.length === 0) {
      setFormError("Add at least one question.");
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
      setFormError(err instanceof Error ? err.message : "Failed to create template");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(templateId: string) {
    try {
      await companyApi.deleteTemplate(templateId);
      setTemplates(templates.filter((t) => t.template_id !== templateId));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to delete template");
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
            <h1 className="text-2xl font-bold text-white mt-3">Interview Templates</h1>
            <p className="text-slate-400 text-sm mt-1">Create custom question sets for candidates</p>
          </div>
          <button
            onClick={() => setShowForm(!showForm)}
            className="bg-blue-600 hover:bg-blue-500 text-white font-semibold px-4 py-2 rounded-lg transition-colors text-sm"
          >
            {showForm ? "Cancel" : "+ New Template"}
          </button>
        </div>

        {error && (
          <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg px-4 py-3 mb-6">
            {error}
          </div>
        )}

        {/* Create form */}
        {showForm && (
          <form
            onSubmit={handleCreate}
            className="bg-slate-800 border border-slate-700 rounded-xl p-6 mb-6 space-y-4"
          >
            <h2 className="text-white font-semibold">New Template</h2>
            {formError && (
              <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg px-4 py-3">
                {formError}
              </div>
            )}
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1.5">Name</label>
              <input
                required
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="e.g. Senior Backend Engineer Screen"
                className="w-full bg-slate-700 border border-slate-600 text-white rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder-slate-400"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1.5">Target Role</label>
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
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1.5">Description (optional)</label>
              <input
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                placeholder="Brief description for candidates"
                className="w-full bg-slate-700 border border-slate-600 text-white rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder-slate-400"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">Questions</label>
              <div className="space-y-2">
                {form.questions.map((q, idx) => (
                  <div key={idx} className="flex gap-2">
                    <input
                      value={q}
                      onChange={(e) => setQuestion(idx, e.target.value)}
                      placeholder={`Question ${idx + 1}`}
                      className="flex-1 bg-slate-700 border border-slate-600 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder-slate-400"
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
                + Add question
              </button>
            </div>
            <label className="flex items-center gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={form.is_public}
                onChange={(e) => setForm({ ...form, is_public: e.target.checked })}
                className="rounded"
              />
              <span className="text-sm text-slate-300">
                Make public (visible to all candidates on the interview start page)
              </span>
            </label>
            <button
              type="submit"
              disabled={saving}
              className="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white font-semibold py-2.5 rounded-lg transition-colors"
            >
              {saving ? "Creating…" : "Create Template"}
            </button>
          </form>
        )}

        {/* Template list */}
        {templates.length === 0 && !showForm ? (
          <div className="bg-slate-800 border border-slate-700 rounded-xl p-12 text-center">
            <div className="text-4xl mb-4">📋</div>
            <h2 className="text-white font-semibold text-lg mb-2">No templates yet</h2>
            <p className="text-slate-400 text-sm max-w-sm mx-auto">
              Create a template to define a custom set of interview questions for candidates.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {templates.map((tmpl) => (
              <div
                key={tmpl.template_id}
                className="bg-slate-800 border border-slate-700 rounded-xl p-5"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-white font-semibold">{tmpl.name}</span>
                      {tmpl.is_public && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-green-500/10 border border-green-500/20 text-green-400">
                          Public
                        </span>
                      )}
                    </div>
                    <p className="text-slate-400 text-sm mt-0.5">
                      {ROLE_LABELS[tmpl.target_role] ?? tmpl.target_role} · {tmpl.questions.length} questions
                    </p>
                    {tmpl.description && (
                      <p className="text-slate-500 text-xs mt-1">{tmpl.description}</p>
                    )}
                  </div>
                  <button
                    onClick={() => handleDelete(tmpl.template_id)}
                    className="text-slate-500 hover:text-red-400 text-sm transition-colors shrink-0"
                  >
                    Delete
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
