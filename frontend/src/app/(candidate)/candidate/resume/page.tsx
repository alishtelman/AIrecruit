"use client";

import { useState, useRef } from "react";
import Link from "next/link";
import { useAuth } from "@/hooks/useAuth";
import { resumeApi } from "@/lib/api";
import type { ResumeUploadResponse } from "@/lib/types";

export default function ResumePage() {
  const { loading: authLoading } = useAuth();
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<ResumeUploadResponse | null>(null);
  const [error, setError] = useState("");

  async function handleUpload() {
    if (!file) return;
    setError("");
    setUploading(true);
    try {
      const res = await resumeApi.upload(file);
      setResult(res);
      setFile(null);
      if (inputRef.current) inputRef.current.value = "";
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
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

        <h1 className="text-2xl font-bold text-white mb-2">Upload Resume</h1>
        <p className="text-slate-400 mb-8">PDF or DOCX, max 10 MB. Your active resume is used for AI interviews.</p>

        {result && (
          <div className="bg-green-500/10 border border-green-500/30 rounded-xl p-5 mb-6">
            <div className="text-green-400 font-semibold mb-1">✓ Resume uploaded successfully</div>
            <div className="text-slate-300 text-sm">{result.file_name}</div>
            <div className="text-slate-400 text-sm">{result.text_length.toLocaleString()} characters extracted</div>
          </div>
        )}

        {error && (
          <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg px-4 py-3 mb-6">
            {error}
          </div>
        )}

        <div className="bg-slate-800 border border-slate-700 rounded-xl p-6 space-y-5">
          <div
            onClick={() => inputRef.current?.click()}
            className="border-2 border-dashed border-slate-600 hover:border-blue-500 rounded-lg p-10 text-center cursor-pointer transition-colors"
          >
            <div className="text-3xl mb-3">📎</div>
            <div className="text-white font-medium mb-1">
              {file ? file.name : "Click to select file"}
            </div>
            <div className="text-slate-400 text-sm">
              {file
                ? `${(file.size / 1024).toFixed(0)} KB`
                : "PDF or DOCX · max 10 MB"}
            </div>
            <input
              ref={inputRef}
              type="file"
              accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
              className="hidden"
              onChange={(e) => {
                setResult(null);
                setError("");
                setFile(e.target.files?.[0] ?? null);
              }}
            />
          </div>

          <button
            onClick={handleUpload}
            disabled={!file || uploading}
            className="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold py-2.5 rounded-lg transition-colors"
          >
            {uploading ? "Uploading…" : "Upload Resume"}
          </button>
        </div>

        {result && (
          <div className="mt-6 text-center">
            <Link
              href="/candidate/interview/start"
              className="inline-block bg-blue-600 hover:bg-blue-500 text-white font-semibold px-6 py-2.5 rounded-lg transition-colors"
            >
              Start Interview →
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}
