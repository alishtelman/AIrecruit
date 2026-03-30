"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { LocaleSwitcher } from "@/components/locale-switcher";
import { Link, useRouter } from "@/i18n/navigation";
import { useAuth } from "@/hooks/useAuth";
import { interviewApi, templateApi } from "@/lib/api";
import { clearPreparedInterviewMedia, prepareInterviewMediaSession } from "@/lib/interviewMediaSession";
import type { InterviewTemplate, TargetRole } from "@/lib/types";

const ROLE_VALUES: TargetRole[] = [
  "backend_engineer",
  "frontend_engineer",
  "qa_engineer",
  "devops_engineer",
  "data_scientist",
  "product_manager",
  "mobile_engineer",
  "designer",
];

// Inner component that reads searchParams
function StartInterviewInner() {
  const t = useTranslations("interviewStart");
  const common = useTranslations("common");
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
    if (role && ROLE_VALUES.includes(role)) {
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
      await prepareInterviewMediaSession();
    } catch {
      setError(t("grantAccessError"));
      setStarting(false);
      return;
    }

    try {
      const res = await interviewApi.start({
        target_role: selected,
        template_id: selectedTemplate?.template_id ?? null,
        language,
      });
      router.push(`/candidate/interview/${res.interview_id}`);
    } catch (err: unknown) {
      clearPreparedInterviewMedia();
      setError(err instanceof Error ? err.message : t("startError"));
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
        <div className="text-slate-400">{common("status.loading")}</div>
      </div>
    );
  }

  const roleTemplates = templates.filter((t) => !selected || t.target_role === selected);
  const roleLabel = (role: TargetRole) => t(`roles.${role}.label`);
  const roleDescription = (role: TargetRole) => t(`roles.${role}.desc`);

  return (
    <div className="min-h-screen bg-slate-900 px-4 py-10">
      <div className="max-w-lg mx-auto">
        <div className="mb-6 flex items-center justify-between gap-4">
          <Link href="/candidate/dashboard" className="text-slate-400 hover:text-white text-sm inline-block">
            ← {t("back")}
          </Link>
          <LocaleSwitcher />
        </div>

        <h1 className="text-2xl font-bold text-white mb-2">{t("title")}</h1>
        <p className="text-slate-400 mb-8">{t("subtitle")}</p>

        {error && (
          <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg px-4 py-3 mb-6">
            {error}
          </div>
        )}

        {/* Role selection */}
        <div className="space-y-3 mb-8">
          {ROLE_VALUES.map((role) => (
            <button
              key={role}
              onClick={() => { setSelected(role); clearTemplate(); }}
              className={`w-full text-left p-5 rounded-xl border transition-all ${
                selected === role
                  ? "border-blue-500 bg-blue-500/10"
                  : "border-slate-700 bg-slate-800 hover:border-slate-600"
              }`}
            >
              <div className={`font-semibold mb-1 ${selected === role ? "text-blue-300" : "text-white"}`}>
                {roleLabel(role)}
              </div>
              <div className="text-slate-400 text-sm">{roleDescription(role)}</div>
            </button>
          ))}
        </div>

        {/* Public templates */}
        {templates.length > 0 && (
          <div className="mb-8">
            <h2 className="text-white font-semibold mb-3">
              {t("companyTemplates")}
              {selected && roleTemplates.length > 0 && (
                <span className="ml-2 text-xs text-slate-400 font-normal">
                  ({roleTemplates.length} · {roleLabel(selected)})
                </span>
              )}
            </h2>
            {(selected ? roleTemplates : templates).length === 0 ? (
              <p className="text-slate-500 text-sm">{t("noTemplates")}</p>
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
                        {t("templateQuestions", {count: tmpl.questions.length})} · {roleLabel(tmpl.target_role)}
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
                {t("clearTemplate")}
              </button>
            )}
          </div>
        )}

        {selectedTemplate && (
          <div className="bg-purple-500/10 border border-purple-500/20 rounded-xl px-4 py-3 mb-6 text-sm text-purple-300">
            {t("usingTemplate", {name: selectedTemplate.name, count: selectedTemplate.questions.length})}
          </div>
        )}

        {/* Language selection */}
        <div className="mb-6">
          <p className="text-slate-400 text-sm mb-2">{t("language")}:</p>
          <div className="flex gap-2">
            <button
              onClick={() => setLanguage("ru")}
              className={`flex-1 py-2 rounded-lg border text-sm font-medium transition-colors ${
                language === "ru"
                  ? "bg-blue-500/15 border-blue-500/40 text-blue-400"
                  : "bg-slate-800 border-slate-700 text-slate-400 hover:border-slate-600"
              }`}
            >
              RU
            </button>
            <button
              onClick={() => setLanguage("en")}
              className={`flex-1 py-2 rounded-lg border text-sm font-medium transition-colors ${
                language === "en"
                  ? "bg-blue-500/15 border-blue-500/40 text-blue-400"
                  : "bg-slate-800 border-slate-700 text-slate-400 hover:border-slate-600"
              }`}
            >
              EN
            </button>
          </div>
          <p className="mt-2 text-xs text-slate-500">{t("recordingHint")}</p>
        </div>

        <button
          onClick={handleStart}
          disabled={!selected || starting}
          className="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold py-3 rounded-lg transition-colors"
        >
          {starting ? t("starting") : t("start")}
        </button>
      </div>
    </div>
  );
}

export default function StartInterviewPage() {
  const common = useTranslations("common");
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="text-slate-400">{common("status.loading")}</div>
      </div>
    }>
      <StartInterviewInner />
    </Suspense>
  );
}
