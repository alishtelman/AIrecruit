"use client";

import { Link } from "@/i18n/navigation";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useParams } from "next/navigation";
import { authApi, candidateApi, companyApi } from "@/lib/api";
import type { CompanyShareAccessStatus, SharedCandidateProfile, User } from "@/lib/types";

function formatSalary(profile: SharedCandidateProfile, emptyLabel: string): string {
  if (profile.salary_min == null && profile.salary_max == null) {
    return emptyLabel;
  }
  const low = profile.salary_min ?? profile.salary_max;
  const high = profile.salary_max ?? profile.salary_min;
  if (low == null || high == null) {
    return emptyLabel;
  }
  return low === high
    ? `${low.toLocaleString()} ${profile.salary_currency}`
    : `${low.toLocaleString()}–${high.toLocaleString()} ${profile.salary_currency}`;
}

export default function SharedCandidatePage() {
  const t = useTranslations("sharedProfile");
  const reportT = useTranslations("report");
  const startT = useTranslations("interviewStart");
  const params = useParams<{ token: string }>();
  const [profile, setProfile] = useState<SharedCandidateProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [viewer, setViewer] = useState<User | null>(null);
  const [accessStatus, setAccessStatus] = useState<CompanyShareAccessStatus | null>(null);
  const [requestingAccess, setRequestingAccess] = useState(false);

  useEffect(() => {
    const token = Array.isArray(params.token) ? params.token[0] : params.token;
    if (!token) return;

    candidateApi.getSharedProfile(token)
      .then((data) => {
        setProfile(data);
        setError(null);
      })
      .catch((err: Error) => {
        setError(err.message || t("errors.notFound"));
      })
      .finally(() => setLoading(false));
  }, [params.token, t]);

  useEffect(() => {
    const token = Array.isArray(params.token) ? params.token[0] : params.token;
    if (!token || !profile || profile.visibility !== "request_only") return;

    authApi.me()
      .then((user) => {
        setViewer(user);
        if (user.role === "company_admin" || user.role === "company_member") {
          return companyApi.getShareLinkAccessStatus(token).then(setAccessStatus);
        }
        return null;
      })
      .catch(() => null);
  }, [params.token, profile]);

  async function handleRequestAccess() {
    const token = Array.isArray(params.token) ? params.token[0] : params.token;
    if (!token) return;
    setRequestingAccess(true);
    try {
      const response = await companyApi.requestShareLinkAccess(token);
      setAccessStatus(response);
    } catch {
      // ignore
    } finally {
      setRequestingAccess(false);
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#F4F5F7]">
        <p className="font-semibold text-[#56596a]">{t("loading")}</p>
      </div>
    );
  }

  if (error || !profile) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#F4F5F7] px-4">
        <div className="max-w-lg rounded-3xl border border-[#E9EAEE] bg-white p-8 text-center shadow-[0_20px_50px_rgba(20,22,30,0.06)]">
          <p className="mb-2 font-bold text-red-700">{t("errors.unavailable")}</p>
          <p className="text-sm text-[#56596a]">{error ?? t("errors.noLongerAvailable")}</p>
          <Link href="/" className="mt-6 inline-block text-sm font-bold text-[#2F5BEA] hover:underline">
            {t("errors.returnHome")}
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#F4F5F7] text-[#1A1C22]">
      <div className="mx-auto max-w-5xl px-4 py-12">
        <Link href="/" className="mb-6 inline-flex items-center gap-3 text-sm font-bold text-[#56596a] hover:text-[#1A1C22]">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#14161B] font-manrope text-xs tracking-[0.16em] text-[#7E9BFF]">AI</span>
          AI HR
        </Link>

        <div className="mb-8 overflow-hidden rounded-[2rem] border border-[#D6E0FD] bg-[linear-gradient(135deg,#FFFFFF_0%,#EEF2FF_62%,#EAF8FF_100%)] p-8 shadow-[0_24px_60px_rgba(47,91,234,0.12)]">
          <p className="mb-3 text-sm font-bold uppercase tracking-[0.2em] text-[#2F5BEA]">{t("kicker")}</p>
          <h1 className="mb-3 font-manrope text-4xl font-bold tracking-tight text-[#1A1C22]">{profile.full_name}</h1>
          <p className="max-w-2xl text-[#56596a]">
            {profile.requires_approval
              ? t("requestOnlyDescription")
              : t("publicDescription")}
          </p>
          <div className="mt-6 inline-flex items-center rounded-full border border-[#D6E0FD] bg-white/70 px-4 py-2 text-sm font-semibold text-[#2348C8]">
            {t("salaryExpectation")}: {formatSalary(profile, t("notShared"))}
          </div>
        </div>

        {profile.requires_approval && (
          <div className="mb-6 rounded-3xl border border-[#D6E0FD] bg-white p-6 shadow-[0_12px_30px_rgba(20,22,30,0.04)]">
            <p className="mb-2 font-bold text-[#2348C8]">{t("requestOnlyTitle")}</p>
            <p className="text-sm leading-6 text-[#56596a]">{t("requestOnlyHelp")}</p>
            {(viewer?.role === "company_admin" || viewer?.role === "company_member") ? (
              <div className="mt-4 flex flex-wrap items-center gap-3">
                {accessStatus?.request_status === "approved" ? (
                  <>
                    <span className="rounded-full border border-[#D6E0FD] bg-[#ECF0FE] px-3 py-1 text-xs font-bold text-[#2348C8]">
                      {t("access.approved")}
                    </span>
                    {accessStatus.can_open_company_workspace && (
                      <Link
                        href={`/company/candidates/${profile.candidate_id}`}
                        className="candidate-btn-primary rounded-xl px-4 py-2 text-sm font-bold"
                      >
                        {t("access.openWorkspace")}
                      </Link>
                    )}
                  </>
                ) : (
                  <>
                    <span className={`px-3 py-1 rounded-full text-xs border ${
                      accessStatus?.request_status === "pending"
                        ? "bg-[#ECF0FE] text-[#2348C8] border-[#D6E0FD]"
                        : accessStatus?.request_status === "denied"
                          ? "bg-red-50 text-red-700 border-red-200"
                          : "bg-slate-50 text-[#56596a] border-slate-200"
                    }`}>
                      {accessStatus?.request_status === "pending"
                        ? t("access.pending")
                        : accessStatus?.request_status === "denied"
                          ? t("access.denied")
                          : t("access.none")}
                    </span>
                    <button
                      onClick={handleRequestAccess}
                      disabled={requestingAccess || accessStatus?.request_status === "pending"}
                      className="candidate-btn-primary rounded-xl px-4 py-2 text-sm font-bold disabled:opacity-50"
                    >
                      {requestingAccess ? t("access.requesting") : accessStatus?.request_status === "denied" ? t("access.requestAgain") : t("access.request")}
                    </button>
                  </>
                )}
              </div>
            ) : (
              <p className="mt-4 text-sm text-[#56596a]">{t("access.signInHint")}</p>
            )}
          </div>
        )}

        <div className="space-y-5">
          {profile.reports.length === 0 ? (
            <div className="rounded-3xl border border-[#E9EAEE] bg-white p-6 shadow-[0_12px_30px_rgba(20,22,30,0.04)]">
              <p className="text-[#56596a]">
                {profile.requires_approval
                  ? t("reports.hidden")
                  : t("reports.empty")}
              </p>
            </div>
          ) : (
            profile.reports.map((report) => (
              <div key={report.report_id} className="rounded-3xl border border-[#E9EAEE] bg-white p-6 shadow-[0_12px_30px_rgba(20,22,30,0.04)]">
                <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                  <div>
                    <p className="mb-1 text-sm font-bold text-[#2F5BEA]">{startT(`roles.${report.target_role}.label`)}</p>
                    <h2 className="font-manrope text-2xl font-bold text-[#1A1C22]">{report.overall_score != null ? `${report.overall_score.toFixed(1)}/10 ${t("reports.overall")}` : reportT("title")}</h2>
                    <p className="mt-2 text-sm leading-6 text-[#56596a]">{report.interview_summary ?? t("reports.noSummary")}</p>
                  </div>
                  <div className="min-w-[180px] rounded-2xl border border-[#E9EAEE] bg-[#FAFBFC] px-4 py-3">
                    <p className="mb-1 text-xs font-bold uppercase tracking-wide text-slate-400">{reportT("recommendation")}</p>
                    <p className="font-bold text-[#1A1C22]">{reportT(`labels.${report.hiring_recommendation === "strong_yes" ? "strongYes" : report.hiring_recommendation}`)}</p>
                  </div>
                </div>

                {report.skill_tags && report.skill_tags.length > 0 && (
                  <div className="mt-5">
                    <p className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-400">{t("reports.keySkills")}</p>
                    <div className="flex flex-wrap gap-2">
                      {report.skill_tags.slice(0, 8).map((tag) => (
                        <span key={`${report.report_id}-${tag.skill}`} className="rounded-full border border-[#D6E0FD] bg-[#ECF0FE] px-3 py-1 text-sm font-semibold text-[#2348C8]">
                          {tag.skill}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                <div className="grid gap-4 md:grid-cols-2 mt-5">
                  <div>
                    <p className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-400">{reportT("strengths")}</p>
                    <ul className="space-y-2 text-sm text-[#56596a]">
                      {report.strengths.length === 0 ? <li>{t("reports.noStrengths")}</li> : report.strengths.map((item) => <li key={item}>• {item}</li>)}
                    </ul>
                  </div>
                  <div>
                    <p className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-400">{reportT("recommendations")}</p>
                    <ul className="space-y-2 text-sm text-[#56596a]">
                      {report.recommendations.length === 0 ? <li>{t("reports.noRecommendations")}</li> : report.recommendations.map((item) => <li key={item}>• {item}</li>)}
                    </ul>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
