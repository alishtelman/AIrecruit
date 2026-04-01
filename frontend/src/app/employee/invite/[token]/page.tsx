"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useParams, useRouter } from "next/navigation";
import { authApi, employeeApi } from "@/lib/api";
import type { EmployeeInviteInfo } from "@/lib/types";

function formatDate(value: string | null): string | null {
  if (!value) return null;
  return new Date(value).toLocaleString();
}

export default function EmployeeInvitePage() {
  const t = useTranslations("employeeInvite");
  const { token } = useParams<{ token: string }>();
  const router = useRouter();
  const [info, setInfo] = useState<EmployeeInviteInfo | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [language, setLanguage] = useState<"ru" | "en">("ru");
  const [hasSession, setHasSession] = useState(false);

  useEffect(() => {
    setLoading(true);
    employeeApi
      .getInvite(token)
      .then(setInfo)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : t("errors.notFoundOrExpired")))
      .finally(() => setLoading(false));
  }, [token, t]);

  useEffect(() => {
    authApi.me().then(() => setHasSession(true)).catch(() => setHasSession(false));
  }, []);

  async function handleStart() {
    if (!hasSession) {
      sessionStorage.setItem("employee_invite_token", token);
      router.push(`/candidate/login?redirect=/employee/invite/${token}`);
      return;
    }

    setStarting(true);
    setError("");
    try {
      const { interview_id } = await employeeApi.startAssessment(token, language);
      router.push(`/candidate/interview/${interview_id}`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t("errors.startFailed"));
      setStarting(false);
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-[#08111e] flex items-center justify-center">
        <div className="text-slate-400">{t("loading")}</div>
      </div>
    );
  }

  if (error && !info) {
    return (
      <div className="min-h-screen bg-[#08111e] flex items-center justify-center px-4">
        <div className="w-full max-w-md rounded-[28px] border border-rose-500/20 bg-slate-950/80 p-8 text-center">
          <h1 className="mt-4 text-xl font-semibold text-white">{t("unavailable.title")}</h1>
          <p className="mt-2 text-sm text-slate-400">{error}</p>
        </div>
      </div>
    );
  }

  if (!info) return null;

  const brandName = info.branding_name || info.company_name;
  const isCandidateCampaign = info.assessment_type === "candidate_external";
  const deadlineLabel = formatDate(info.deadline_at);
  const expiresLabel = formatDate(info.expires_at);
  const isCompleted = info.status === "completed";
  const isExpired = info.status === "expired";

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top,_rgba(34,197,94,0.12),_transparent_28%),linear-gradient(180deg,_#071019_0%,_#0f172a_100%)] px-4 py-10">
      <div className="mx-auto grid max-w-5xl gap-6 lg:grid-cols-[1.1fr_0.9fr]">
        <section className="rounded-[32px] border border-slate-800 bg-slate-950/80 p-8 shadow-2xl shadow-black/20">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="text-xs uppercase tracking-[0.2em] text-emerald-300">
                {isCandidateCampaign ? t("kinds.candidate") : t("kinds.internal")}
              </div>
              <h1 className="mt-3 text-3xl font-semibold text-white">{brandName}</h1>
              <p className="mt-3 max-w-xl text-sm leading-6 text-slate-400">
                {isCandidateCampaign
                  ? t("description.candidate", { company: info.company_name, role: info.role_label })
                  : t("description.internal", { company: info.company_name })}
              </p>
            </div>
            <div
              className="flex h-14 w-14 items-center justify-center rounded-2xl border border-slate-800 bg-emerald-500/10 text-xl text-white"
              style={
                info.branding_logo_url
                  ? {
                      backgroundImage: `url(${info.branding_logo_url})`,
                      backgroundPosition: "center",
                      backgroundRepeat: "no-repeat",
                      backgroundSize: "cover",
                    }
                  : undefined
              }
            >
              {!info.branding_logo_url ? (isCandidateCampaign ? "CA" : "IA") : null}
            </div>
          </div>

          <div className="mt-8 grid gap-4 rounded-[28px] border border-slate-800 bg-slate-900/60 p-5 md:grid-cols-2">
            <Detail label={isCandidateCampaign ? t("details.candidate") : t("details.invitee")} value={info.employee_name} />
            <Detail label={t("details.email")} value={info.employee_email} />
            <Detail label={t("details.targetRole")} value={info.role_label} />
            <Detail label={t("details.status")} value={t(`status.${info.status}`)} />
            <Detail label={t("details.template")} value={info.template_name || t("details.adaptiveDefault")} />
            <Detail label={t("details.company")} value={info.company_name} />
            {deadlineLabel ? <Detail label={t("details.deadline")} value={deadlineLabel} /> : null}
            {expiresLabel ? <Detail label={t("details.expires")} value={expiresLabel} /> : null}
          </div>

          <div className="mt-6 rounded-[28px] border border-slate-800 bg-slate-900/40 p-5 text-sm leading-6 text-slate-300">
            <p>
              {t("flow.questionsPrefix")} <span className="font-semibold text-white">{t("flow.questionsCount")}</span> {t("flow.questionsSuffix")}
            </p>
            <p className="mt-3">
              {t("flow.visibilityPrefix")} <span className="font-semibold text-white">{info.company_name}</span>{t("flow.visibilitySuffix")}
            </p>
          </div>

          {error && (
            <div className="mt-5 rounded-2xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
              {error}
            </div>
          )}

          {isCompleted ? (
            <StateCard
              tone="green"
              title={t("state.completedTitle")}
              body={t("state.completedBody", { company: info.company_name })}
            />
          ) : isExpired ? (
            <StateCard
              tone="rose"
              title={t("state.expiredTitle")}
              body={t("state.expiredBody")}
            />
          ) : (
            <>
              <div className="mt-6">
                <div className="mb-2 text-sm text-slate-400">{t("language.title")}</div>
                <div className="flex gap-2">
                  <LanguageButton
                    active={language === "ru"}
                    label={t("language.ru")}
                    onClick={() => setLanguage("ru")}
                  />
                  <LanguageButton
                    active={language === "en"}
                    label={t("language.en")}
                    onClick={() => setLanguage("en")}
                  />
                </div>
              </div>

              <button
                onClick={handleStart}
                disabled={starting}
                className="mt-6 w-full rounded-2xl bg-emerald-500 py-3 text-sm font-semibold text-slate-950 transition-colors hover:bg-emerald-400 disabled:opacity-50"
              >
                {starting ? t("actions.starting") : hasSession ? t("actions.start") : t("actions.signInAndStart")}
              </button>

              {!hasSession && (
                <p className="mt-3 text-center text-xs text-slate-500">
                  {t("actions.needAccount")}{" "}
                  <a href={`/candidate/register?redirect=/employee/invite/${token}`} className="text-emerald-300 hover:underline">
                    {t("actions.register")}
                  </a>
                </p>
              )}
            </>
          )}
        </section>

        <aside className="rounded-[32px] border border-slate-800 bg-slate-950/70 p-8">
          <div className="text-xs uppercase tracking-[0.2em] text-slate-500">{t("checklist.title")}</div>
          <div className="mt-5 space-y-5">
            <ChecklistItem
              title={t("checklist.emailTitle")}
              body={t("checklist.emailBody")}
            />
            <ChecklistItem
              title={t("checklist.timeTitle")}
              body={t("checklist.timeBody")}
            />
            <ChecklistItem
              title={t("checklist.privateTitle")}
              body={t("checklist.privateBody")}
            />
            <ChecklistItem
              title={t("checklist.templateTitle")}
              body={info.template_name ? t("checklist.templateCustom", { name: info.template_name }) : t("checklist.templateDefault")}
            />
          </div>
        </aside>
      </div>
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-[0.16em] text-slate-500">{label}</div>
      <div className="mt-1 text-sm text-white">{value}</div>
    </div>
  );
}

function LanguageButton({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex-1 rounded-2xl border px-4 py-2.5 text-sm font-medium transition-colors ${
        active
          ? "border-emerald-400/50 bg-emerald-500/15 text-emerald-200"
          : "border-slate-800 bg-slate-900 text-slate-400 hover:border-slate-700"
      }`}
    >
      {label}
    </button>
  );
}

function ChecklistItem({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
      <div className="text-sm font-semibold text-white">{title}</div>
      <div className="mt-1 text-sm leading-6 text-slate-400">{body}</div>
    </div>
  );
}

function StateCard({
  tone,
  title,
  body,
}: {
  tone: "green" | "rose";
  title: string;
  body: string;
}) {
  const styles =
    tone === "green"
      ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200"
      : "border-rose-500/30 bg-rose-500/10 text-rose-200";
  return (
    <div className={`mt-6 rounded-[28px] border p-5 ${styles}`}>
      <div className="text-lg font-semibold">{title}</div>
      <p className="mt-2 text-sm leading-6">{body}</p>
    </div>
  );
}
