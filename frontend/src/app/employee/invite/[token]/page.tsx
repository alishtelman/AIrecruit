"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { getToken } from "@/lib/auth";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";

interface InviteInfo {
  employee_name: string;
  employee_email: string;
  target_role: string;
  role_label: string;
  status: string;
  company_name: string;
}

export default function EmployeeInvitePage() {
  const { token } = useParams<{ token: string }>();
  const router = useRouter();
  const [info, setInfo] = useState<InviteInfo | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [language, setLanguage] = useState<"ru" | "en">("ru");

  useEffect(() => {
    fetch(`${BASE_URL}/api/v1/employee/invite/${token}`)
      .then((r) => {
        if (!r.ok) throw new Error("Invite not found or expired");
        return r.json();
      })
      .then(setInfo)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [token]);

  async function handleStart() {
    const authToken = getToken();
    if (!authToken) {
      // Save token in sessionStorage so we return here after login
      sessionStorage.setItem("employee_invite_token", token);
      router.push(`/candidate/login?redirect=/employee/invite/${token}`);
      return;
    }

    setStarting(true);
    setError("");
    try {
      const res = await fetch(`${BASE_URL}/api/v1/employee/invite/${token}/start`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${authToken}`,
        },
        body: JSON.stringify({ language }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail ?? "Failed to start");
      }
      const { interview_id } = await res.json();
      router.push(`/candidate/interview/${interview_id}`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to start assessment");
      setStarting(false);
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="text-slate-400">Loading invite…</div>
      </div>
    );
  }

  if (error && !info) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center px-4">
        <div className="text-center">
          <div className="text-4xl mb-4">⚠️</div>
          <h1 className="text-xl font-bold text-white mb-2">Invite Not Found</h1>
          <p className="text-slate-400 text-sm">{error}</p>
        </div>
      </div>
    );
  }

  if (!info) return null;

  const isCompleted = info.status === "completed";

  return (
    <div className="min-h-screen bg-slate-900 flex items-center justify-center px-4">
      <div className="w-full max-w-lg">
        <div className="text-center mb-8">
          <div className="text-5xl mb-4">🎯</div>
          <h1 className="text-2xl font-bold text-white">Employee Assessment</h1>
          <p className="text-slate-400 mt-2 text-sm">
            {info.company_name} has invited you to complete an AI interview
          </p>
        </div>

        <div className="bg-slate-800 border border-slate-700 rounded-xl p-6 mb-6">
          <div className="space-y-3">
            <div className="flex justify-between text-sm">
              <span className="text-slate-400">Your name</span>
              <span className="text-white font-medium">{info.employee_name}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-slate-400">Email</span>
              <span className="text-white">{info.employee_email}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-slate-400">Role</span>
              <span className="text-white font-medium">{info.role_label}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-slate-400">Company</span>
              <span className="text-white">{info.company_name}</span>
            </div>
          </div>
        </div>

        {isCompleted ? (
          <div className="bg-green-500/10 border border-green-500/30 rounded-xl p-5 text-center">
            <div className="text-green-400 font-semibold text-lg mb-1">Assessment Complete</div>
            <p className="text-slate-400 text-sm">
              You have already completed this assessment. Your results have been shared with {info.company_name}.
            </p>
          </div>
        ) : (
          <>
            <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 mb-5">
              <p className="text-slate-300 text-sm leading-relaxed">
                You will answer <span className="text-white font-semibold">8 questions</span> asked by an AI interviewer.
                The interview takes approximately 15–20 minutes. Your answers will be assessed and the report
                shared with <span className="text-white font-semibold">{info.company_name}</span>.
              </p>
            </div>

            {error && (
              <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg px-4 py-3 mb-4">
                {error}
              </div>
            )}

            <div className="mb-5">
              <p className="text-slate-400 text-sm mb-2">Interview language:</p>
              <div className="flex gap-2">
                <button
                  onClick={() => setLanguage("ru")}
                  className={`flex-1 py-2 rounded-lg border text-sm font-medium transition-colors ${
                    language === "ru"
                      ? "bg-blue-500/15 border-blue-500/40 text-blue-400"
                      : "bg-slate-800 border-slate-700 text-slate-400 hover:border-slate-600"
                  }`}
                >
                  🇷🇺 Русский
                </button>
                <button
                  onClick={() => setLanguage("en")}
                  className={`flex-1 py-2 rounded-lg border text-sm font-medium transition-colors ${
                    language === "en"
                      ? "bg-blue-500/15 border-blue-500/40 text-blue-400"
                      : "bg-slate-800 border-slate-700 text-slate-400 hover:border-slate-600"
                  }`}
                >
                  🇬🇧 English
                </button>
              </div>
            </div>

            <button
              onClick={handleStart}
              disabled={starting}
              className="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white font-semibold py-3 rounded-lg transition-colors"
            >
              {starting ? "Starting…" : getToken() ? "Start Assessment" : "Sign In & Start"}
            </button>

            {!getToken() && (
              <p className="text-slate-500 text-xs text-center mt-3">
                You need a candidate account to take the assessment.{" "}
                <a href={`/candidate/register?redirect=/employee/invite/${token}`} className="text-blue-400 hover:underline">
                  Register here
                </a>
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
