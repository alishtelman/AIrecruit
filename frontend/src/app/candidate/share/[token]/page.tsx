"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { candidateApi } from "@/lib/api";
import type { SharedCandidateProfile } from "@/lib/types";

function formatSalary(profile: SharedCandidateProfile): string {
  if (profile.salary_min == null && profile.salary_max == null) {
    return "Not shared";
  }
  const low = profile.salary_min ?? profile.salary_max;
  const high = profile.salary_max ?? profile.salary_min;
  if (low == null || high == null) {
    return "Not shared";
  }
  return low === high
    ? `${low.toLocaleString()} ${profile.salary_currency}`
    : `${low.toLocaleString()}–${high.toLocaleString()} ${profile.salary_currency}`;
}

export default function SharedCandidatePage() {
  const params = useParams<{ token: string }>();
  const [profile, setProfile] = useState<SharedCandidateProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = Array.isArray(params.token) ? params.token[0] : params.token;
    if (!token) return;

    candidateApi.getSharedProfile(token)
      .then((data) => {
        setProfile(data);
        setError(null);
      })
      .catch((err: Error) => {
        setError(err.message || "Shared profile not found.");
      })
      .finally(() => setLoading(false));
  }, [params.token]);

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <p className="text-slate-400">Loading shared profile…</p>
      </div>
    );
  }

  if (error || !profile) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center px-4">
        <div className="max-w-lg rounded-2xl border border-slate-800 bg-slate-900 p-8 text-center">
          <p className="text-red-300 font-semibold mb-2">Link unavailable</p>
          <p className="text-slate-400 text-sm">{error ?? "This shared profile is no longer available."}</p>
          <Link href="/" className="inline-block mt-6 text-blue-400 hover:text-blue-300 text-sm">
            Return to home
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950 text-white">
      <div className="max-w-5xl mx-auto px-4 py-12">
        <div className="rounded-3xl border border-slate-800 bg-gradient-to-br from-slate-900 via-slate-900 to-blue-950/40 p-8 mb-8">
          <p className="text-blue-300 text-sm uppercase tracking-[0.2em] mb-3">Shared Candidate Profile</p>
          <h1 className="text-4xl font-bold mb-3">{profile.full_name}</h1>
          <p className="text-slate-300 max-w-2xl">
            Structured interview results shared directly by the candidate. Marketplace discovery is disabled for this profile.
          </p>
          <div className="mt-6 inline-flex items-center rounded-full border border-slate-700 bg-slate-900/80 px-4 py-2 text-sm text-slate-300">
            Salary expectation: {formatSalary(profile)}
          </div>
        </div>

        <div className="space-y-5">
          {profile.reports.length === 0 ? (
            <div className="rounded-2xl border border-slate-800 bg-slate-900 p-6">
              <p className="text-slate-400">No public interview reports are attached to this shared profile yet.</p>
            </div>
          ) : (
            profile.reports.map((report) => (
              <div key={report.report_id} className="rounded-2xl border border-slate-800 bg-slate-900 p-6">
                <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                  <div>
                    <p className="text-sm text-blue-300 mb-1">{report.target_role.replaceAll("_", " ")}</p>
                    <h2 className="text-2xl font-semibold">{report.overall_score != null ? `${report.overall_score.toFixed(1)}/10 overall` : "Assessment Report"}</h2>
                    <p className="text-slate-400 text-sm mt-2">{report.interview_summary ?? "No summary provided."}</p>
                  </div>
                  <div className="rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 min-w-[180px]">
                    <p className="text-slate-500 text-xs uppercase tracking-wide mb-1">Recommendation</p>
                    <p className="text-white font-medium">{report.hiring_recommendation.replaceAll("_", " ")}</p>
                  </div>
                </div>

                {report.skill_tags && report.skill_tags.length > 0 && (
                  <div className="mt-5">
                    <p className="text-slate-500 text-xs uppercase tracking-wide mb-2">Key Skills</p>
                    <div className="flex flex-wrap gap-2">
                      {report.skill_tags.slice(0, 8).map((tag) => (
                        <span key={`${report.report_id}-${tag.skill}`} className="rounded-full border border-blue-500/20 bg-blue-500/10 px-3 py-1 text-sm text-blue-200">
                          {tag.skill}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                <div className="grid gap-4 md:grid-cols-2 mt-5">
                  <div>
                    <p className="text-slate-500 text-xs uppercase tracking-wide mb-2">Strengths</p>
                    <ul className="space-y-2 text-sm text-slate-300">
                      {report.strengths.length === 0 ? <li>No strengths shared.</li> : report.strengths.map((item) => <li key={item}>• {item}</li>)}
                    </ul>
                  </div>
                  <div>
                    <p className="text-slate-500 text-xs uppercase tracking-wide mb-2">Recommendations</p>
                    <ul className="space-y-2 text-sm text-slate-300">
                      {report.recommendations.length === 0 ? <li>No recommendations shared.</li> : report.recommendations.map((item) => <li key={item}>• {item}</li>)}
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
