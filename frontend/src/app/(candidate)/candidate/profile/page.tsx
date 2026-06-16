"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { useAuth } from "@/hooks/useAuth";
import { candidateApi, resumeApi } from "@/lib/api";
import type { ActiveResume } from "@/lib/types";
import { CandidateShell } from "@/components/candidate-shell";

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function ProfilePage() {
  const t = useTranslations("candidateProfile");
  const common = useTranslations("common");
  const { user, loading: authLoading } = useAuth({ allowedRoles: ["candidate"] });
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
      setSuccess(t("updated"));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("uploadFailed"));
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  if (authLoading || loading) {
    return (
      <div className="min-h-screen bg-[#F4F5F7] flex items-center justify-center">
        <div className="text-[#56596a]">{common("status.loading")}</div>
      </div>
    );
  }

  return (
    <CandidateShell>
      <div className="max-w-3xl mx-auto py-6">
        {/* Title area */}
        <div className="mb-6">
          <div className="text-xs uppercase tracking-widest text-[#9aa0ab] font-bold">
            {t("kicker") || "Профиль"}
          </div>
          <h1 className="text-[34px] font-bold font-manrope tracking-tight text-[#1A1C22] mt-1.5 leading-none">
            {t("title") || "Мой профиль"}
          </h1>
          <p className="max-w-2xl text-[#56596a] text-sm mt-2">{t("subtitle")}</p>
        </div>

        {/* Account Details Card */}
        <section className="candidate-card p-6 mb-6">
          <h2 className="text-[#1A1C22] font-bold mb-4 text-[16px]">{t("account")}</h2>
          <div className="space-y-3 text-sm">
            <div className="flex justify-between items-center py-2 border-b border-slate-100">
              <span className="text-[#56596a] font-medium">{t("email")}</span>
              <span className="text-[#1A1C22] font-semibold">{user?.email}</span>
            </div>
            <div className="flex justify-between items-center py-2">
              <span className="text-[#56596a] font-medium">{t("role")}</span>
              <span className="text-[#1A1C22] font-semibold capitalize">{t("candidate")}</span>
            </div>
          </div>
        </section>

        {/* Active Resume Card */}
        <section className="candidate-card p-6">
          <h2 className="text-[#1A1C22] font-bold text-[16px] mb-2">{t("activeResume")}</h2>
          <p className="text-[#56596a] text-xs mb-5">{t("resumeCardHint")}</p>

          {error && (
            <div className="bg-red-50 border border-red-200 text-red-600 text-sm rounded-lg px-4 py-3 mb-4 font-semibold">
              {error}
            </div>
          )}
          {success && (
            <div className="bg-[#ECF0FE] border border-[#D6E0FD] text-[#2348C8] text-sm rounded-lg px-4 py-3 mb-4 font-semibold">
              {success}
            </div>
          )}

          {resume ? (
            <div className="flex items-center justify-between gap-4 mb-6 p-4 rounded-xl bg-slate-50 border border-slate-200">
              <div className="min-w-0">
                <div className="text-[#1A1C22] font-bold truncate">{resume.file_name}</div>
                <div className="text-[#56596a] text-xs mt-1 font-medium">
                  {formatBytes(resume.file_size)} · {t("uploaded")}{" "}
                  {new Date(resume.uploaded_at).toLocaleDateString()}
                </div>
              </div>
              <span className="text-xs px-2.5 py-1 rounded-full bg-[#ECF0FE] border border-[#D6E0FD] text-[#2348C8] font-bold shrink-0">
                {t("active")}
              </span>
            </div>
          ) : (
            <p className="text-[#56596a] text-sm mb-6 italic">{t("noResume")}</p>
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
            className="candidate-btn-primary w-full rounded-xl py-3 text-white font-bold disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {uploading ? t("uploading") : resume ? t("replaceResume") : t("uploadResume")}
          </button>
          <div className="mt-4 flex items-center justify-between gap-3">
            <p className="text-[#56596a] text-xs font-medium">{t("fileHint")}</p>
            <Link href="/candidate/resume" className="text-sm font-semibold text-[#2F5BEA] transition-colors hover:text-[#2348C8]">
              {t("manageResume")}
            </Link>
          </div>
        </section>
      </div>
    </CandidateShell>
  );
}
