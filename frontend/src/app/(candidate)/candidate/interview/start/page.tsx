"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import { interviewApi, templateApi } from "@/lib/api";
import type { InterviewTemplate, TargetRole } from "@/lib/types";

const ROLES: { value: TargetRole; label: string; desc: string }[] = [
  { value: "backend_engineer",  label: "Backend Engineer",  desc: "System design, databases, APIs, performance" },
  { value: "frontend_engineer", label: "Frontend Engineer", desc: "UI, performance, frameworks, accessibility" },
  { value: "qa_engineer",       label: "QA Engineer",       desc: "Test strategy, automation, quality processes" },
  { value: "devops_engineer",   label: "DevOps Engineer",   desc: "CI/CD, infrastructure, Kubernetes, monitoring" },
  { value: "data_scientist",    label: "Data Scientist",    desc: "ML models, experiments, analytics, production AI" },
  { value: "product_manager",   label: "Product Manager",   desc: "Roadmap, stakeholders, metrics, delivery" },
  { value: "mobile_engineer",   label: "Mobile Engineer",   desc: "iOS, Android, React Native, Flutter" },
  { value: "designer",          label: "UX/UI Designer",    desc: "User research, prototyping, design systems" },
];

const ROLE_LABELS: Record<string, string> = Object.fromEntries(ROLES.map((r) => [r.value, r.label]));

// Inner component that reads searchParams
function StartInterviewInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { loading: authLoading } = useAuth();
  const [selected, setSelected] = useState<TargetRole | null>(null);
  const [selectedTemplate, setSelectedTemplate] = useState<InterviewTemplate | null>(null);
  const [templates, setTemplates] = useState<InterviewTemplate[]>([]);
  const [language, setLanguage] = useState<"ru" | "en">("ru");
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const role = searchParams.get("role") as TargetRole | null;
    if (role && ROLES.some((r) => r.value === role)) {
      setSelected(role);
    }
  }, [searchParams]);

  useEffect(() => {
    templateApi.listPublic().then(setTemplates).catch(() => null);
  }, []);

  async function handleStart() {
    if (!selected) return;
    setError("");
    setStarting(true);
    try {
      const res = await interviewApi.start({
        target_role: selected,
        template_id: selectedTemplate?.template_id ?? null,
        language,
      });
      router.push(`/candidate/interview/${res.interview_id}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not start interview");
      setStarting(false);
    }
  }

  function selectTemplate(tmpl: InterviewTemplate) {
    setSelectedTemplate(tmpl);
    setSelected(tmpl.target_role as TargetRole);
  }

  function clearTemplate() {
    setSelectedTemplate(null);
  }

  if (authLoading) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="text-slate-400">Loading…</div>
      </div>
    );
  }

  const roleTemplates = templates.filter((t) => !selected || t.target_role === selected);

  return (
    <div className="min-h-screen bg-slate-900 px-4 py-10">
      <div className="max-w-lg mx-auto">
        <Link href="/candidate/dashboard" className="text-slate-400 hover:text-white text-sm mb-6 inline-block">
          ← Back to dashboard
        </Link>

        <h1 className="text-2xl font-bold text-white mb-2">Start AI Interview</h1>
        <p className="text-slate-400 mb-8">
          Choose your target role. You&apos;ll answer 8 questions. The interview takes 15–20 minutes.
        </p>

        {error && (
          <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg px-4 py-3 mb-6">
            {error}
          </div>
        )}

        {/* Role selection */}
        <div className="space-y-3 mb-8">
          {ROLES.map((role) => (
            <button
              key={role.value}
              onClick={() => { setSelected(role.value); clearTemplate(); }}
              className={`w-full text-left p-5 rounded-xl border transition-all ${
                selected === role.value
                  ? "border-blue-500 bg-blue-500/10"
                  : "border-slate-700 bg-slate-800 hover:border-slate-600"
              }`}
            >
              <div className={`font-semibold mb-1 ${selected === role.value ? "text-blue-300" : "text-white"}`}>
                {role.label}
              </div>
              <div className="text-slate-400 text-sm">{role.desc}</div>
            </button>
          ))}
        </div>

        {/* Public templates */}
        {templates.length > 0 && (
          <div className="mb-8">
            <h2 className="text-white font-semibold mb-3">
              Company Templates
              {selected && roleTemplates.length > 0 && (
                <span className="ml-2 text-xs text-slate-400 font-normal">
                  ({roleTemplates.length} for {ROLE_LABELS[selected]})
                </span>
              )}
            </h2>
            {(selected ? roleTemplates : templates).length === 0 ? (
              <p className="text-slate-500 text-sm">No public templates for this role.</p>
            ) : (
              <div className="space-y-2">
                {(selected ? roleTemplates : templates).map((tmpl) => (
                  <button
                    key={tmpl.template_id}
                    onClick={() => selectTemplate(tmpl)}
                    className={`w-full text-left p-4 rounded-xl border transition-all ${
                      selectedTemplate?.template_id === tmpl.template_id
                        ? "border-purple-500 bg-purple-500/10"
                        : "border-slate-700 bg-slate-800 hover:border-slate-600"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className={`font-medium text-sm ${selectedTemplate?.template_id === tmpl.template_id ? "text-purple-300" : "text-white"}`}>
                        {tmpl.name}
                      </span>
                      <span className="text-xs text-slate-500 shrink-0">
                        {tmpl.questions.length}q · {ROLE_LABELS[tmpl.target_role] ?? tmpl.target_role}
                      </span>
                    </div>
                    {tmpl.description && (
                      <p className="text-slate-400 text-xs mt-1">{tmpl.description}</p>
                    )}
                  </button>
                ))}
              </div>
            )}
            {selectedTemplate && (
              <button
                onClick={clearTemplate}
                className="mt-2 text-slate-400 hover:text-white text-xs transition-colors"
              >
                ✕ Clear template selection (use AI questions)
              </button>
            )}
          </div>
        )}

        {selectedTemplate && (
          <div className="bg-purple-500/10 border border-purple-500/20 rounded-xl px-4 py-3 mb-6 text-sm text-purple-300">
            Using template: <span className="font-semibold">{selectedTemplate.name}</span>
            {" "}({selectedTemplate.questions.length} custom questions)
          </div>
        )}

        {/* Language selection */}
        <div className="mb-6">
          <p className="text-slate-400 text-sm mb-2">Interview language:</p>
          <div className="flex gap-2">
            <button
              onClick={() => setLanguage("ru")}
              className={`flex-1 py-2 rounded-lg border text-sm font-medium transition-colors ${
                language === "ru"
                  ? "bg-blue-500/15 border-blue-500/40 text-blue-400"
                  : "bg-slate-800 border-slate-700 text-slate-400 hover:border-slate-600"
              }`}
            >
              🇷🇺 Русский
            </button>
            <button
              onClick={() => setLanguage("en")}
              className={`flex-1 py-2 rounded-lg border text-sm font-medium transition-colors ${
                language === "en"
                  ? "bg-blue-500/15 border-blue-500/40 text-blue-400"
                  : "bg-slate-800 border-slate-700 text-slate-400 hover:border-slate-600"
              }`}
            >
              🇬🇧 English
            </button>
          </div>
        </div>

        <button
          onClick={handleStart}
          disabled={!selected || starting}
          className="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold py-3 rounded-lg transition-colors"
        >
          {starting ? "Starting…" : "Start Interview"}
        </button>
      </div>
    </div>
  );
}

export default function StartInterviewPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="text-slate-400">Loading…</div>
      </div>
    }>
      <StartInterviewInner />
    </Suspense>
  );
}
