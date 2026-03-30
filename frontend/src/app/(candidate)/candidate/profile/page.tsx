"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { useAuth } from "@/hooks/useAuth";
import { candidateApi, resumeApi } from "@/lib/api";
import type { ActiveResume } from "@/lib/types";

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function ProfilePage() {
  const t = useTranslations("candidateProfile");
  const common = useTranslations("common");
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
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="text-slate-400">{common("status.loading")}</div>
      </div>
    );
  }

  return (
    <div className="ai-shell min-h-screen px-4 py-10">
      <div className="ai-section max-w-3xl mx-auto">
        <Link
          href="/candidate/dashboard"
          className="text-slate-400 hover:text-white text-sm mb-6 inline-block transition-colors"
        >
          ← {t("back")}
        </Link>

        <div className="ai-panel-strong rounded-[2rem] p-7 mb-6">
          <div className="ai-kicker mb-5">{t("kicker")}</div>
          <h1 className="text-3xl font-semibold tracking-[-0.03em] text-white mb-2">{t("title")}</h1>
          <p className="max-w-2xl text-slate-400">{t("subtitle")}</p>
        </div>

        <section className="ai-panel rounded-[1.8rem] p-6 mb-4">
          <h2 className="text-white font-semibold mb-4">{t("account")}</h2>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-slate-400">{t("email")}</span>
              <span className="text-white">{user?.email}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">{t("role")}</span>
              <span className="text-white capitalize">{t("candidate")}</span>
            </div>
          </div>
        </section>

        <section className="ai-panel rounded-[1.8rem] p-6">
          <h2 className="text-white font-semibold mb-4">{t("activeResume")}</h2>
          <p className="text-slate-400 text-sm mb-4">{t("resumeCardHint")}</p>

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
                  {formatBytes(resume.file_size)} · {t("uploaded")}{" "}
                  {new Date(resume.uploaded_at).toLocaleDateString()}
                </div>
              </div>
              <span className="text-xs px-2 py-0.5 rounded-full bg-green-500/10 border border-green-500/20 text-green-400">
                {t("active")}
              </span>
            </div>
          ) : (
            <p className="text-slate-400 text-sm mb-5">{t("noResume")}</p>
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
            className="ai-button-primary w-full rounded-xl py-2.5 text-white font-semibold disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {uploading ? t("uploading") : resume ? t("replaceResume") : t("uploadResume")}
          </button>
          <div className="mt-3 flex items-center justify-between gap-3">
            <p className="text-slate-500 text-xs">{t("fileHint")}</p>
            <Link href="/candidate/resume" className="text-sm text-blue-300 transition-colors hover:text-blue-200">
              {t("manageResume")}
            </Link>
          </div>
        </section>
      </div>
    </div>
  );
}
