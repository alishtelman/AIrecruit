"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/hooks/useAuth";
import { candidateApi, resumeApi } from "@/lib/api";
import type { ActiveResume } from "@/lib/types";

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function ProfilePage() {
  const { user, loading: authLoading } = useAuth();
  const [resume, setResume] = useState<ActiveResume | null>(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (authLoading) return;
    candidateApi
      .getResume()
      .then(setResume)
      .catch(() => null)
      .finally(() => setLoading(false));
  }, [authLoading]);

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setError("");
    setSuccess("");
    setUploading(true);
    try {
      await resumeApi.upload(file);
      const updated = await candidateApi.getResume();
      setResume(updated);
      setSuccess("Resume updated successfully.");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  if (authLoading || loading) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="text-slate-400">Loading…</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-900 px-4 py-10">
      <div className="max-w-xl mx-auto">
        <Link
          href="/candidate/dashboard"
          className="text-slate-400 hover:text-white text-sm mb-6 inline-block transition-colors"
        >
          ← Back to dashboard
        </Link>

        <h1 className="text-2xl font-bold text-white mb-1">My Profile</h1>
        <p className="text-slate-400 mb-8">Manage your account and resume.</p>

        {/* Account info */}
        <section className="bg-slate-800 border border-slate-700 rounded-xl p-6 mb-4">
          <h2 className="text-white font-semibold mb-4">Account</h2>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-slate-400">Email</span>
              <span className="text-white">{user?.email}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">Role</span>
              <span className="text-white capitalize">Candidate</span>
            </div>
          </div>
        </section>

        {/* Resume */}
        <section className="bg-slate-800 border border-slate-700 rounded-xl p-6">
          <h2 className="text-white font-semibold mb-4">Active Resume</h2>

          {error && (
            <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg px-4 py-3 mb-4">
              {error}
            </div>
          )}
          {success && (
            <div className="bg-green-500/10 border border-green-500/30 text-green-400 text-sm rounded-lg px-4 py-3 mb-4">
              {success}
            </div>
          )}

          {resume ? (
            <div className="flex items-center justify-between gap-4 mb-5">
              <div>
                <div className="text-white font-medium">{resume.file_name}</div>
                <div className="text-slate-400 text-sm mt-0.5">
                  {formatBytes(resume.file_size)} · Uploaded{" "}
                  {new Date(resume.uploaded_at).toLocaleDateString()}
                </div>
              </div>
              <span className="text-xs px-2 py-0.5 rounded-full bg-green-500/10 border border-green-500/20 text-green-400">
                Active
              </span>
            </div>
          ) : (
            <p className="text-slate-400 text-sm mb-5">No resume uploaded yet.</p>
          )}

          <input
            ref={fileRef}
            type="file"
            accept=".pdf,.docx"
            className="hidden"
            onChange={handleUpload}
          />
          <button
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
            className="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold py-2.5 rounded-lg transition-colors"
          >
            {uploading ? "Uploading…" : resume ? "Replace Resume" : "Upload Resume"}
          </button>
          <p className="text-slate-500 text-xs text-center mt-2">PDF or DOCX, max 10 MB</p>
        </section>
      </div>
    </div>
  );
}
