"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { LocaleSwitcher } from "@/components/locale-switcher";
import { Link, useRouter } from "@/i18n/navigation";
import { useAuth } from "@/hooks/useAuth";
import { candidateApi, interviewApi } from "@/lib/api";
import { clearPreparedInterviewMedia, prepareInterviewMediaSession } from "@/lib/interviewMediaSession";
import type { TargetRole } from "@/lib/types";

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

function StartInterviewInner() {
  const t = useTranslations("interviewStart");
  const common = useTranslations("common");
  const router = useRouter();
  const searchParams = useSearchParams();
  const { loading: authLoading } = useAuth();
  const [selected, setSelected] = useState<TargetRole | null>(null);
  const [language, setLanguage] = useState<"ru" | "en">("ru");
  const [starting, setStarting] = useState(false);
  const [checkingResume, setCheckingResume] = useState(true);
  const [hasActiveResume, setHasActiveResume] = useState<boolean | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const role = searchParams.get("role") as TargetRole | null;
    if (role && ROLE_VALUES.includes(role)) {
      setSelected(role);
    }
  }, [searchParams]);

  useEffect(() => {
    if (authLoading) return;
    let cancelled = false;

    candidateApi
      .getResume()
      .then((resume) => {
        if (!cancelled) {
          setHasActiveResume(Boolean(resume));
        }
      })
      .catch(() => {
        if (!cancelled) {
          setHasActiveResume(null);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setCheckingResume(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [authLoading]);

  async function handleStart() {
    if (!selected) return;
    setError("");
    setStarting(true);

    try {
      await prepareInterviewMediaSession({
        requireCameraAndMic: true,
        tryScreenShare: false,
      });
    } catch {
      clearPreparedInterviewMedia();
      setError(t("cameraMicRequired"));
      setStarting(false);
      return;
    }

    try {
      const res = await interviewApi.start({
        target_role: selected,
        language,
      });
      router.push(`/candidate/interview/${res.interview_id}`);
    } catch (err: unknown) {
      clearPreparedInterviewMedia();
      setError(err instanceof Error ? err.message : t("startError"));
      setStarting(false);
    }
  }

  const roleLabel = (role: TargetRole) => t(`roles.${role}.label`);
  const roleDescription = (role: TargetRole) => t(`roles.${role}.desc`);
  const resumeMissing = hasActiveResume === false;
  const startDisabled = !selected || starting || checkingResume || resumeMissing;

  if (authLoading) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="text-slate-400">{common("status.loading")}</div>
      </div>
    );
  }

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

        {resumeMissing && (
          <div className="mb-6 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
            <p>{t("resumeRequired")}</p>
            <Link
              href="/candidate/resume"
              className="mt-2 inline-block font-medium text-amber-100 underline underline-offset-4 hover:text-white"
            >
              {t("uploadResumeCta")}
            </Link>
          </div>
        )}

        <div className="space-y-3 mb-8">
          {ROLE_VALUES.map((role) => (
            <button
              key={role}
              onClick={() => setSelected(role)}
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
          disabled={startDisabled}
          className="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold py-3 rounded-lg transition-colors"
        >
          {checkingResume ? t("checkingResume") : starting ? t("starting") : t("start")}
        </button>
      </div>
    </div>
  );
}

export default function StartInterviewPage() {
  const common = useTranslations("common");
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-slate-900 flex items-center justify-center">
          <div className="text-slate-400">{common("status.loading")}</div>
        </div>
      }
    >
      <StartInterviewInner />
    </Suspense>
  );
}
