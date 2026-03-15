"use client";

import Link from "next/link";
import { useAuth } from "@/hooks/useAuth";

export default function ReportsPage() {
  const { loading } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="text-slate-400">Loading…</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-900 px-4 py-10">
      <div className="max-w-2xl mx-auto">
        <Link href="/candidate/dashboard" className="text-slate-400 hover:text-white text-sm mb-6 inline-block">
          ← Back to dashboard
        </Link>
        <h1 className="text-2xl font-bold text-white mb-2">My Reports</h1>
        <p className="text-slate-400 mb-8">
          After finishing an interview you&apos;ll be redirected here automatically.
        </p>
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-12 text-center">
          <div className="text-4xl mb-4">📊</div>
          <h2 className="text-white font-semibold text-lg mb-2">No reports yet</h2>
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
      </div>
    </div>
  );
}
