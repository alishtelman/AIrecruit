"use client";

import { useState, useRef } from "react";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { useAuth } from "@/hooks/useAuth";
import { resumeApi } from "@/lib/api";
import type { ResumeUploadResponse } from "@/lib/types";

export default function ResumePage() {
  const t = useTranslations("candidateResume");
  const common = useTranslations("common");
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
    <div className="ai-shell min-h-screen px-4 py-10">
      <div className="ai-section max-w-3xl mx-auto">
        <Link href="/candidate/dashboard" className="text-slate-400 hover:text-white text-sm mb-6 inline-block">
          ← {t("back")}
        </Link>

        <div className="ai-panel-strong rounded-[2rem] p-7 mb-6">
          <div className="ai-kicker mb-5">{t("kicker")}</div>
          <h1 className="text-3xl font-semibold tracking-[-0.03em] text-white mb-2">{t("title")}</h1>
          <p className="max-w-2xl text-slate-400">{t("subtitle")}</p>
        </div>

        {result && (
          <div className="rounded-[1.6rem] border border-green-500/30 bg-green-500/10 p-5 mb-6">
            <div className="text-green-400 font-semibold mb-1">{t("success")}</div>
            <div className="text-slate-300 text-sm">{result.file_name}</div>
            <div className="text-slate-400 text-sm">{t("charactersExtracted", {count: result.text_length.toLocaleString()})}</div>
          </div>
        )}

        {error && (
          <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg px-4 py-3 mb-6">
            {error}
          </div>
        )}

        <div className="ai-panel rounded-[1.8rem] p-6 space-y-5">
          <div
            onClick={() => inputRef.current?.click()}
            className="rounded-[1.6rem] border-2 border-dashed border-slate-600 p-10 text-center cursor-pointer transition-colors hover:border-blue-500"
          >
            <div className="mb-3 inline-flex rounded-lg border border-slate-700 bg-slate-900 px-3 py-1 text-xs font-semibold tracking-[0.2em] text-slate-300">{t("fileBadge")}</div>
            <div className="text-white font-medium mb-1">
              {file ? file.name : t("pickFile")}
            </div>
            <div className="text-slate-400 text-sm">
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
            className="ai-button-primary w-full rounded-xl py-2.5 text-white font-semibold disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {uploading ? t("uploading") : t("upload")}
          </button>
        </div>

        {result && (
          <div className="ai-panel rounded-[1.8rem] mt-6 p-6">
            <div className="text-white font-semibold mb-1">{t("nextStepTitle")}</div>
            <div className="text-slate-400 text-sm mb-4">{t("nextStepBody")}</div>
            <Link
              href="/candidate/interview/start"
              className="ai-button-primary inline-block rounded-xl px-6 py-2.5 text-white font-semibold"
            >
              {t("startInterview")}
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}
