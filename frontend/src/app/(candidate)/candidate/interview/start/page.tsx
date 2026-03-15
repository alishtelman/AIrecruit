"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import { interviewApi } from "@/lib/api";
import type { TargetRole } from "@/lib/types";

const ROLES: { value: TargetRole; label: string; desc: string }[] = [
  {
    value: "backend_engineer",
    label: "Backend Engineer",
    desc: "System design, databases, APIs, performance",
  },
  {
    value: "qa_engineer",
    label: "QA Engineer",
    desc: "Test strategy, automation, quality processes",
  },
  {
    value: "product_manager",
    label: "Product Manager",
    desc: "Roadmap, stakeholders, metrics, delivery",
  },
];

export default function StartInterviewPage() {
  const router = useRouter();
  const { loading: authLoading } = useAuth();
  const [selected, setSelected] = useState<TargetRole | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");

  async function handleStart() {
    if (!selected) return;
    setError("");
    setStarting(true);
    try {
      const res = await interviewApi.start({ target_role: selected });
      router.push(`/candidate/interview/${res.interview_id}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not start interview");
      setStarting(false);
    }
  }

  if (authLoading) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="text-slate-400">Loading…</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-900 px-4 py-10">
      <div className="max-w-lg mx-auto">
        <Link href="/candidate/dashboard" className="text-slate-400 hover:text-white text-sm mb-6 inline-block">
          ← Back to dashboard
        </Link>

        <h1 className="text-2xl font-bold text-white mb-2">Start AI Interview</h1>
        <p className="text-slate-400 mb-8">
          Choose your target role. You'll answer 8 questions. The interview takes 15–20 minutes.
        </p>

        {error && (
          <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg px-4 py-3 mb-6">
            {error}
          </div>
        )}

        <div className="space-y-3 mb-8">
          {ROLES.map((role) => (
            <button
              key={role.value}
              onClick={() => setSelected(role.value)}
              className={`w-full text-left p-5 rounded-xl border transition-all ${
                selected === role.value
                  ? "border-blue-500 bg-blue-500/10"
                  : "border-slate-700 bg-slate-800 hover:border-slate-600"
              }`}
            >
              <div className={`font-semibold mb-1 ${selected === role.value ? "text-blue-300" : "text-white"}`}>
                {role.label}
              </div>
              <div className="text-slate-400 text-sm">{role.desc}</div>
            </button>
          ))}
        </div>

        <button
          onClick={handleStart}
          disabled={!selected || starting}
          className="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold py-3 rounded-lg transition-colors"
        >
          {starting ? "Starting…" : "Start Interview"}
        </button>
      </div>
    </div>
  );
}
