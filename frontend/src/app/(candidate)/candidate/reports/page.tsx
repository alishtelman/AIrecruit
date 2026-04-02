"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Link, useRouter } from "@/i18n/navigation";
import { interviewApi } from "@/lib/api";
import type { InterviewListItem, InterviewStatus } from "@/lib/types";

export default function ReportsPage() {
  const t = useTranslations("candidateReports");
  const startT = useTranslations("interviewStart");
  const router = useRouter();
  const [interviews, setInterviews] = useState<InterviewListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
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
  }, [router, t]);

  const statusConfig: Record<InterviewStatus, { label: string; className: string }> = {
    created: { label: t("statuses.created"), className: "text-slate-400" },
    in_progress: { label: t("statuses.in_progress"), className: "text-yellow-400" },
    completed: { label: t("statuses.completed"), className: "text-blue-400" },
    report_processing: { label: t("statuses.report_processing"), className: "text-blue-400" },
    report_generated: { label: t("statuses.report_generated"), className: "text-green-400" },
    failed: { label: t("statuses.failed"), className: "text-red-400" },
  };

  return (
    <div className="min-h-screen bg-slate-900 px-4 py-10">
      <div className="max-w-2xl mx-auto">
        <Link href="/candidate/dashboard" className="text-slate-400 hover:text-white text-sm mb-6 inline-block transition-colors">
          ← {t("back")}
        </Link>

        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold text-white">{t("title")}</h1>
          <Link
            href="/candidate/interview/start"
            className="bg-blue-600 hover:bg-blue-500 text-white text-sm font-semibold px-4 py-2 rounded-lg transition-colors"
          >
            {t("newInterview")}
          </Link>
        </div>

        {loading && (
          <div className="space-y-3">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="bg-slate-800 border border-slate-700 rounded-xl p-5 flex items-center justify-between gap-4 animate-pulse">
                <div className="space-y-2">
                  <div className="h-4 w-36 bg-slate-700 rounded" />
                  <div className="h-3 w-20 bg-slate-700 rounded" />
                  <div className="h-3 w-24 bg-slate-700 rounded" />
                </div>
                <div className="h-3 w-20 bg-slate-700 rounded" />
                <div className="h-9 w-24 bg-slate-700 rounded-lg" />
              </div>
            ))}
          </div>
        )}

        {error && (
          <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg px-4 py-3">
            {error}
          </div>
        )}

        {!loading && !error && interviews.length === 0 && (
          <div className="bg-slate-800 border border-slate-700 rounded-xl p-12 text-center">
            <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl border border-slate-700 bg-slate-900 text-xs font-semibold tracking-[0.2em] text-slate-400">AR</div>
            <h2 className="text-white font-semibold text-lg mb-2">{t("emptyTitle")}</h2>
            <p className="text-slate-400 text-sm max-w-sm mx-auto mb-6">
              {t("emptyDescription")}
            </p>
            <Link
              href="/candidate/interview/start"
              className="inline-block bg-blue-600 hover:bg-blue-500 text-white font-semibold px-6 py-2.5 rounded-lg transition-colors"
            >
              {t("startInterview")}
            </Link>
          </div>
        )}

        {!loading && interviews.length > 0 && (
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
                  className="bg-slate-800 border border-slate-700 rounded-xl p-5 flex items-center justify-between gap-4"
                >
                  <div>
                    <div className="text-white font-semibold">{role}</div>
                    <div className="text-slate-500 text-sm mt-0.5">{date}</div>
                    <div className={`text-sm mt-1 ${status.className}`}>{status.label}</div>
                  </div>

                  <div className="text-sm text-slate-500 shrink-0">
                    {t("questions", {current: item.question_count, total: item.max_questions})}
                  </div>

                  <div className="shrink-0 flex flex-col gap-2 items-end">
                    {item.status === "report_generated" && item.report_id ? (
                      <>
                        <Link
                          href={`/candidate/reports/${item.report_id}`}
                          className="bg-blue-600 hover:bg-blue-500 text-white text-sm font-semibold px-4 py-2 rounded-lg transition-colors"
                        >
                          {t("viewReport")}
                        </Link>
                        <Link
                          href={`/candidate/interview/start?role=${item.target_role}`}
                          className="bg-slate-700 hover:bg-slate-600 text-white text-xs font-semibold px-4 py-1.5 rounded-lg transition-colors"
                        >
                          {t("retake")}
                        </Link>
                      </>
                    ) : item.status === "in_progress" || item.status === "report_processing" ? (
                      <Link
                        href={`/candidate/interview/${item.interview_id}`}
                        className="bg-slate-700 hover:bg-slate-600 text-white text-sm font-semibold px-4 py-2 rounded-lg transition-colors"
                      >
                        {t("continue")}
                      </Link>
                    ) : (
                      <span className="text-slate-600 text-sm">—</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
