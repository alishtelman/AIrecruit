"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { interviewApi } from "@/lib/api";
import type { InterviewListItem, InterviewStatus } from "@/lib/types";

const ROLE_LABELS: Record<string, string> = {
  backend_engineer: "Backend Engineer",
  frontend_engineer: "Frontend Engineer",
  qa_engineer: "QA Engineer",
  devops_engineer: "DevOps Engineer",
  data_scientist: "Data Scientist",
  product_manager: "Product Manager",
  mobile_engineer: "Mobile Engineer",
  designer: "UX/UI Designer",
};

const STATUS_CONFIG: Record<InterviewStatus, { label: string; className: string }> = {
  created:          { label: "Created",          className: "text-slate-400" },
  in_progress:      { label: "In Progress",      className: "text-yellow-400" },
  completed:        { label: "Processing…",      className: "text-blue-400" },
  report_generated: { label: "Report Ready",     className: "text-green-400" },
  failed:           { label: "Failed",           className: "text-red-400" },
};

export default function ReportsPage() {
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
          setError(err.message ?? "Failed to load interviews");
        }
      })
      .finally(() => setLoading(false));
  }, [router]);

  return (
    <div className="min-h-screen bg-slate-900 px-4 py-10">
      <div className="max-w-2xl mx-auto">
        <Link href="/candidate/dashboard" className="text-slate-400 hover:text-white text-sm mb-6 inline-block transition-colors">
          ← Back to dashboard
        </Link>

        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold text-white">My Interviews</h1>
          <Link
            href="/candidate/interview/start"
            className="bg-blue-600 hover:bg-blue-500 text-white text-sm font-semibold px-4 py-2 rounded-lg transition-colors"
          >
            + New Interview
          </Link>
        </div>

        {loading && (
          <div className="text-center py-16 text-slate-400">Loading…</div>
        )}

        {error && (
          <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg px-4 py-3">
            {error}
          </div>
        )}

        {!loading && !error && interviews.length === 0 && (
          <div className="bg-slate-800 border border-slate-700 rounded-xl p-12 text-center">
            <div className="text-4xl mb-4">📊</div>
            <h2 className="text-white font-semibold text-lg mb-2">No interviews yet</h2>
            <p className="text-slate-400 text-sm max-w-sm mx-auto mb-6">
              Complete an AI interview to receive your assessment report.
            </p>
            <Link
              href="/candidate/interview/start"
              className="inline-block bg-blue-600 hover:bg-blue-500 text-white font-semibold px-6 py-2.5 rounded-lg transition-colors"
            >
              Start Interview
            </Link>
          </div>
        )}

        {!loading && interviews.length > 0 && (
          <div className="space-y-3">
            {interviews.map((item) => {
              const status = STATUS_CONFIG[item.status] ?? STATUS_CONFIG.created;
              const role = ROLE_LABELS[item.target_role] ?? item.target_role;
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
                    {item.question_count}/{item.max_questions} questions
                  </div>

                  <div className="shrink-0">
                    {item.status === "report_generated" && item.report_id ? (
                      <Link
                        href={`/candidate/reports/${item.report_id}`}
                        className="bg-blue-600 hover:bg-blue-500 text-white text-sm font-semibold px-4 py-2 rounded-lg transition-colors"
                      >
                        View Report
                      </Link>
                    ) : item.status === "in_progress" ? (
                      <Link
                        href={`/candidate/interview/${item.interview_id}`}
                        className="bg-slate-700 hover:bg-slate-600 text-white text-sm font-semibold px-4 py-2 rounded-lg transition-colors"
                      >
                        Continue
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
