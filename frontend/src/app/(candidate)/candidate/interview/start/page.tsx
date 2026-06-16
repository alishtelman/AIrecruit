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
import { CandidateShell } from "@/components/candidate-shell";
import { PageHeader, PanelCard, StatusBadge } from "@/components/ui/primitives";

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
  const { loading: authLoading } = useAuth({ allowedRoles: ["candidate"] });
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
      <div className="flex min-h-screen items-center justify-center bg-[#F4F5F7]">
        <div className="font-semibold text-slate-500">{common("status.loading")}</div>
      </div>
    );
  }

  return (
    <CandidateShell>
      <div className="mx-auto max-w-5xl py-6">
        <PageHeader
          eyebrow="Voice interview"
          title={t("title")}
          description={t("subtitle")}
          actions={
            <div className="flex items-center gap-3">
              <LocaleSwitcher />
              <Link href="/candidate/dashboard" className="candidate-btn-secondary rounded-xl px-4 py-2 text-sm font-bold">
                ← {t("back")}
              </Link>
            </div>
          }
        />

        <div className="mb-6 grid gap-4 md:grid-cols-3">
          <PanelCard className="p-5">
            <StatusBadge tone="info">01</StatusBadge>
            <h2 className="mt-4 font-manrope text-lg font-bold text-[#1A1C22]">Выберите роль</h2>
            <p className="mt-2 text-sm leading-6 text-[#56596a]">AI подстроит структуру интервью, практику и рубрики под выбранную позицию.</p>
          </PanelCard>
          <PanelCard className="p-5">
            <StatusBadge tone="success">02</StatusBadge>
            <h2 className="mt-4 font-manrope text-lg font-bold text-[#1A1C22]">Голосовой формат</h2>
            <p className="mt-2 text-sm leading-6 text-[#56596a]">{t("recordingHint")}</p>
          </PanelCard>
          <PanelCard className="p-5">
            <StatusBadge tone="neutral">03</StatusBadge>
            <h2 className="mt-4 font-manrope text-lg font-bold text-[#1A1C22]">Отчёт после финала</h2>
            <p className="mt-2 text-sm leading-6 text-[#56596a]">После завершения вы получите понятный отчёт с сильными сторонами и roadmap.</p>
          </PanelCard>
        </div>

        <PanelCard className="p-6 sm:p-8">
          {error && (
            <div className="mb-6 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-700">
              {error}
            </div>
          )}

          {resumeMissing && (
            <div className="mb-6 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
              <p className="font-semibold">{t("resumeRequired")}</p>
              <Link
                href="/candidate/resume"
                className="mt-2 inline-block font-bold text-amber-900 underline underline-offset-4 hover:text-[#1A1C22]"
              >
                {t("uploadResumeCta")}
              </Link>
            </div>
          )}

          <div className="mb-8 grid gap-3 md:grid-cols-2">
            {ROLE_VALUES.map((role) => (
              <button
                key={role}
                onClick={() => setSelected(role)}
                className={`w-full rounded-2xl border p-5 text-left transition-all ${
                  selected === role
                    ? "border-[#2F5BEA] bg-[#EEF2FF] shadow-[0_12px_28px_rgba(47,91,234,0.12)]"
                    : "border-[#E9EAEE] bg-[#FAFBFC] hover:border-slate-300 hover:bg-white"
                }`}
              >
                <div className={`mb-1 font-bold ${selected === role ? "text-[#2348C8]" : "text-[#1A1C22]"}`}>
                  {roleLabel(role)}
                </div>
                <div className="text-sm leading-6 text-[#56596a]">{roleDescription(role)}</div>
              </button>
            ))}
          </div>

          <div className="mb-6">
            <p className="mb-2 text-sm font-bold text-[#56596a]">{t("language")}:</p>
            <div className="flex gap-2">
              <button
                onClick={() => setLanguage("ru")}
                className={`flex-1 rounded-xl border py-2.5 text-sm font-bold transition-colors ${
                  language === "ru"
                    ? "border-[#2F5BEA] bg-[#EEF2FF] text-[#2348C8]"
                    : "border-[#E0E1E6] bg-white text-[#56596a] hover:border-slate-300"
                }`}
              >
                RU
              </button>
              <button
                onClick={() => setLanguage("en")}
                className={`flex-1 rounded-xl border py-2.5 text-sm font-bold transition-colors ${
                  language === "en"
                    ? "border-[#2F5BEA] bg-[#EEF2FF] text-[#2348C8]"
                    : "border-[#E0E1E6] bg-white text-[#56596a] hover:border-slate-300"
                }`}
              >
                EN
              </button>
            </div>
          </div>

          <button
            onClick={handleStart}
            disabled={startDisabled}
            className="candidate-btn-primary w-full rounded-xl py-3.5 text-base font-bold shadow-[0_8px_20px_rgba(47,91,234,0.25)] disabled:cursor-not-allowed disabled:opacity-40"
          >
            {checkingResume ? t("checkingResume") : starting ? t("starting") : t("start")}
          </button>
        </PanelCard>
      </div>
    </CandidateShell>
  );
}

export default function StartInterviewPage() {
  const common = useTranslations("common");
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-[#F4F5F7]">
          <div className="text-slate-500">{common("status.loading")}</div>
        </div>
      }
    >
      <StartInterviewInner />
    </Suspense>
  );
}
