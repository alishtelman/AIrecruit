"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAuth } from "@/hooks/useAuth";
import { candidateApi } from "@/lib/api";

interface Stats {
  has_resume: boolean;
  interview_count: number;
  completed_count: number;
  latest_report_id: string | null;
}

export default function DashboardPage() {
  const { user, loading, logout } = useAuth();
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    if (loading) return;
    candidateApi.stats().then(setStats).catch(() => null);
  }, [loading]);

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="text-slate-400">Loading…</div>
      </div>
    );
  }

  const step1Done = stats?.has_resume ?? false;
  const step2Done = (stats?.interview_count ?? 0) > 0;
  const step3Done = (stats?.completed_count ?? 0) > 0;

  return (
    <div className="min-h-screen bg-slate-900">
      {/* Nav */}
      <header className="border-b border-slate-800 px-6 py-4 flex items-center justify-between">
        <span className="text-white font-semibold">AI Recruiting</span>
        <div className="flex items-center gap-4">
          <span className="text-slate-400 text-sm">{user?.email}</span>
          <Link href="/candidate/profile" className="text-slate-400 hover:text-white text-sm transition-colors">
            Profile
          </Link>
          <button onClick={logout} className="text-slate-400 hover:text-white text-sm transition-colors">
            Sign out
          </button>
        </div>
      </header>

      <main className="max-w-2xl mx-auto px-4 py-10">
        <h1 className="text-2xl font-bold text-white mb-1">Welcome back!</h1>
        <p className="text-slate-400 mb-8">Complete each step to get your verified profile.</p>

        {/* Progress summary */}
        {stats && (
          <div className="grid grid-cols-3 gap-3 mb-8">
            <StatBadge label="Resume" done={step1Done} value={step1Done ? "Uploaded" : "Missing"} />
            <StatBadge label="Interviews" done={step2Done} value={`${stats.interview_count} started`} />
            <StatBadge label="Reports" done={step3Done} value={`${stats.completed_count} completed`} />
          </div>
        )}

        <div className="grid gap-4">
          <StepCard
            step={1}
            href="/candidate/resume"
            icon="📄"
            label="Upload Resume"
            desc="Upload your CV (PDF or DOCX) to get started"
            done={step1Done}
          />
          <StepCard
            step={2}
            href="/candidate/interview/start"
            icon="🎯"
            label="Start AI Interview"
            desc="Complete a structured interview for your target role"
            done={step2Done}
            locked={!step1Done}
          />
          <StepCard
            step={3}
            href={stats?.latest_report_id ? `/candidate/reports/${stats.latest_report_id}` : "/candidate/reports"}
            icon="📊"
            label="View Reports"
            desc={step3Done ? `${stats!.completed_count} report${stats!.completed_count !== 1 ? "s" : ""} ready` : "See your assessment scores and hiring recommendation"}
            done={step3Done}
            locked={!step2Done}
          />
        </div>
      </main>
    </div>
  );
}

function StatBadge({ label, done, value }: { label: string; done: boolean; value: string }) {
  return (
    <div className={`rounded-xl p-4 border text-center ${done ? "bg-green-500/10 border-green-500/20" : "bg-slate-800 border-slate-700"}`}>
      <div className={`text-xs font-medium mb-1 ${done ? "text-green-400" : "text-slate-500"}`}>{label}</div>
      <div className={`text-sm font-semibold ${done ? "text-green-300" : "text-slate-400"}`}>{value}</div>
    </div>
  );
}

function StepCard({
  step, href, icon, label, desc, done = false, locked = false,
}: {
  step: number; href: string; icon: string; label: string;
  desc: string; done?: boolean; locked?: boolean;
}) {
  const base = "flex items-center gap-4 border rounded-xl p-5 transition-colors group";
  const style = locked
    ? `${base} border-slate-800 bg-slate-900 opacity-50 cursor-not-allowed pointer-events-none`
    : done
    ? `${base} border-green-500/20 bg-green-500/5 hover:bg-green-500/10`
    : `${base} border-slate-700 bg-slate-800 hover:border-slate-500`;

  return (
    <Link href={locked ? "#" : href} className={style}>
      <div className={`w-10 h-10 rounded-full flex items-center justify-center text-sm font-bold shrink-0 border ${
        done ? "bg-green-500/20 border-green-500/40 text-green-400" : "bg-blue-500/10 border-blue-500/20 text-blue-400"
      }`}>
        {done ? "✓" : step}
      </div>
      <span className="text-2xl">{icon}</span>
      <div className="flex-1">
        <div className={`font-semibold transition-colors ${done ? "text-green-300" : "text-white group-hover:text-blue-400"}`}>{label}</div>
        <div className="text-slate-400 text-sm">{desc}</div>
      </div>
      {!locked && <span className={`text-lg transition-colors ${done ? "text-green-500" : "text-slate-600 group-hover:text-blue-400"}`}>→</span>}
    </Link>
  );
}
