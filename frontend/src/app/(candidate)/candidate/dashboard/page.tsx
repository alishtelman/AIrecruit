"use client";

import Link from "next/link";
import { useAuth } from "@/hooks/useAuth";

export default function DashboardPage() {
  const { user, loading, logout } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="text-slate-400">Loading…</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-900">
      {/* Nav */}
      <header className="border-b border-slate-800 px-6 py-4 flex items-center justify-between">
        <span className="text-white font-semibold">AI Recruiting</span>
        <div className="flex items-center gap-4">
          <span className="text-slate-400 text-sm">{user?.email}</span>
          <button onClick={logout} className="text-slate-400 hover:text-white text-sm transition-colors">
            Sign out
          </button>
        </div>
      </header>

      <main className="max-w-2xl mx-auto px-4 py-10">
        <h1 className="text-2xl font-bold text-white mb-1">Welcome back!</h1>
        <p className="text-slate-400 mb-8">Complete each step to get your verified profile.</p>

        <div className="grid gap-4">
          <StepCard
            step={1}
            href="/candidate/resume"
            icon="📄"
            label="Upload Resume"
            desc="Upload your CV (PDF or DOCX) to get started"
          />
          <StepCard
            step={2}
            href="/candidate/interview/start"
            icon="🎯"
            label="Start AI Interview"
            desc="Complete a structured interview for your target role"
          />
          <StepCard
            step={3}
            href="/candidate/reports"
            icon="📊"
            label="View Reports"
            desc="See your assessment scores and hiring recommendation"
          />
        </div>
      </main>
    </div>
  );
}

function StepCard({
  step,
  href,
  icon,
  label,
  desc,
}: {
  step: number;
  href: string;
  icon: string;
  label: string;
  desc: string;
}) {
  return (
    <Link
      href={href}
      className="flex items-center gap-4 bg-slate-800 hover:bg-slate-750 border border-slate-700 rounded-xl p-5 transition-colors group"
    >
      <div className="w-10 h-10 rounded-full bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400 text-sm font-bold shrink-0">
        {step}
      </div>
      <span className="text-2xl">{icon}</span>
      <div className="flex-1">
        <div className="text-white font-semibold group-hover:text-blue-400 transition-colors">{label}</div>
        <div className="text-slate-400 text-sm">{desc}</div>
      </div>
      <span className="text-slate-600 group-hover:text-blue-400 transition-colors text-lg">→</span>
    </Link>
  );
}
