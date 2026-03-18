"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAuth } from "@/hooks/useAuth";
import { candidateApi } from "@/lib/api";
import type { CandidatePrivacy, ProfileVisibility } from "@/lib/types";

interface Stats {
  has_resume: boolean;
  interview_count: number;
  completed_count: number;
  latest_report_id: string | null;
}

interface Salary {
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string;
}

const VISIBILITY_HELP: Record<ProfileVisibility, { title: string; body: string }> = {
  private: {
    title: "Private",
    body: "Your profile stays hidden from marketplace companies and direct links.",
  },
  marketplace: {
    title: "Marketplace",
    body: "Companies can discover your profile, reports, and salary expectations in the public talent database.",
  },
  direct_link: {
    title: "Direct Link",
    body: "Your profile is hidden from marketplace search, but anyone with your link can open the shared profile.",
  },
  request_only: {
    title: "Request Only",
    body: "Your profile is hidden from marketplace search. Company approval flows will build on this mode later.",
  },
};

export default function DashboardPage() {
  const { user, loading, logout } = useAuth();
  const [stats, setStats] = useState<Stats | null>(null);
  const [salary, setSalary] = useState<Salary>({ salary_min: null, salary_max: null, salary_currency: "USD" });
  const [salaryMin, setSalaryMin] = useState("");
  const [salaryMax, setSalaryMax] = useState("");
  const [salaryCurrency, setSalaryCurrency] = useState("USD");
  const [savingSalary, setSavingSalary] = useState(false);
  const [salarySaved, setSalarySaved] = useState(false);
  const [privacy, setPrivacy] = useState<CandidatePrivacy>({ visibility: "marketplace", share_token: null });
  const [savingPrivacy, setSavingPrivacy] = useState(false);
  const [privacySaved, setPrivacySaved] = useState(false);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");

  useEffect(() => {
    if (loading) return;
    candidateApi.stats().then(setStats).catch(() => null);
    candidateApi.getSalary().then((s) => {
      setSalary(s);
      setSalaryMin(s.salary_min?.toString() ?? "");
      setSalaryMax(s.salary_max?.toString() ?? "");
      setSalaryCurrency(s.salary_currency ?? "USD");
    }).catch(() => null);
    candidateApi.getPrivacy().then(setPrivacy).catch(() => null);
  }, [loading]);

  async function handleSaveSalary() {
    setSavingSalary(true);
    try {
      const updated = await candidateApi.updateSalary({
        salary_min: salaryMin ? parseInt(salaryMin) : null,
        salary_max: salaryMax ? parseInt(salaryMax) : null,
        currency: salaryCurrency,
      });
      setSalary(updated);
      setSalarySaved(true);
      setTimeout(() => setSalarySaved(false), 2000);
    } catch {
      // ignore
    } finally {
      setSavingSalary(false);
    }
  }

  async function handleSavePrivacy() {
    setSavingPrivacy(true);
    try {
      const updated = await candidateApi.updatePrivacy(privacy.visibility);
      setPrivacy(updated);
      setPrivacySaved(true);
      setTimeout(() => setPrivacySaved(false), 2000);
    } catch {
      // ignore
    } finally {
      setSavingPrivacy(false);
    }
  }

  async function handleCopyShareLink() {
    if (!privacy.share_token || typeof window === "undefined") return;
    try {
      await navigator.clipboard.writeText(`${window.location.origin}/candidate/share/${privacy.share_token}`);
      setCopyState("copied");
      setTimeout(() => setCopyState("idle"), 2000);
    } catch {
      setCopyState("failed");
      setTimeout(() => setCopyState("idle"), 2000);
    }
  }

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

        {/* Salary Expectations */}
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 mb-6">
          <h2 className="text-white font-semibold mb-3 text-sm">💰 Salary Expectations</h2>
          <div className="flex flex-wrap gap-3 items-end">
            <div>
              <label className="text-slate-400 text-xs mb-1 block">Min</label>
              <input
                type="number"
                placeholder="e.g. 80000"
                value={salaryMin}
                onChange={(e) => setSalaryMin(e.target.value)}
                className="w-32 bg-slate-700 border border-slate-600 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label className="text-slate-400 text-xs mb-1 block">Max</label>
              <input
                type="number"
                placeholder="e.g. 120000"
                value={salaryMax}
                onChange={(e) => setSalaryMax(e.target.value)}
                className="w-32 bg-slate-700 border border-slate-600 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label className="text-slate-400 text-xs mb-1 block">Currency</label>
              <select
                value={salaryCurrency}
                onChange={(e) => setSalaryCurrency(e.target.value)}
                className="bg-slate-700 border border-slate-600 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500"
              >
                {["USD", "EUR", "GBP", "RUB", "KZT"].map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </div>
            <button
              onClick={handleSaveSalary}
              disabled={savingSalary}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-sm rounded-lg transition-colors"
            >
              {salarySaved ? "Saved ✓" : savingSalary ? "Saving…" : "Save"}
            </button>
          </div>
        </div>

        <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 mb-6">
          <h2 className="text-white font-semibold mb-3 text-sm">🔐 Profile Visibility</h2>
          <div className="flex flex-wrap gap-3 items-end">
            <div className="min-w-[220px]">
              <label className="text-slate-400 text-xs mb-1 block">Visibility</label>
              <select
                value={privacy.visibility}
                onChange={(e) => setPrivacy((current) => ({ ...current, visibility: e.target.value as ProfileVisibility }))}
                className="w-full bg-slate-700 border border-slate-600 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500"
              >
                <option value="marketplace">Marketplace</option>
                <option value="direct_link">Direct Link</option>
                <option value="request_only">Request Only</option>
                <option value="private">Private</option>
              </select>
            </div>
            <button
              onClick={handleSavePrivacy}
              disabled={savingPrivacy}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-sm rounded-lg transition-colors"
            >
              {privacySaved ? "Saved ✓" : savingPrivacy ? "Saving…" : "Save"}
            </button>
          </div>
          <div className="mt-3 rounded-lg border border-slate-700 bg-slate-900 px-4 py-3">
            <p className="text-white text-sm font-medium">{VISIBILITY_HELP[privacy.visibility].title}</p>
            <p className="text-slate-400 text-sm mt-1">{VISIBILITY_HELP[privacy.visibility].body}</p>
          </div>
          {privacy.visibility === "direct_link" && privacy.share_token && (
            <div className="mt-3 rounded-lg border border-blue-500/20 bg-blue-500/5 px-4 py-3">
              <p className="text-blue-300 text-sm font-medium mb-1">Shareable profile link</p>
              <p className="text-slate-300 text-sm break-all">/candidate/share/{privacy.share_token}</p>
              <div className="mt-3 flex flex-wrap gap-3">
                <button
                  onClick={handleCopyShareLink}
                  className="px-3 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded-lg transition-colors"
                >
                  {copyState === "copied" ? "Copied ✓" : copyState === "failed" ? "Copy failed" : "Copy full link"}
                </button>
                <Link
                  href={`/candidate/share/${privacy.share_token}`}
                  target="_blank"
                  className="px-3 py-2 border border-slate-600 text-slate-200 hover:text-white hover:border-slate-500 text-sm rounded-lg transition-colors"
                >
                  Open shared profile
                </Link>
              </div>
            </div>
          )}
        </div>

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
