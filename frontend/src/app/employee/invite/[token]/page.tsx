"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { authApi, employeeApi } from "@/lib/api";
import type { EmployeeInviteInfo } from "@/lib/types";

function formatDate(value: string | null): string | null {
  if (!value) return null;
  return new Date(value).toLocaleString();
}

export default function EmployeeInvitePage() {
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
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Invite not found or expired"))
      .finally(() => setLoading(false));
  }, [token]);

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
      setError(e instanceof Error ? e.message : "Failed to start assessment");
      setStarting(false);
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-[#08111e] flex items-center justify-center">
        <div className="text-slate-400">Loading invite…</div>
      </div>
    );
  }

  if (error && !info) {
    return (
      <div className="min-h-screen bg-[#08111e] flex items-center justify-center px-4">
        <div className="w-full max-w-md rounded-[28px] border border-rose-500/20 bg-slate-950/80 p-8 text-center">
          <div className="text-4xl">⚠️</div>
          <h1 className="mt-4 text-xl font-semibold text-white">Invite unavailable</h1>
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
                {isCandidateCampaign ? "Candidate Assessment" : "Internal Assessment"}
              </div>
              <h1 className="mt-3 text-3xl font-semibold text-white">{brandName}</h1>
              <p className="mt-3 max-w-xl text-sm leading-6 text-slate-400">
                {isCandidateCampaign
                  ? `${info.company_name} invited you to complete a private AI screening flow for ${info.role_label}.`
                  : `${info.company_name} invited you to complete a private AI assessment as part of an internal review flow.`}
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
              {!info.branding_logo_url ? (isCandidateCampaign ? "🚀" : "🎯") : null}
            </div>
          </div>

          <div className="mt-8 grid gap-4 rounded-[28px] border border-slate-800 bg-slate-900/60 p-5 md:grid-cols-2">
            <Detail label={isCandidateCampaign ? "Candidate" : "Invitee"} value={info.employee_name} />
            <Detail label="Email" value={info.employee_email} />
            <Detail label="Target role" value={info.role_label} />
            <Detail label="Status" value={info.status.replace("_", " ")} />
            <Detail label="Template" value={info.template_name || "Adaptive default"} />
            <Detail label="Company" value={info.company_name} />
            {deadlineLabel ? <Detail label="Deadline" value={deadlineLabel} /> : null}
            {expiresLabel ? <Detail label="Invite expires" value={expiresLabel} /> : null}
          </div>

          <div className="mt-6 rounded-[28px] border border-slate-800 bg-slate-900/40 p-5 text-sm leading-6 text-slate-300">
            <p>
              The flow contains <span className="font-semibold text-white">8 structured questions</span> and usually
              takes 15–20 minutes.
            </p>
            <p className="mt-3">
              Your answers will be reviewed by AI and the results will remain visible only to{" "}
              <span className="font-semibold text-white">{info.company_name}</span>.
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
              title="Assessment completed"
              body={`This invite has already been completed. ${info.company_name} can already access the private report.`}
            />
          ) : isExpired ? (
            <StateCard
              tone="rose"
              title="Invite expired"
              body="This invite can no longer be started. Contact the company if you need a new campaign link."
            />
          ) : (
            <>
              <div className="mt-6">
                <div className="mb-2 text-sm text-slate-400">Interview language</div>
                <div className="flex gap-2">
                  <LanguageButton
                    active={language === "ru"}
                    label="🇷🇺 Русский"
                    onClick={() => setLanguage("ru")}
                  />
                  <LanguageButton
                    active={language === "en"}
                    label="🇬🇧 English"
                    onClick={() => setLanguage("en")}
                  />
                </div>
              </div>

              <button
                onClick={handleStart}
                disabled={starting}
                className="mt-6 w-full rounded-2xl bg-emerald-500 py-3 text-sm font-semibold text-slate-950 transition-colors hover:bg-emerald-400 disabled:opacity-50"
              >
                {starting ? "Starting…" : hasSession ? "Start assessment" : "Sign in and start"}
              </button>

              {!hasSession && (
                <p className="mt-3 text-center text-xs text-slate-500">
                  You need a candidate account to continue.{" "}
                  <a href={`/candidate/register?redirect=/employee/invite/${token}`} className="text-emerald-300 hover:underline">
                    Register here
                  </a>
                </p>
              )}
            </>
          )}
        </section>

        <aside className="rounded-[32px] border border-slate-800 bg-slate-950/70 p-8">
          <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Before you begin</div>
          <div className="mt-5 space-y-5">
            <ChecklistItem
              title="Use the invited email"
              body="The assessment is locked to the email on this page. A different candidate account will be rejected."
            />
            <ChecklistItem
              title="Keep enough time"
              body="Once started, the flow becomes an in-progress private campaign linked to your account."
            />
            <ChecklistItem
              title="Private by design"
              body="This report will not be exposed in the public candidate marketplace."
            />
            <ChecklistItem
              title="Template-aware"
              body={info.template_name ? `This campaign uses the "${info.template_name}" template.` : "This campaign uses the adaptive default interview."}
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
