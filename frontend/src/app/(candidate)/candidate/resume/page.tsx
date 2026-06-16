"use client";

import { useState, useRef } from "react";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { useAuth } from "@/hooks/useAuth";
import { resumeApi } from "@/lib/api";
import type { ResumeUploadResponse } from "@/lib/types";
import { CandidateShell } from "@/components/candidate-shell";

export default function ResumePage() {
  const t = useTranslations("candidateResume");
  const common = useTranslations("common");
  const { loading: authLoading } = useAuth({ allowedRoles: ["candidate"] });
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
      setError(err instanceof Error ? err.message : t("uploadFailed"));
    } finally {
      setUploading(false);
    }
  }

  if (authLoading) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="text-slate-400">{common("status.loading")}</div>
      </div>
    );
  }

  return (
    <CandidateShell>
      <div className="max-w-3xl mx-auto py-6">
        {/* Title block */}
        <div className="mb-6">
          <div className="text-xs uppercase tracking-widest text-[#9aa0ab] font-bold">
            {t("kicker") || "Резюме"}
          </div>
          <h1 className="text-[34px] font-bold font-manrope tracking-tight text-[#1A1C22] mt-1.5 leading-none">
            {t("title") || "Загрузить резюме"}
          </h1>
          <p className="max-w-2xl text-[#56596a] text-sm mt-2">{t("subtitle")}</p>
        </div>

        {result && (
          <div className="rounded-2xl border border-green-200 bg-green-50 p-5 mb-6">
            <div className="text-green-600 font-bold mb-1">{t("success")}</div>
            <div className="text-[#1A1C22] text-sm font-semibold">{result.file_name}</div>
            <div className="text-[#56596a] text-xs mt-1 font-medium">
              {t("charactersExtracted", {count: result.text_length.toLocaleString()})}
            </div>
          </div>
        )}

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-600 text-sm rounded-lg px-4 py-3 mb-6 font-semibold">
            {error}
          </div>
        )}

        {/* Upload card container */}
        <div className="candidate-card p-6 space-y-5">
          <div
            onClick={() => inputRef.current?.click()}
            className="rounded-[1.6rem] border-2 border-dashed border-slate-300 bg-slate-50/50 p-10 text-center cursor-pointer transition-colors hover:border-[#2F5BEA]"
          >
            <div className="mb-3 inline-flex rounded-lg border border-slate-200 bg-slate-100 px-3 py-1 text-xs font-bold tracking-[0.2em] text-[#56596a]">{t("fileBadge")}</div>
            <div className="text-[#1A1C22] font-bold mb-1 text-[15.5px]">
              {file ? file.name : t("pickFile")}
            </div>
            <div className="text-[#56596a] text-xs font-medium">
              {file
                ? `${t("selectedFile")}: ${(file.size / 1024).toFixed(0)} KB`
                : t("fileHint")}
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
            className="candidate-btn-primary w-full rounded-xl py-3 text-white font-bold disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {uploading ? t("uploading") : t("upload")}
          </button>
        </div>

        {result && (
          <div className="candidate-card mt-6 p-6">
            <div className="text-[#1A1C22] font-bold mb-1">{t("nextStepTitle")}</div>
            <div className="text-[#56596a] text-sm mb-4 leading-relaxed">{t("nextStepBody")}</div>
            <Link
              href="/candidate/interview/start"
              className="candidate-btn-primary inline-block rounded-xl px-6 py-3 text-white font-bold shadow-[0_4px_12px_rgba(47,91,234,0.3)]"
            >
              {t("startInterview")}
            </Link>
          </div>
        )}
      </div>
    </CandidateShell>
  );
}
