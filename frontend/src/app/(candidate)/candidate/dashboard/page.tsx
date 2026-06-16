"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { LocaleSwitcher } from "@/components/locale-switcher";
import { Link } from "@/i18n/navigation";
import { useAuth } from "@/hooks/useAuth";
import { candidateApi } from "@/lib/api";
import type { CandidateAccessRequest, CandidatePrivacy, ProfileVisibility } from "@/lib/types";
import { CandidateShell } from "@/components/candidate-shell";

type ActiveProfileVisibility = Exclude<ProfileVisibility, "private">;

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

export default function DashboardPage() {
  const t = useTranslations("candidateDashboard");
  const common = useTranslations("common");
  const { user, loading, logout } = useAuth({ allowedRoles: ["candidate"] });
  const [stats, setStats] = useState<Stats | null>(null);
  const [salary, setSalary] = useState<Salary>({ salary_min: null, salary_max: null, salary_currency: "USD" });
  const [salaryMin, setSalaryMin] = useState("");
  const [salaryMax, setSalaryMax] = useState("");
  const [salaryCurrency, setSalaryCurrency] = useState("USD");
  const [savingSalary, setSavingSalary] = useState(false);
  const [salarySaved, setSalarySaved] = useState(false);
  const [privacy, setPrivacy] = useState<CandidatePrivacy>({ visibility: "marketplace", share_token: null });
  const [lastActiveVisibility, setLastActiveVisibility] = useState<ActiveProfileVisibility>("marketplace");
  const [savingPrivacy, setSavingPrivacy] = useState(false);
  const [privacySaved, setPrivacySaved] = useState(false);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const [accessRequests, setAccessRequests] = useState<CandidateAccessRequest[]>([]);
  const [accessActionId, setAccessActionId] = useState<string | null>(null);

  useEffect(() => {
    if (loading) return;
    candidateApi.stats().then(setStats).catch(() => null);
    candidateApi.getSalary().then((s) => {
      setSalary(s);
      setSalaryMin(s.salary_min?.toString() ?? "");
      setSalaryMax(s.salary_max?.toString() ?? "");
      setSalaryCurrency(s.salary_currency ?? "USD");
    }).catch(() => null);
    candidateApi.getPrivacy().then((data) => {
      setPrivacy(data);
      if (data.visibility !== "private") {
        setLastActiveVisibility(data.visibility as ActiveProfileVisibility);
      }
    }).catch(() => null);
    candidateApi.listAccessRequests().then(setAccessRequests).catch(() => null);
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
      if (updated.visibility !== "private") {
        setLastActiveVisibility(updated.visibility as ActiveProfileVisibility);
      }
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

  async function handleAccessRequestAction(requestId: string, action: "approve" | "deny") {
    setAccessActionId(requestId);
    try {
      const updated = action === "approve"
        ? await candidateApi.approveAccessRequest(requestId)
        : await candidateApi.denyAccessRequest(requestId);
      setAccessRequests((current) => current.map((item) => (item.request_id === requestId ? updated : item)));
    } catch {
      // ignore
    } finally {
      setAccessActionId(null);
    }
  }

  function handleProfileStatusChange(nextActive: boolean) {
    if (!nextActive && privacy.visibility !== "private") {
      setLastActiveVisibility(privacy.visibility as ActiveProfileVisibility);
    }

    setPrivacy((current) => {
      if (nextActive) {
        if (current.visibility === "private") {
          return { ...current, visibility: lastActiveVisibility };
        }
        return current;
      }
      if (current.visibility === "private") {
        return current;
      }
      return { ...current, visibility: "private" };
    });
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-[#F4F5F7] px-4 py-10">
        <div className="max-w-4xl mx-auto space-y-4">
          <div className="h-7 w-48 bg-slate-200 rounded animate-pulse" />
          <div className="h-4 w-72 bg-slate-200 rounded animate-pulse" />
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-6">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="h-20 bg-slate-200 rounded-xl animate-pulse" />
            ))}
          </div>
          <div className="h-48 bg-slate-200 rounded-xl animate-pulse mt-4" />
        </div>
      </div>
    );
  }

  const step1Done = stats?.has_resume ?? false;
  const step2Done = (stats?.interview_count ?? 0) > 0;
  const step3Done = (stats?.completed_count ?? 0) > 0;
  const isProfileActive = privacy.visibility !== "private";
  const visibilityLabel = t(
    `privacy.${
      privacy.visibility === "direct_link"
        ? "directLink"
        : privacy.visibility === "request_only"
        ? "requestOnly"
        : privacy.visibility
    }`
  );
  const visibilityHelp: Record<ProfileVisibility, { title: string; body: string }> = {
    private: {
      title: t("privacy.help.private.title"),
      body: t("privacy.help.private.body"),
    },
    marketplace: {
      title: t("privacy.help.marketplace.title"),
      body: t("privacy.help.marketplace.body"),
    },
    direct_link: {
      title: t("privacy.help.directLink.title"),
      body: t("privacy.help.directLink.body"),
    },
    request_only: {
      title: t("privacy.help.requestOnly.title"),
      body: t("privacy.help.requestOnly.body"),
    },
  };

  const completedSteps = (step1Done ? 1 : 0) + (step2Done ? 1 : 0) + (step3Done ? 1 : 0);

  return (
    <CandidateShell>
      <div className="max-w-[960px] mx-auto py-6">
        {/* Header and top badge row */}
        <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between mb-8">
          <div>
            <div className="text-xs uppercase tracking-widest text-[#9aa0ab] font-bold">
              {t("workspaceKicker") || "Панель кандидата"}
            </div>
            <h1 className="text-[34px] font-bold font-manrope tracking-tight text-[#1A1C22] mt-1.5 leading-none">
              {t("title") || "С возвращением"}, {user?.full_name?.split(" ")[0] || "Кандидат"}
            </h1>
          </div>
          <div className="bg-white border border-[#E9EAEE] rounded-xl px-4 py-2.5 flex items-center gap-2.5 shadow-[0_1px_2px_rgba(20,22,30,0.04)]">
            <span className={`w-2 h-2 rounded-full ${isProfileActive ? "bg-[#2F5BEA]" : "bg-slate-400"}`}></span>
            <span className="text-sm font-semibold text-[#1A1C22]">
              {isProfileActive ? "Профиль активен" : "Профиль неактивен"}
            </span>
            <span className="text-[#c7cad2]">·</span>
            <span className="text-sm font-medium text-[#56596a]">
              {visibilityLabel}
            </span>
          </div>
        </div>

        {/* Profile completion progress */}
        <div className="candidate-card p-6 mb-4">
          <div className="flex items-center justify-between">
            <span className="font-semibold text-[15px] text-[#1A1C22]">Готовность профиля</span>
            <span className="font-manrope font-bold text-[15px] text-[#2F5BEA]">
              {completedSteps} из 3 шагов
            </span>
          </div>
          <div className="h-2 bg-[#EEF0F3] rounded-full overflow-hidden mt-3">
            <div
              className="h-full bg-[#2F5BEA] rounded-full transition-all duration-500"
              style={{ width: `${(completedSteps / 3) * 100}%` }}
            ></div>
          </div>
        </div>

        {/* Adaptive banner */}
        <div className="rounded-2xl border border-[#D6E0FD] bg-[linear-gradient(135deg,#FFFFFF_0%,#EEF2FF_62%,#EAF8FF_100%)] p-7 mb-6 flex flex-col md:flex-row md:items-center justify-between gap-6 relative overflow-hidden shadow-[0_18px_42px_rgba(47,91,234,0.10)]">
          <div className="absolute bottom-[-60px] right-[-20px] w-[220px] h-[220px] rounded-full bg-gradient-to-tr from-[#2F5BEA]/15 to-transparent pointer-events-none"></div>
          <div className="flex-1 min-w-[240px] relative z-1">
            <div className="text-[11.5px] font-bold tracking-widest text-[#2F5BEA] uppercase">
              {completedSteps === 0 ? "ШАГ 1" : completedSteps === 1 ? "СЛЕДУЮЩИЙ ШАГ" : "ГОТОВО"}
            </div>
            <h2 className="font-manrope font-bold text-2xl text-[#1A1C22] mt-2 mb-1.5">
              {completedSteps === 0
                ? "Загрузите ваше резюме"
                : completedSteps === 1
                ? "Пройдите ИИ-интервью"
                : "Отчёт о навыках"}
            </h2>
            <p className="text-[14.5px] text-[#56596a] leading-relaxed max-w-[480px]">
              {completedSteps === 0
                ? "Для старта оценки и адаптивного подбора вопросов загрузите файл резюме."
                : completedSteps === 1
                ? "Резюме загружено. Пройдите ИИ-интервью под целевую роль, чтобы собрать отчёт."
                : "Вы успешно завершили интервью. Ваш подтверждённый профиль и отчёты готовы к отправке работодателям."}
            </p>
          </div>
          <Link
            href={
              completedSteps === 0
                ? "/candidate/resume"
                : completedSteps === 1
                ? "/candidate/interview/start"
                : "/candidate/reports"
            }
            className="relative z-1 candidate-btn-primary px-7 py-3.5 text-[15px] font-bold rounded-xl shadow-[0_8px_20px_rgba(47,91,234,0.4)] whitespace-nowrap"
          >
            {completedSteps === 0
              ? "Загрузить резюме"
              : completedSteps === 1
              ? "Начать интервью →"
              : "Посмотреть отчёты"}
          </Link>
        </div>

        {/* Steps checklists */}
        <div className="flex flex-col gap-3 mb-8">
          <Link
            href="/candidate/resume"
            className="flex items-center gap-4 border rounded-2xl p-5 bg-white transition-all hover:border-slate-300 shadow-[0_1px_2px_rgba(20,22,30,0.04)]"
          >
            <div className={`w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold shrink-0 ${
              step1Done
                ? "bg-[#ECF0FE] text-[#2348C8] border border-[#D6E0FD]"
                : "bg-[#2F5BEA]/10 text-[#2F5BEA] border border-[#2F5BEA]/20"
            }`}>
              {step1Done ? "✓" : "1"}
            </div>
            <div className="flex-1">
              <div className="font-bold text-[#1A1C22] text-[15.5px]">
                {t("steps.uploadResume") || "Загрузить резюме"}
              </div>
              <div className="text-[#56596a] text-sm mt-0.5">
                {step1Done ? "Резюме успешно загружено и проанализировано" : t("steps.uploadResumeDesc")}
              </div>
            </div>
            <span className={`text-sm font-bold ${step1Done ? "text-[#2348C8]" : "text-[#2F5BEA]"}`}>
              {step1Done ? "Готово" : "Начать →"}
            </span>
          </Link>

          <Link
            href={step1Done ? "/candidate/interview/start" : "#"}
            className={`flex items-center gap-4 border rounded-2xl p-5 bg-white transition-all shadow-[0_1px_2px_rgba(20,22,30,0.04)] ${
              !step1Done
                ? "opacity-50 cursor-not-allowed pointer-events-none"
                : "hover:border-slate-300"
            }`}
          >
            <div className={`w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold shrink-0 ${
              step2Done
                ? "bg-[#ECF0FE] text-[#2348C8] border border-[#D6E0FD]"
                : step1Done
                ? "bg-[#2F5BEA]/10 text-[#2F5BEA] border border-[#2F5BEA]/20"
                : "bg-slate-100 text-slate-400 border border-slate-200"
            }`}>
              {step2Done ? "✓" : "2"}
            </div>
            <div className="flex-1">
              <div className="font-bold text-[#1A1C22] text-[15.5px]">
                {t("steps.startInterview") || "Пройти ИИ-интервью"}
              </div>
              <div className="text-[#56596a] text-sm mt-0.5">
                {step2Done
                  ? `Успешно пройдено интервью: ${stats?.interview_count} раз(а)`
                  : t("steps.startInterviewDesc")}
              </div>
            </div>
            <span className={`text-sm font-bold ${step2Done ? "text-[#2348C8]" : step1Done ? "text-[#2F5BEA]" : "text-slate-400"}`}>
              {step2Done ? "Пройдено" : step1Done ? "Сейчас" : "Заблокировано"}
            </span>
          </Link>

          <Link
            href={step2Done ? "/candidate/reports" : "#"}
            className={`flex items-center gap-4 border rounded-2xl p-5 bg-white transition-all shadow-[0_1px_2px_rgba(20,22,30,0.04)] ${
              !step2Done
                ? "opacity-50 cursor-not-allowed pointer-events-none"
                : "hover:border-slate-300"
            }`}
          >
            <div className={`w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold shrink-0 ${
              step3Done
                ? "bg-[#ECF0FE] text-[#2348C8] border border-[#D6E0FD]"
                : "bg-slate-100 text-slate-400 border border-slate-200"
            }`}>
              {step3Done ? "✓" : "3"}
            </div>
            <div className="flex-1">
              <div className="font-bold text-[#1A1C22] text-[15.5px]">
                {t("steps.viewReports") || "Получить отчёт по навыкам"}
              </div>
              <div className="text-[#56596a] text-sm mt-0.5">
                {step3Done
                  ? `Подготовлено отчетов по компетенциям: ${stats?.completed_count}`
                  : t("steps.viewReportsDesc")}
              </div>
            </div>
            <span className={`text-sm font-bold ${step3Done ? "text-[#2348C8]" : "text-slate-400"}`}>
              {step3Done ? "Смотреть" : "Ожидает"}
            </span>
          </Link>
        </div>

        {/* Settings blocks */}
        <h2 className="font-manrope font-bold text-xl text-[#1A1C22] mb-4">Настройки профиля</h2>
        <div className="grid gap-6 md:grid-cols-2 mb-8">
          {/* Salary Expectation card */}
          <div className="candidate-card p-6 flex flex-col justify-between">
            <div>
              <h3 className="text-[16px] font-bold text-[#1A1C22] mb-1">{t("salary.title")}</h3>
              <p className="text-xs text-[#56596a] mb-5">Укажите желаемый диапазон оплаты труда в удобной валюте.</p>
              <div className="grid grid-cols-3 gap-3 items-end">
                <div className="col-span-1">
                  <label className="text-[#56596a] text-xs font-bold mb-1.5 block">{t("salary.min")}</label>
                  <input
                    type="number"
                    placeholder="80000"
                    value={salaryMin}
                    onChange={(e) => setSalaryMin(e.target.value)}
                    className="candidate-input w-full px-3 py-2.5 text-sm"
                  />
                </div>
                <div className="col-span-1">
                  <label className="text-[#56596a] text-xs font-bold mb-1.5 block">{t("salary.max")}</label>
                  <input
                    type="number"
                    placeholder="120000"
                    value={salaryMax}
                    onChange={(e) => setSalaryMax(e.target.value)}
                    className="candidate-input w-full px-3 py-2.5 text-sm"
                  />
                </div>
                <div className="col-span-1">
                  <label className="text-[#56596a] text-xs font-bold mb-1.5 block">{t("salary.currency")}</label>
                  <div className="relative">
                    <select
                      value={salaryCurrency}
                      onChange={(e) => setSalaryCurrency(e.target.value)}
                      className="candidate-select w-full appearance-none px-3 py-2.5 pr-8 text-sm cursor-pointer"
                    >
                      {["USD", "EUR", "GBP", "RUB", "KZT"].map((c) => (
                        <option key={c} value={c}>{c}</option>
                      ))}
                    </select>
                    <SelectChevron />
                  </div>
                </div>
              </div>
            </div>
            <button
              onClick={handleSaveSalary}
              disabled={savingSalary}
              className="mt-6 candidate-btn-primary w-full py-2.5 text-sm rounded-xl"
            >
              {salarySaved ? t("salary.saved") : savingSalary ? common("actions.saving") : common("actions.save")}
            </button>
          </div>

          {/* Privacy Expectations Card */}
          <div className="candidate-card p-6 flex flex-col justify-between">
            <div>
              <h3 className="text-[16px] font-bold text-[#1A1C22] mb-1">{t("privacy.title")}</h3>
              <p className="text-xs text-[#56596a] mb-5">Управляйте видимостью ваших ИИ-отчетов для работодателей.</p>
              <div className="space-y-4">
                <div>
                  <label className="text-[#56596a] text-xs font-bold mb-1.5 block">{t("privacy.profileStatus")}</label>
                  <div className="grid grid-cols-2 gap-2">
                    <button
                      onClick={() => handleProfileStatusChange(true)}
                      className={`rounded-xl border py-2 text-xs font-bold transition-all ${
                        isProfileActive
                          ? "bg-[#ECF0FE] text-[#2348C8] border-[#D6E0FD]"
                          : "bg-white text-slate-500 border-slate-200 hover:border-slate-400"
                      }`}
                    >
                      {t("privacy.profileActive")}
                    </button>
                    <button
                      onClick={() => handleProfileStatusChange(false)}
                      className={`rounded-xl border py-2 text-xs font-bold transition-all ${
                        !isProfileActive
                          ? "bg-slate-100 text-[#1A1C22] border-slate-300"
                          : "bg-white text-slate-500 border-slate-200 hover:border-slate-400"
                      }`}
                    >
                      {t("privacy.profileInactive")}
                    </button>
                  </div>
                </div>

                <div>
                  <label className="text-[#56596a] text-xs font-bold mb-1.5 block">{t("privacy.visibility")}</label>
                  <div className="relative">
                    <select
                      value={privacy.visibility}
                      onChange={(e) => {
                        const nextVisibility = e.target.value as ProfileVisibility;
                        setPrivacy((current) => ({ ...current, visibility: nextVisibility }));
                        if (nextVisibility !== "private") {
                          setLastActiveVisibility(nextVisibility as ActiveProfileVisibility);
                        }
                      }}
                      disabled={!isProfileActive}
                      className="candidate-select w-full appearance-none px-4 py-2.5 pr-8 text-sm cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      <option value="marketplace">{t("privacy.marketplace")}</option>
                      <option value="direct_link">{t("privacy.directLink")}</option>
                      <option value="request_only">{t("privacy.requestOnly")}</option>
                      <option value="private">{t("privacy.private")}</option>
                    </select>
                    <SelectChevron />
                  </div>
                  {!isProfileActive && (
                    <p className="mt-1.5 text-[11px] text-slate-500">{t("privacy.inactiveHint")}</p>
                  )}
                </div>
              </div>
            </div>
            <button
              onClick={handleSavePrivacy}
              disabled={savingPrivacy}
              className="mt-6 candidate-btn-primary w-full py-2.5 text-sm rounded-xl"
            >
              {privacySaved ? t("privacy.saved") : savingPrivacy ? common("actions.saving") : common("actions.save")}
            </button>
          </div>
        </div>

        {/* Detailed help block & links */}
        <div className="candidate-card p-5 mb-6 bg-slate-50/50">
          <p className="text-sm font-bold text-[#1A1C22]">{visibilityHelp[privacy.visibility].title}</p>
          <p className="text-sm text-[#56596a] mt-1 leading-relaxed">{visibilityHelp[privacy.visibility].body}</p>
          {(privacy.visibility === "direct_link" || privacy.visibility === "request_only") && privacy.share_token && (
            <div className="mt-4 border-t border-slate-100 pt-4">
              <p className="text-xs font-bold text-[#2f5bea] uppercase tracking-wider">
                {privacy.visibility === "direct_link" ? t("privacy.shareableLink") : t("privacy.requestLink")}
              </p>
              <p className="text-sm font-semibold text-[#1A1C22] mt-1 break-all bg-slate-100 px-3 py-2 rounded-lg inline-block border border-slate-200">
                {typeof window !== "undefined" ? window.location.origin : ""}/candidate/share/{privacy.share_token}
              </p>
              <p className="text-xs text-[#56596a] mt-2 leading-relaxed">
                {privacy.visibility === "direct_link"
                  ? t("privacy.shareHelp.directLink")
                  : t("privacy.shareHelp.requestOnly")}
              </p>
              <div className="mt-3 flex gap-2">
                <button
                  onClick={handleCopyShareLink}
                  className="candidate-btn-primary text-xs px-4 py-2 rounded-lg"
                >
                  {copyState === "copied" ? common("status.copied") : copyState === "failed" ? common("status.copyFailed") : t("privacy.copyLink")}
                </button>
                <Link
                  href={`/candidate/share/${privacy.share_token}`}
                  target="_blank"
                  className="candidate-btn-secondary text-xs px-4 py-2 rounded-lg"
                >
                  {t("privacy.openSharedProfile")}
                </Link>
              </div>
            </div>
          )}
        </div>

        {/* Access Requests */}
        <div className="candidate-card p-6">
          <h3 className="text-[16px] font-bold text-[#1A1C22] mb-1">{t("accessRequests.title")}</h3>
          <p className="text-xs text-[#56596a] mb-5">{t("accessRequests.description")}</p>
          {accessRequests.length === 0 ? (
            <p className="text-xs text-slate-400 italic py-2">{t("accessRequests.empty")}</p>
          ) : (
            <div className="divide-y divide-slate-100">
              {accessRequests.map((request) => (
                <div key={request.request_id} className="py-4 first:pt-0 last:pb-0 flex flex-col md:flex-row md:items-center justify-between gap-4">
                  <div>
                    <p className="text-sm font-bold text-[#1a1c22]">{request.company_name}</p>
                    <p className="text-xs text-[#56596a] mt-1">
                      {t("accessRequests.requestedBy", {
                        email: request.requested_by_email ?? t("accessRequests.companyMember"),
                        date: new Date(request.updated_at).toLocaleString(),
                      })}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={`px-2.5 py-1 rounded-full text-xs font-bold border ${
                      request.status === "approved"
                        ? "bg-[#ECF0FE] text-[#2348C8] border-[#D6E0FD]"
                        : request.status === "denied"
                          ? "bg-red-50 text-red-600 border-red-100"
                          : "bg-[#ECF0FE] text-[#2348C8] border-[#D6E0FD]"
                    }`}>
                      {request.status === "approved"
                        ? t("accessRequests.status.approved")
                        : request.status === "denied"
                          ? t("accessRequests.status.denied")
                          : t("accessRequests.status.pending")}
                    </span>
                    {request.status === "pending" && (
                      <div className="flex gap-1.5">
                        <button
                          onClick={() => handleAccessRequestAction(request.request_id, "approve")}
                          disabled={accessActionId === request.request_id}
                          className="px-3 py-1.5 rounded-lg bg-[#2F5BEA] text-white text-xs font-bold hover:bg-[#2348C8] disabled:opacity-50"
                        >
                          {t("accessRequests.approve")}
                        </button>
                        <button
                          onClick={() => handleAccessRequestAction(request.request_id, "deny")}
                          disabled={accessActionId === request.request_id}
                          className="px-3 py-1.5 rounded-lg bg-slate-200 text-slate-700 text-xs font-bold hover:bg-slate-300 disabled:opacity-50"
                        >
                          {t("accessRequests.deny")}
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </CandidateShell>
  );
}

function SelectChevron() {
  return (
    <span className="pointer-events-none absolute inset-y-0 right-4 flex items-center text-slate-400">
      <svg className="h-4 w-4" viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <path d="M6 8l4 4 4-4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </span>
  );
}
