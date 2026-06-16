"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Link, useRouter } from "@/i18n/navigation";
import { interviewApi } from "@/lib/api";
import type { InterviewListItem, InterviewStatus } from "@/lib/types";
import { useAuth } from "@/hooks/useAuth";
import { CandidateShell } from "@/components/candidate-shell";

export default function ReportsPage() {
  const t = useTranslations("candidateReports");
  const startT = useTranslations("interviewStart");
  const router = useRouter();
  const { loading: authLoading } = useAuth({ allowedRoles: ["candidate"] });
  const [interviews, setInterviews] = useState<InterviewListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (authLoading) return;
    interviewApi.list()
      .then(setInterviews)
      .catch((err) => {
        if (err.message?.includes("401") || err.message?.includes("403")) {
          router.push("/candidate/login");
        } else {
          setError(err.message ?? t("loadFailed"));
        }
      })
      .finally(() => setLoading(false));
  }, [authLoading, router, t]);

  const statusConfig: Record<InterviewStatus, { label: string; className: string }> = {
    created: { label: t("statuses.created"), className: "text-slate-400" },
    in_progress: { label: t("statuses.in_progress"), className: "text-yellow-400" },
    completed: { label: t("statuses.completed"), className: "text-blue-400" },
    report_processing: { label: t("statuses.report_processing"), className: "text-blue-400" },
    report_generated: { label: t("statuses.report_generated"), className: "text-[#2348C8]" },
    failed: { label: t("statuses.failed"), className: "text-red-400" },
  };

  return (
    <CandidateShell>
      <div className="max-w-4xl mx-auto py-6">
        <div className="flex items-center justify-between mb-8">
          <div>
            <div className="text-xs uppercase tracking-widest text-[#9aa0ab] font-bold">Интервью</div>
            <h1 className="text-[34px] font-bold font-manrope tracking-tight text-[#1A1C22] mt-1.5 leading-none">
              {t("title") || "Мои интервью"}
            </h1>
          </div>
          <Link
            href="/candidate/interview/start"
            className="candidate-btn-primary px-5 py-2.5 text-sm font-bold rounded-xl shadow-[0_4px_12px_rgba(47,91,234,0.25)]"
          >
            {t("newInterview") || "Новое интервью"}
          </Link>
        </div>

        {(authLoading || loading) && (
          <div className="space-y-3">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="bg-white border border-[#E9EAEE] rounded-2xl p-6 flex items-center justify-between gap-4 animate-pulse">
                <div className="space-y-2 flex-1">
                  <div className="h-4 w-40 bg-slate-200 rounded" />
                  <div className="h-3.5 w-24 bg-slate-100 rounded" />
                  <div className="h-3 w-32 bg-slate-100 rounded" />
                </div>
                <div className="h-4 w-16 bg-slate-100 rounded" />
                <div className="h-10 w-28 bg-slate-200 rounded-xl" />
              </div>
            ))}
          </div>
        )}

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-600 text-sm rounded-lg px-4 py-3 font-semibold">
            {error}
          </div>
        )}

        {!authLoading && !loading && !error && interviews.length === 0 && (
          <div className="candidate-card p-12 text-center bg-white">
            <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl border border-slate-200 bg-slate-50 text-xs font-bold tracking-[0.2em] text-[#56596a]">AI</div>
            <h2 className="text-[#1A1C22] font-bold text-lg mb-2">{t("emptyTitle")}</h2>
            <p className="text-[#56596a] text-sm max-w-sm mx-auto mb-6">
              {t("emptyDescription")}
            </p>
            <Link
              href="/candidate/interview/start"
              className="candidate-btn-primary px-6 py-3 rounded-xl font-bold inline-block shadow-[0_4px_12px_rgba(47,91,234,0.3)]"
            >
              {t("startInterview")}
            </Link>
          </div>
        )}

        {!authLoading && !loading && interviews.length > 0 && (
          <div className="space-y-3">
            {interviews.map((item) => {
              const status = statusConfig[item.status] ?? statusConfig.created;
              const role = startT(`roles.${item.target_role}.label`);
              const date = item.started_at
                ? new Date(item.started_at).toLocaleDateString()
                : "—";

              return (
                <div
                  key={item.interview_id}
                  className="candidate-card p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4 border border-[#E9EAEE] bg-white transition-all hover:border-slate-300"
                >
                  <div className="min-w-0 flex-1">
                    <div className="text-[#1A1C22] font-bold text-[16px] truncate">{role}</div>
                    <div className="text-[#56596a] text-xs mt-1 font-medium">
                      Запущено: {date}
                    </div>
                    <div className="mt-2.5">
                      <span className={`px-2.5 py-0.5 rounded-full text-xs font-bold border ${
                        item.status === "report_generated"
                          ? "bg-[#ECF0FE] text-[#2348C8] border-[#D6E0FD]"
                          : item.status === "failed"
                          ? "bg-red-50 text-red-600 border-red-100"
                          : "bg-[#ECF0FE] text-[#2348C8] border-[#D6E0FD]"
                      }`}>
                        {status.label}
                      </span>
                    </div>
                  </div>

                  <div className="text-sm font-semibold text-[#56596a] shrink-0">
                    {t("questions", {current: item.question_count, total: item.max_questions})}
                  </div>

                  <div className="shrink-0 flex gap-2 items-center">
                    {item.status === "report_generated" && item.report_id ? (
                      <>
                        <Link
                          href={`/candidate/reports/${item.report_id}`}
                          className="candidate-btn-primary px-4 py-2 text-xs rounded-lg font-bold"
                        >
                          {t("viewReport")}
                        </Link>
                        <Link
                          href={`/candidate/interview/start?role=${item.target_role}`}
                          className="candidate-btn-secondary px-3 py-2 text-xs rounded-lg font-bold"
                        >
                          {t("retake")}
                        </Link>
                      </>
                    ) : item.status === "in_progress" || item.status === "report_processing" ? (
                      <Link
                        href={`/candidate/interview/${item.interview_id}`}
                        className="candidate-btn-primary px-4 py-2 text-xs rounded-lg font-bold"
                      >
                        {t("continue")}
                      </Link>
                    ) : (
                      <span className="text-[#8a8f9c] text-sm font-semibold px-2">—</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </CandidateShell>
  );
}
