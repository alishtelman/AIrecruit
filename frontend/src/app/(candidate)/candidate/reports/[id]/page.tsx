"use client";

import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { useAuth } from "@/hooks/useAuth";
import { reportApi } from "@/lib/api";
import type { AssessmentReport, HiringRecommendation, CompetencyScore, SkillTag, RedFlag, QuestionAnalysis, ReportSummaryBlock, SystemDesignStageSummary, SystemDesignRubricScore, BehavioralInterviewStageSummary, BehavioralInterviewRubricScore, DevelopmentRoadmapPhase, CodingTaskStageSummary, CodingTaskRubricScore, CodingTaskCoverageCheck, SqlLiveStageSummary, SqlLiveRubricScore } from "@/lib/types";

const CATEGORY_COLORS: Record<string, string> = {
  technical_core: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  technical_breadth: "bg-cyan-500/15 text-cyan-400 border-cyan-500/30",
  problem_solving: "bg-purple-500/15 text-purple-400 border-purple-500/30",
  communication: "bg-green-500/15 text-green-400 border-green-500/30",
  behavioral: "bg-orange-500/15 text-orange-400 border-orange-500/30",
};

const PROFICIENCY_COLORS: Record<string, string> = {
  expert: "bg-green-500/20 text-green-400",
  advanced: "bg-blue-500/20 text-blue-400",
  intermediate: "bg-yellow-500/20 text-yellow-400",
  beginner: "bg-slate-500/20 text-slate-400",
};

const SEVERITY_COLORS: Record<string, string> = {
  high: "border-red-500/40 bg-red-500/10 text-red-300",
  medium: "border-yellow-500/40 bg-yellow-500/10 text-yellow-300",
  low: "border-slate-600 bg-slate-800 text-slate-400",
};

const RU_COMPETENCY_LABELS: Record<string, string> = {
  "System Design & Architecture": "Системный дизайн и архитектура",
  "Database Design & Optimization": "Проектирование и оптимизация БД",
  "API Design & Protocols": "Проектирование API и протоколы",
  "Programming Fundamentals": "Базовые знания программирования",
  "DevOps & Infrastructure": "DevOps и инфраструктура",
  "Security & Error Handling": "Безопасность и обработка ошибок",
  "Debugging & Problem Decomposition": "Отладка и декомпозиция задач",
  "Technical Communication": "Техническая коммуникация",
  "Collaboration & Code Review": "Командная работа и код-ревью",
  "Ownership & Growth Mindset": "Ответственность и установка на рост",
  "UI Framework Mastery": "Владение UI-фреймворками",
  "Web Performance Optimization": "Оптимизация производительности веба",
  "CSS & Responsive Design": "CSS и адаптивный дизайн",
  "JavaScript/TypeScript Fundamentals": "Основы JavaScript/TypeScript",
  "Accessibility & Standards": "Доступность и стандарты",
  "Testing & Quality": "Тестирование и качество",
  "Collaboration & Design Partnership": "Сотрудничество с дизайном",
  "Test Strategy & Planning": "Тестовая стратегия и планирование",
  "Test Automation": "Тестовая автоматизация",
  "Manual & Exploratory Testing": "Ручное и исследовательское тестирование",
  "API & Performance Testing": "API- и нагрузочное тестирование",
  "DevOps & CI/CD Integration": "DevOps и интеграция CI/CD",
  "Domain & Product Understanding": "Понимание домена и продукта",
  "Root Cause Analysis": "Анализ первопричин",
  "Collaboration & Advocacy": "Сотрудничество и quality advocacy",
  "CI/CD Pipeline Design": "Проектирование CI/CD-пайплайнов",
  "Container Orchestration": "Оркестрация контейнеров",
  "Cloud Infrastructure": "Облачная инфраструктура",
  "Monitoring & Observability": "Мониторинг и observability",
  "Security & Compliance": "Безопасность и соответствие требованиям",
  "Scripting & Automation": "Скрипты и автоматизация",
  "Incident Response & Troubleshooting": "Реакция на инциденты и troubleshooting",
  "Collaboration & On-Call Culture": "Сотрудничество и on-call культура",
  "ML Modeling & Algorithms": "ML-модели и алгоритмы",
  "Data Processing & Feature Engineering": "Обработка данных и feature engineering",
  "Statistics & Experimentation": "Статистика и эксперименты",
  "MLOps & Production ML": "MLOps и production ML",
  "Data Infrastructure & Tools": "Инфраструктура данных и инструменты",
  "Domain Knowledge Application": "Применение доменной экспертизы",
  "Analytical Problem Solving": "Аналитическое решение задач",
  "Collaboration & Cross-functional Work": "Кросс-функциональное сотрудничество",
  "Product Strategy & Vision": "Продуктовая стратегия и видение",
  "Requirements & User Research": "Требования и исследование пользователей",
  "Prioritization & Decision Making": "Приоритизация и принятие решений",
  "Metrics & Data-Driven Decisions": "Метрики и решения на основе данных",
  "Technical Understanding": "Техническое понимание",
  "Market & Business Acumen": "Понимание рынка и бизнеса",
  "Problem Structuring": "Структурирование проблем",
  "Stakeholder Communication": "Коммуникация со стейкхолдерами",
  "Leadership & Influence": "Лидерство и влияние",
  "Platform-Specific Development": "Разработка под конкретные платформы",
  "Cross-Platform Frameworks": "Кроссплатформенные фреймворки",
  "Mobile UI & UX Implementation": "Реализация мобильного UI/UX",
  "Performance & Memory Optimization": "Оптимизация производительности и памяти",
  "Networking & Data Persistence": "Сетевое взаимодействие и хранение данных",
  "Testing & CI/CD for Mobile": "Тестирование и CI/CD для mobile",
  "Collaboration & Cross-Platform Alignment": "Кроссплатформенное взаимодействие",
  "UX Research & User Understanding": "UX-исследования и понимание пользователей",
  "UI Design & Visual Systems": "UI-дизайн и визуальные системы",
  "Interaction Design": "Проектирование взаимодействия",
  "Information Architecture": "Информационная архитектура",
  "Accessibility Design": "Дизайн доступности",
  "Design-to-Development Handoff": "Передача дизайна в разработку",
  "Design Problem Solving": "Решение дизайн-задач",
};

function localizeCompetencyLabel(label: string, locale: string) {
  if (locale === "ru") {
    return RU_COMPETENCY_LABELS[label] ?? label;
  }
  return label;
}

function localizeEvidenceText(text: string, locale: string) {
  return text;
}

function localizeFreeformText(text: string, locale: string) {
  if (locale !== "ru") return text;

  let result = localizeEvidenceText(text, locale);
  const replacements: Array<[string, string]> = [
    ["backend engineer", "бэкенд-разработчик"],
    ["frontend engineer", "фронтенд-разработчик"],
    ["qa engineer", "QA-инженер"],
    ["devops engineer", "DevOps-инженер"],
    ["data scientist", "дата-сайентист"],
    ["product manager", "продакт-менеджер"],
    ["mobile engineer", "мобильный разработчик"],
    ["ux/ui designer", "UX/UI-дизайнер"],
  ];

  for (const [from, to] of replacements) {
    result = result.replace(new RegExp(from, "gi"), to);
  }

  return result;
}

function localizeScoredMetric(metric: string, locale: string) {
  const ruLabels: Record<string, string> = {
    technical_depth: "Техническая глубина",
    practical_experience: "Практический опыт",
    problem_solving: "Решение задач",
    communication: "Коммуникация",
    ownership: "Ownership",
    role_fit: "Role fit",
    growth_potential: "Потенциал роста",
  };
  if (locale === "ru") return ruLabels[metric] ?? metric.replace(/_/g, " ");
  return metric.replace(/_/g, " ");
}

function getCategoryLabel(t: ReturnType<typeof useTranslations>, category: string) {
  if (category === "technical_core") return t("labels.technicalCore");
  if (category === "technical_breadth") return t("labels.technicalBreadth");
  if (category === "problem_solving") return t("labels.problemSolving");
  if (category === "communication") return t("labels.communication");
  if (category === "behavioral") return t("labels.behavioral");
  return category;
}

function InterviewSummaryPanel({
  summaryModel,
  locale,
  onJumpToQuestion,
}: {
  summaryModel: AssessmentReport["summary_model"];
  locale: string;
  onJumpToQuestion?: (questionNumber: number) => void;
}) {
  const t = useTranslations("report");
  const [showDetails, setShowDetails] = useState(false);

  if (!summaryModel) return null;

  const items = [
    { label: t("summaryModel.coreTopics"), value: summaryModel.core_topics },
    { label: t("summaryModel.extraTurns"), value: summaryModel.extra_turns },
    { label: t("summaryModel.coveredCompetencies"), value: summaryModel.covered_competencies },
    { label: t("summaryModel.strongTopics"), value: summaryModel.strong_topics },
    { label: t("summaryModel.honestGaps"), value: summaryModel.honest_gaps },
    { label: t("summaryModel.genericTopics"), value: summaryModel.generic_or_evasive_topics },
  ];
  const topicOutcomes = summaryModel.topic_outcomes ?? [];

  function getTopicSignalLabel(signal: string) {
    switch (signal) {
      case "strong":
        return t("summaryModel.topicSignals.strong");
      case "partial":
        return t("summaryModel.topicSignals.partial");
      case "generic":
        return t("summaryModel.topicSignals.generic");
      case "evasive":
        return t("summaryModel.topicSignals.evasive");
      case "no_experience_honest":
        return t("summaryModel.topicSignals.no_experience_honest");
      default:
        return t("summaryModel.topicSignals.unknown");
    }
  }

  function getTopicOutcomeLabel(outcome: string) {
    switch (outcome) {
      case "validated":
        return t("summaryModel.topicOutcomes.validated");
      case "partial":
        return t("summaryModel.topicOutcomes.partial");
      case "honest_gap":
        return t("summaryModel.topicOutcomes.honest_gap");
      case "unverified_claim":
        return t("summaryModel.topicOutcomes.unverified_claim");
      case "evasive":
        return t("summaryModel.topicOutcomes.evasive");
      default:
        return outcome.replace(/_/g, " ");
    }
  }

  function getTopicSignalTone(signal: string) {
    if (signal === "strong") return "border-emerald-500/30 bg-emerald-500/10 text-emerald-200";
    if (signal === "partial") return "border-amber-500/30 bg-amber-500/10 text-amber-200";
    if (signal === "no_experience_honest") return "border-slate-600 bg-slate-900 text-slate-300";
    return "border-rose-500/30 bg-rose-500/10 text-rose-200";
  }

  function getTopicOutcomeTone(outcome: string) {
    if (outcome === "validated") return "border-emerald-500/30 bg-emerald-500/10 text-emerald-200";
    if (outcome === "partial") return "border-blue-500/30 bg-blue-500/10 text-blue-200";
    if (outcome === "honest_gap") return "border-slate-600 bg-slate-900 text-slate-300";
    if (outcome === "unverified_claim") return "border-yellow-500/30 bg-yellow-500/10 text-yellow-200";
    return "border-rose-500/30 bg-rose-500/10 text-rose-200";
  }

  return (
    <div className="mb-6 rounded-2xl border border-slate-700 bg-slate-800/80 p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-xs uppercase tracking-[0.24em] text-slate-500">{t("summaryModel.eyebrow")}</div>
          <div className="text-sm font-semibold text-white">{t("summaryModel.title")}</div>
        </div>
        <span className="rounded-full border border-cyan-500/30 bg-cyan-500/10 px-3 py-1 text-xs font-medium text-cyan-300">
          {t(`summaryModel.signal.${summaryModel.signal_quality}`)}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {items.map((item) => (
          <div key={item.label} className="rounded-xl border border-slate-700 bg-slate-900/60 px-3 py-3">
            <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">{item.label}</div>
            <div className="mt-1 text-xl font-semibold text-white">{item.value}</div>
          </div>
        ))}
      </div>
      {topicOutcomes.length > 0 && (
        <div className="mt-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="text-xs uppercase tracking-[0.18em] text-slate-500">{t("summaryModel.detailsTitle")}</div>
            <button
              type="button"
              onClick={() => setShowDetails((current) => !current)}
              className="rounded-full border border-cyan-500/30 bg-cyan-500/10 px-3 py-1 text-xs font-medium text-cyan-300 transition-colors hover:bg-cyan-500/20"
            >
              {showDetails ? t("summaryModel.detailsHide") : t("summaryModel.detailsShow")}
            </button>
          </div>
          {showDetails && (
            <div className="mt-3 grid gap-3">
              {topicOutcomes.map((outcome) => (
                <div key={outcome.slot} className="rounded-xl border border-slate-700 bg-slate-900/60 p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="text-xs uppercase tracking-[0.16em] text-slate-500">
                        {t("questionShort", { number: outcome.slot })}
                      </div>
                      <div className="mt-1 text-sm font-semibold text-white">
                        {localizeFreeformText(outcome.label, locale)}
                      </div>
                    </div>
                    {onJumpToQuestion && (
                      <button
                        type="button"
                        onClick={() => onJumpToQuestion(outcome.slot)}
                        className="rounded-full border border-slate-600 bg-slate-950 px-3 py-1 text-xs text-slate-200 transition-colors hover:border-cyan-400/40 hover:text-cyan-200"
                      >
                        {t("summaryModel.jumpToQuestion")}
                      </button>
                    )}
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <span className={`rounded-full border px-2.5 py-1 text-[11px] ${getTopicSignalTone(outcome.signal)}`}>
                      {t("summaryModel.signalLabel")}: {getTopicSignalLabel(outcome.signal)}
                    </span>
                    <span className={`rounded-full border px-2.5 py-1 text-[11px] ${getTopicOutcomeTone(outcome.outcome)}`}>
                      {t("summaryModel.outcomeLabel")}: {getTopicOutcomeLabel(outcome.outcome)}
                    </span>
                  </div>
                  {outcome.resume_anchor && (
                    <div className="mt-3">
                      <div className="text-[11px] uppercase tracking-[0.16em] text-slate-500">{t("summaryModel.resumeAnchor")}</div>
                      <div className="mt-1 text-sm text-slate-200">{localizeFreeformText(outcome.resume_anchor, locale)}</div>
                    </div>
                  )}
                  {outcome.verification_target && (
                    <div className="mt-3">
                      <div className="text-[11px] uppercase tracking-[0.16em] text-slate-500">{t("summaryModel.verificationTarget")}</div>
                      <div className="mt-1 text-sm text-slate-200">{localizeFreeformText(outcome.verification_target, locale)}</div>
                    </div>
                  )}
                  {outcome.evidence_hint && (
                    <div className="mt-3">
                      <div className="text-[11px] uppercase tracking-[0.16em] text-slate-500">{t("summaryModel.evidenceHint")}</div>
                      <div className="mt-1 text-sm leading-6 text-slate-300">
                        {localizeFreeformText(outcome.evidence_hint, locale)}
                      </div>
                    </div>
                  )}
                  {outcome.why_asked && (
                    <div className="mt-3">
                      <div className="text-[11px] uppercase tracking-[0.16em] text-slate-500">{t("summaryModel.whyAsked")}</div>
                      <div className="mt-1 text-sm leading-6 text-slate-300">
                        {localizeFreeformText(outcome.why_asked, locale)}
                      </div>
                    </div>
                  )}
                  {outcome.what_was_scored && (
                    <div className="mt-3">
                      <div className="text-[11px] uppercase tracking-[0.16em] text-slate-500">{t("summaryModel.whatWasScored")}</div>
                      <div className="mt-1 text-sm leading-6 text-slate-300">
                        {localizeFreeformText(outcome.what_was_scored, locale)}
                      </div>
                    </div>
                  )}
                  {outcome.scored_metrics && outcome.scored_metrics.length > 0 && (
                    <div className="mt-3">
                      <div className="text-[11px] uppercase tracking-[0.16em] text-slate-500">{t("summaryModel.scoredMetrics")}</div>
                      <div className="mt-1 flex flex-wrap gap-2">
                        {outcome.scored_metrics.map((metric) => (
                          <span key={metric} className="rounded-full border border-sky-500/30 bg-sky-500/10 px-2.5 py-1 text-[11px] text-sky-200">
                            {localizeScoredMetric(metric, locale)}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function ReportPage() {
  const t = useTranslations("report");
  const locale = useLocale();
  const { id } = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const { loading: authLoading } = useAuth();
  const [report, setReport] = useState<AssessmentReport | null>(null);
  const [error, setError] = useState("");
  const [expandedQ, setExpandedQ] = useState<number | null>(null);

  useEffect(() => {
    if (!id || authLoading) return;
    reportApi
      .getById(id)
      .then(setReport)
      .catch(() => setError(t("loadFailed")));
  }, [id, authLoading, t]);

  if (authLoading || (!report && !error)) {
    return (
      <div className="min-h-screen bg-slate-900 px-4 py-10">
        <div className="max-w-3xl mx-auto space-y-4">
          <div className="h-4 w-32 bg-slate-800 rounded animate-pulse" />
          <div className="h-8 w-56 bg-slate-800 rounded animate-pulse" />
          <div className="h-28 bg-slate-800 rounded-2xl animate-pulse" />
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="h-24 bg-slate-800 rounded-xl animate-pulse" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (error || !report) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center px-4">
        <div className="text-center">
          <div className="text-red-400 mb-4">{error}</div>
          <Link href="/candidate/dashboard" className="text-blue-400 hover:underline text-sm">
            ← {t("backToDashboard")}
          </Link>
        </div>
      </div>
    );
  }

  const recommendationConfig: Record<
    HiringRecommendation,
    { label: string; color: string; bg: string }
  > = {
    strong_yes: { label: t("labels.strongYes"), color: "text-green-400", bg: "bg-green-500/10 border-green-500/30" },
    yes: { label: t("labels.yes"), color: "text-blue-400", bg: "bg-blue-500/10 border-blue-500/30" },
    maybe: { label: t("labels.maybe"), color: "text-yellow-400", bg: "bg-yellow-500/10 border-yellow-500/30" },
    no: { label: t("labels.no"), color: "text-red-400", bg: "bg-red-500/10 border-red-500/30" },
  };
  const rec = recommendationConfig[report.hiring_recommendation];
  const notice = searchParams.get("notice");

  return (
    <div className="min-h-screen bg-slate-900 px-4 py-10">
      <div className="max-w-3xl mx-auto">
        <Link href="/candidate/reports" className="text-slate-400 hover:text-white text-sm mb-6 inline-block transition-colors">
          ← {t("backToInterviews")}
        </Link>

        <h1 className="text-2xl font-bold text-white mb-2">{t("title")}</h1>

        {notice === "recording_failed" && (
          <div className="mb-4 rounded-lg border border-yellow-500/30 bg-yellow-500/10 px-4 py-3 text-sm text-yellow-300">
            {t("recordingFailed")}
          </div>
        )}

        {notice === "recording_skipped" && (
          <div className="mb-4 rounded-lg border border-slate-700 bg-slate-800 px-4 py-3 text-sm text-slate-300">
            {t("recordingSkipped")}
          </div>
        )}

        {/* Summary card */}
        {report.summary && (
          <SummaryCard summary={report.summary} recommendationConfig={recommendationConfig} />
        )}

        {report.interview_summary && (
          <p className="text-slate-400 mb-6">{localizeFreeformText(report.interview_summary, locale)}</p>
        )}

        {report.module_session?.scenario_title && <ModuleSessionBanner session={report.module_session} locale={locale} />}

        {report.summary_model && (
          <InterviewSummaryPanel
            summaryModel={report.summary_model}
            locale={locale}
            onJumpToQuestion={(questionNumber) => {
              const questionIndex = report.per_question_analysis?.findIndex((qa) => qa.question_number === questionNumber) ?? -1;
              if (questionIndex >= 0) {
                setExpandedQ(questionIndex);
              }
              window.requestAnimationFrame(() => {
                const target = document.getElementById(`question-analysis-${questionNumber}`) ?? document.getElementById("per-question-analysis");
                target?.scrollIntoView({ behavior: "smooth", block: "start" });
              });
            }}
          />
        )}
        {report.system_design_summary && <SystemDesignSummaryPanel summary={report.system_design_summary} />}
        {report.behavioral_interview_summary && <BehavioralInterviewSummaryPanel summary={report.behavioral_interview_summary} />}
        {report.coding_task_summary && <CodingTaskSummaryPanel summary={report.coding_task_summary} />}
        {report.sql_live_summary && <SqlLiveSummaryPanel summary={report.sql_live_summary} />}
        {report.written_communication_summary && <WrittenCommunicationSummaryPanel summary={report.written_communication_summary} />}

        {/* Recommendation badge */}
        <div className={`inline-flex items-center gap-2 border rounded-full px-4 py-1.5 text-sm font-semibold mb-6 ${rec.bg} ${rec.color}`}>
          {t("recommendation")}: {rec.label}
        </div>
        {report.proficiency_label && (
          <div className="ml-3 inline-flex items-center gap-2 rounded-full border border-cyan-500/30 bg-cyan-500/10 px-4 py-1.5 text-sm font-semibold text-cyan-200">
            {t("proficiencyLevel")}: {report.proficiency_label}
          </div>
        )}

        {/* Score cards — 5 dimensions */}
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 mb-8">
          <ScoreCard label={t("overallScore")} score={report.overall_score} highlight />
          <ScoreCard label={t("hardSkills")} score={report.hard_skills_score} />
          <ScoreCard label={t("softSkills")} score={report.soft_skills_score} />
          <ScoreCard label={t("communication")} score={report.communication_score} />
          <ScoreCard label={t("problemSolving")} score={report.problem_solving_score} />
          {report.response_consistency != null && (
            <ScoreCard label={t("consistency")} score={report.response_consistency} />
          )}
        </div>

        <ConfidencePanel report={report} locale={locale} />
        {report.explainability_report && (
          <ExplainabilityPanel explainability={report.explainability_report} />
        )}

        {/* Competency heatmap */}
        {report.competency_scores && report.competency_scores.length > 0 && (
          <Section title={t("competencyHeatmap")} color="blue">
            <CompetencyHeatmap scores={report.competency_scores} />
          </Section>
        )}

        {/* Skill matrix */}
        {report.skill_tags && report.skill_tags.length > 0 && (
          <Section title={t("skillsIdentified")} color="cyan">
            <SkillMatrix tags={report.skill_tags} />
          </Section>
        )}

        {/* Red flags */}
        {report.red_flags && report.red_flags.length > 0 && (
          <Section title={t("redFlags")} color="red">
            <div className="space-y-3">
              {report.red_flags.map((rf, i) => (
                <RedFlagRow key={i} flag={rf} />
              ))}
            </div>
          </Section>
        )}

        {/* Strengths */}
        {report.strengths.length > 0 && (
          <Section title={t("strengths")} color="green">
            {report.strengths.map((s, i) => (
              <ListItem key={i} text={s} bullet="+" color="text-green-400" />
            ))}
          </Section>
        )}

        {/* Weaknesses */}
        {report.weaknesses.length > 0 && (
          <Section title={t("areasToImprove")} color="yellow">
            {report.weaknesses.map((w, i) => (
              <ListItem key={i} text={w} bullet="-" color="text-yellow-400" />
            ))}
          </Section>
        )}

        {/* Recommendations */}
        {report.recommendations.length > 0 && (
          <Section title={t("recommendations")} color="purple">
            {report.recommendations.map((r, i) => (
              <ListItem key={i} text={r} bullet=">" color="text-purple-400" />
            ))}
          </Section>
        )}

        {report.development_roadmap && report.development_roadmap.phases.length > 0 && (
          <RoadmapPanel phases={report.development_roadmap.phases} />
        )}

        {/* Per-question analysis */}
        {report.per_question_analysis && report.per_question_analysis.length > 0 && (
          <div id="per-question-analysis" className="mt-6 scroll-mt-24">
            <h2 className="text-white font-semibold mb-3">{t("perQuestionAnalysis")}</h2>
            <div className="space-y-2">
              {report.per_question_analysis.map((qa, i) => (
                <QuestionAccordion
                  key={i}
                  qa={qa}
                  expanded={expandedQ === i}
                  onToggle={() => setExpandedQ(expandedQ === i ? null : i)}
                />
              ))}
            </div>
          </div>
        )}

        <div className="text-slate-600 text-xs mt-8">
          {t("generatedBy", {model: report.model_version, date: new Date(report.created_at).toLocaleDateString()})}
        </div>
      </div>
    </div>
  );
}

function ModuleSessionBanner({
  session,
  locale,
}: {
  session: NonNullable<AssessmentReport["module_session"]>;
  locale: string;
}) {
  const t = useTranslations("report");

  return (
    <div className="mb-6 rounded-2xl border border-cyan-500/20 bg-cyan-500/10 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-[0.24em] text-cyan-300">{t("moduleSession.eyebrow")}</div>
          <div className="mt-1 text-sm font-semibold text-white">
            {localizeFreeformText(session.module_title || t("moduleSession.titleFallback"), locale)}
          </div>
          <div className="mt-2 text-lg font-semibold text-white">
            {localizeFreeformText(session.scenario_title ?? "", locale)}
          </div>
        </div>
        <div className="flex flex-wrap gap-2 text-xs">
          <span className="rounded-full border border-cyan-400/20 bg-slate-900/50 px-3 py-1 text-slate-200">
            {t("moduleSession.stageCount", { count: session.stage_count })}
          </span>
          {session.preferred_language && (
            <span className="rounded-full border border-slate-700 bg-slate-950 px-3 py-1 text-slate-300">
              {t("moduleSession.preferredLanguage")}: {session.preferred_language}
            </span>
          )}
        </div>
      </div>
      {session.stack_focus && (
        <p className="mt-3 text-sm leading-6 text-slate-200">{localizeFreeformText(session.stack_focus, locale)}</p>
      )}
      {session.scenario_prompt && (
        <p className="mt-3 text-sm leading-6 text-slate-300">{localizeFreeformText(session.scenario_prompt, locale)}</p>
      )}
      {session.workspace_hint && (
        <p className="mt-3 text-sm leading-6 text-slate-400">{localizeFreeformText(session.workspace_hint, locale)}</p>
      )}
    </div>
  );
}

function SystemDesignSummaryPanel({ summary }: { summary: NonNullable<AssessmentReport["system_design_summary"]> }) {
  const t = useTranslations("report");
  const locale = useLocale();

  return (
    <div className="mb-6 rounded-2xl border border-violet-500/20 bg-violet-500/10 p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-[0.24em] text-violet-300">{t("systemDesign.eyebrow")}</div>
          <div className="text-sm font-semibold text-white">{summary.module_title || t("systemDesign.title")}</div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full border border-violet-400/20 bg-slate-900/50 px-3 py-1 text-xs text-slate-200">
            {t("systemDesign.stageCount", { count: summary.stage_count })}
          </span>
          {summary.overall_score != null && (
            <span className="rounded-full border border-violet-400/20 bg-violet-950/40 px-3 py-1 text-xs font-semibold text-violet-200">
              {t("systemDesign.overallScore")}: {summary.overall_score.toFixed(1)}/10
            </span>
          )}
        </div>
      </div>

      {summary.scenario_title && (
        <div className="mb-3">
          <div className="text-xs uppercase tracking-[0.16em] text-slate-500">{t("systemDesign.scenario")}</div>
          <div className="mt-1 text-sm font-medium text-white">{localizeFreeformText(summary.scenario_title, locale)}</div>
        </div>
      )}
      {summary.scenario_prompt && (
        <p className="mb-4 text-sm leading-6 text-slate-300">{localizeFreeformText(summary.scenario_prompt, locale)}</p>
      )}

      {summary.rubric_scores.length > 0 && (
        <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {summary.rubric_scores.map((rubric) => (
            <SystemDesignRubricCard key={rubric.rubric_key} rubric={rubric} />
          ))}
        </div>
      )}

      <div className="grid gap-3 md:grid-cols-3">
        {summary.stages.map((stage) => (
          <SystemDesignStageCard key={stage.stage_key} stage={stage} />
        ))}
      </div>
    </div>
  );
}

function SystemDesignStageCard({ stage }: { stage: SystemDesignStageSummary }) {
  const t = useTranslations("report");
  const locale = useLocale();

  return (
    <div className="rounded-xl border border-slate-700 bg-slate-900/60 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="text-sm font-semibold text-white">{localizeFreeformText(stage.stage_title, locale)}</div>
        <div className="text-right">
          {stage.stage_score != null && (
            <div className="text-sm font-bold text-violet-300">
              {t("systemDesign.stageScore")}: {stage.stage_score.toFixed(1)}
            </div>
          )}
          {stage.average_answer_quality != null && (
            <div className="text-[11px] text-slate-500">
              {t("systemDesign.answerQuality")}: {stage.average_answer_quality.toFixed(1)}
            </div>
          )}
        </div>
      </div>
      {stage.question_numbers.length > 0 && (
        <div className="mt-2 text-xs text-slate-500">
          {t("systemDesign.questionsCovered", { count: stage.question_numbers.length })}: {stage.question_numbers.join(", ")}
        </div>
      )}
      <div className="mt-3 space-y-2">
        {stage.evidence_items.length > 0 ? stage.evidence_items.map((item, index) => (
          <div key={index} className="text-sm leading-6 text-slate-300">
            {localizeFreeformText(item, locale)}
          </div>
        )) : (
          <div className="text-sm text-slate-500">{t("systemDesign.noEvidence")}</div>
        )}
      </div>
    </div>
  );
}

function SystemDesignRubricCard({ rubric }: { rubric: SystemDesignRubricScore }) {
  const t = useTranslations("report");

  return (
    <div className="rounded-xl border border-violet-500/15 bg-slate-900/60 px-3 py-3">
      <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">
        {t(`systemDesign.rubrics.${rubric.rubric_key}`)}
      </div>
      <div className="mt-1 text-xl font-semibold text-white">
        {rubric.score != null ? `${rubric.score.toFixed(1)}/10` : "—"}
      </div>
    </div>
  );
}

function BehavioralInterviewSummaryPanel({ summary }: { summary: NonNullable<AssessmentReport["behavioral_interview_summary"]> }) {
  const t = useTranslations("report");
  const locale = useLocale();

  return (
    <div className="mb-6 rounded-2xl border border-orange-500/20 bg-orange-500/10 p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-[0.24em] text-orange-300">{t("behavioralInterview.eyebrow")}</div>
          <div className="text-sm font-semibold text-white">{summary.module_title || t("behavioralInterview.title")}</div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full border border-orange-400/20 bg-slate-900/50 px-3 py-1 text-xs text-slate-200">
            {t("behavioralInterview.stageCount", { count: summary.stage_count })}
          </span>
          {summary.overall_score != null && (
            <span className="rounded-full border border-orange-400/20 bg-orange-950/40 px-3 py-1 text-xs font-semibold text-orange-200">
              {t("behavioralInterview.overallScore")}: {summary.overall_score.toFixed(1)}/10
            </span>
          )}
          {summary.ownership_score != null && (
            <span className="rounded-full border border-emerald-400/20 bg-emerald-950/40 px-3 py-1 text-xs font-semibold text-emerald-200">
              {t("behavioralInterview.ownershipScore")}: {summary.ownership_score.toFixed(1)}/10
            </span>
          )}
          {summary.leadership_score != null && (
            <span className="rounded-full border border-violet-400/20 bg-violet-950/40 px-3 py-1 text-xs font-semibold text-violet-200">
              {t("behavioralInterview.leadershipScore")}: {summary.leadership_score.toFixed(1)}/10
            </span>
          )}
        </div>
      </div>

      {summary.scenario_title && (
        <div className="mb-3">
          <div className="text-xs uppercase tracking-[0.16em] text-slate-500">{t("behavioralInterview.scenario")}</div>
          <div className="mt-1 text-sm font-medium text-white">{localizeFreeformText(summary.scenario_title, locale)}</div>
        </div>
      )}
      {summary.scenario_prompt && (
        <p className="mb-4 text-sm leading-6 text-slate-300">{localizeFreeformText(summary.scenario_prompt, locale)}</p>
      )}

      {summary.rubric_scores.length > 0 && (
        <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {summary.rubric_scores.map((rubric) => (
            <BehavioralInterviewRubricCard key={rubric.rubric_key} rubric={rubric} />
          ))}
        </div>
      )}

      {(summary.strengths.length > 0 || summary.gaps.length > 0 || summary.next_steps.length > 0) && (
        <div className="mb-4 grid gap-3 lg:grid-cols-3">
          <CodingTaskInsightList title={t("behavioralInterview.strengths")} tone="emerald" items={summary.strengths} />
          <CodingTaskInsightList title={t("behavioralInterview.gaps")} tone="amber" items={summary.gaps} />
          <CodingTaskInsightList title={t("behavioralInterview.nextSteps")} tone="blue" items={summary.next_steps} />
        </div>
      )}

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {summary.stages.map((stage) => (
          <BehavioralInterviewStageCard key={stage.stage_key} stage={stage} />
        ))}
      </div>
    </div>
  );
}

function BehavioralInterviewStageCard({ stage }: { stage: BehavioralInterviewStageSummary }) {
  const t = useTranslations("report");
  const locale = useLocale();

  return (
    <div className="rounded-xl border border-slate-700 bg-slate-900/60 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="text-sm font-semibold text-white">{localizeFreeformText(stage.stage_title, locale)}</div>
        <div className="text-right">
          {stage.stage_score != null && (
            <div className="text-sm font-bold text-orange-300">
              {t("behavioralInterview.stageScore")}: {stage.stage_score.toFixed(1)}
            </div>
          )}
          {stage.average_answer_quality != null && (
            <div className="text-[11px] text-slate-500">
              {t("behavioralInterview.answerQuality")}: {stage.average_answer_quality.toFixed(1)}
            </div>
          )}
        </div>
      </div>
      {stage.question_numbers.length > 0 && (
        <div className="mt-2 text-xs text-slate-500">
          {t("behavioralInterview.questionsCovered", { count: stage.question_numbers.length })}: {stage.question_numbers.join(", ")}
        </div>
      )}
      <div className="mt-3 space-y-2">
        {stage.evidence_items.length > 0 ? stage.evidence_items.map((item, index) => (
          <div key={index} className="text-sm leading-6 text-slate-300">
            {localizeFreeformText(item, locale)}
          </div>
        )) : (
          <div className="text-sm text-slate-500">{t("behavioralInterview.noEvidence")}</div>
        )}
      </div>
    </div>
  );
}

function BehavioralInterviewRubricCard({ rubric }: { rubric: BehavioralInterviewRubricScore }) {
  const t = useTranslations("report");

  return (
    <div className="rounded-xl border border-orange-500/15 bg-slate-900/60 px-3 py-3">
      <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">
        {t(`behavioralInterview.rubrics.${rubric.rubric_key}`)}
      </div>
      <div className="mt-1 text-xl font-semibold text-white">
        {rubric.score != null ? `${rubric.score.toFixed(1)}/10` : "—"}
      </div>
    </div>
  );
}

function CodingTaskSummaryPanel({ summary }: { summary: NonNullable<AssessmentReport["coding_task_summary"]> }) {
  const t = useTranslations("report");
  const locale = useLocale();

  return (
    <div className="mb-6 rounded-2xl border border-cyan-500/20 bg-cyan-500/10 p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-[0.24em] text-cyan-300">{t("codingTask.eyebrow")}</div>
          <div className="text-sm font-semibold text-white">{summary.module_title || t("codingTask.title")}</div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full border border-cyan-400/20 bg-slate-900/50 px-3 py-1 text-xs text-slate-200">
            {t("codingTask.stageCount", { count: summary.stage_count })}
          </span>
          {summary.overall_score != null && (
            <span className="rounded-full border border-cyan-400/20 bg-cyan-950/40 px-3 py-1 text-xs font-semibold text-cyan-200">
              {t("codingTask.overallScore")}: {summary.overall_score.toFixed(1)}/10
            </span>
          )}
          {summary.coverage_score != null && (
            <span className="rounded-full border border-emerald-400/20 bg-emerald-950/40 px-3 py-1 text-xs font-semibold text-emerald-200">
              {t("codingTask.coverageScore")}: {summary.coverage_score.toFixed(1)}/10
            </span>
          )}
          {summary.runner_score != null && (
            <span className="rounded-full border border-fuchsia-400/20 bg-fuchsia-950/40 px-3 py-1 text-xs font-semibold text-fuchsia-200">
              {t("codingTask.runnerScore")}: {summary.runner_score.toFixed(1)}/10
            </span>
          )}
          {summary.stack_score != null && (
            <span className="rounded-full border border-blue-400/20 bg-blue-950/40 px-3 py-1 text-xs font-semibold text-blue-200">
              {t("codingTask.stackScore")}: {summary.stack_score.toFixed(1)}/10
            </span>
          )}
        </div>
      </div>

      {summary.scenario_title && (
        <div className="mb-3">
          <div className="text-xs uppercase tracking-[0.16em] text-slate-500">{t("codingTask.task")}</div>
          <div className="mt-1 text-sm font-medium text-white">{localizeFreeformText(summary.scenario_title, locale)}</div>
        </div>
      )}
      {summary.stack_focus && (
        <div className="mb-3">
          <div className="text-xs uppercase tracking-[0.16em] text-slate-500">{t("codingTask.stackFocus")}</div>
          <div className="mt-1 text-sm text-slate-200">{localizeFreeformText(summary.stack_focus, locale)}</div>
        </div>
      )}
      {summary.preferred_language && (
        <div className="mb-3 text-xs text-slate-400">
          {t("codingTask.preferredLanguage")}: <span className="font-medium text-slate-200">{summary.preferred_language}</span>
        </div>
      )}
      {summary.scenario_prompt && (
        <p className="mb-4 text-sm leading-6 text-slate-300">{localizeFreeformText(summary.scenario_prompt, locale)}</p>
      )}

      {summary.rubric_scores.length > 0 && (
        <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {summary.rubric_scores.map((rubric) => (
            <CodingTaskRubricCard key={rubric.rubric_key} rubric={rubric} />
          ))}
        </div>
      )}

      {(summary.strengths.length > 0 || summary.gaps.length > 0 || summary.next_steps.length > 0) && (
        <div className="mb-4 grid gap-3 lg:grid-cols-3">
          <CodingTaskInsightList title={t("codingTask.strengths")} tone="emerald" items={summary.strengths} />
          <CodingTaskInsightList title={t("codingTask.gaps")} tone="amber" items={summary.gaps} />
          <CodingTaskInsightList title={t("codingTask.nextSteps")} tone="blue" items={summary.next_steps} />
        </div>
      )}

      {summary.implementation_excerpt && (
        <div className="mb-4 rounded-xl border border-slate-700 bg-slate-950/70 p-4">
          <div className="mb-2 flex items-center justify-between gap-3">
            <div className="text-xs uppercase tracking-[0.16em] text-slate-500">{t("codingTask.codeExcerpt")}</div>
            {summary.code_signal_score != null && (
              <div className="text-xs text-cyan-300">
                {t("codingTask.codeSignal")}: {summary.code_signal_score.toFixed(1)}/10
              </div>
            )}
          </div>
          <pre className="overflow-x-auto whitespace-pre-wrap text-sm leading-6 text-slate-200">
            {summary.implementation_excerpt}
          </pre>
        </div>
      )}

      {summary.coverage_checks.length > 0 && (
        <div className="mb-4">
          <div className="mb-2 text-xs uppercase tracking-[0.16em] text-slate-500">{t("codingTask.coverageChecks")}</div>
          <div className="grid gap-3 lg:grid-cols-2">
            {summary.coverage_checks.map((check) => (
              <CodingTaskCoverageCheckCard key={check.check_key} check={check} />
            ))}
          </div>
        </div>
      )}

      {summary.runner_checks.length > 0 && (
        <div className="mb-4">
          <div className="mb-2 text-xs uppercase tracking-[0.16em] text-slate-500">{t("codingTask.runnerChecks")}</div>
          <div className="grid gap-3 lg:grid-cols-2">
            {summary.runner_checks.map((check) => (
              <CodingTaskCoverageCheckCard key={check.check_key} check={check} />
            ))}
          </div>
        </div>
      )}

      {summary.stack_checks.length > 0 && (
        <div className="mb-4">
          <div className="mb-2 text-xs uppercase tracking-[0.16em] text-slate-500">{t("codingTask.stackChecks")}</div>
          <div className="grid gap-3 lg:grid-cols-2">
            {summary.stack_checks.map((check) => (
              <CodingTaskCoverageCheckCard key={check.check_key} check={check} />
            ))}
          </div>
        </div>
      )}

      <div className="grid gap-3 md:grid-cols-3">
        {summary.stages.map((stage) => (
          <CodingTaskStageCard key={stage.stage_key} stage={stage} />
        ))}
      </div>
    </div>
  );
}

function CodingTaskInsightList({
  title,
  tone,
  items,
}: {
  title: string;
  tone: "emerald" | "amber" | "blue";
  items: string[];
}) {
  const locale = useLocale();
  if (items.length === 0) {
    return null;
  }

  const toneStyles = {
    emerald: "border-emerald-500/20 bg-emerald-500/10 text-emerald-100",
    amber: "border-amber-500/20 bg-amber-500/10 text-amber-100",
    blue: "border-blue-500/20 bg-blue-500/10 text-blue-100",
  } satisfies Record<typeof tone, string>;

  return (
    <div className={`rounded-xl border p-4 ${toneStyles[tone]}`}>
      <div className="mb-2 text-xs uppercase tracking-[0.16em] text-slate-300">{title}</div>
      <div className="space-y-2">
        {items.map((item) => (
          <div key={item} className="text-sm leading-6">
            {localizeFreeformText(item, locale)}
          </div>
        ))}
      </div>
    </div>
  );
}

function CodingTaskStageCard({ stage }: { stage: CodingTaskStageSummary }) {
  const t = useTranslations("report");
  const locale = useLocale();

  return (
    <div className="rounded-xl border border-slate-700 bg-slate-900/60 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="text-sm font-semibold text-white">{localizeFreeformText(stage.stage_title, locale)}</div>
        <div className="text-right">
          {stage.stage_score != null && (
            <div className="text-sm font-bold text-cyan-300">
              {t("codingTask.stageScore")}: {stage.stage_score.toFixed(1)}
            </div>
          )}
          {stage.average_answer_quality != null && (
            <div className="text-[11px] text-slate-500">
              {t("codingTask.answerQuality")}: {stage.average_answer_quality.toFixed(1)}
            </div>
          )}
        </div>
      </div>
      {stage.question_numbers.length > 0 && (
        <div className="mt-2 text-xs text-slate-500">
          {t("codingTask.questionsCovered", { count: stage.question_numbers.length })}: {stage.question_numbers.join(", ")}
        </div>
      )}
      <div className="mt-3 space-y-2">
        {stage.evidence_items.length > 0 ? stage.evidence_items.map((item, index) => (
          <div key={index} className="text-sm leading-6 text-slate-300">
            {localizeFreeformText(item, locale)}
          </div>
        )) : (
          <div className="text-sm text-slate-500">{t("codingTask.noEvidence")}</div>
        )}
      </div>
    </div>
  );
}

function CodingTaskRubricCard({ rubric }: { rubric: CodingTaskRubricScore }) {
  const t = useTranslations("report");

  return (
    <div className="rounded-xl border border-cyan-500/15 bg-slate-900/60 px-3 py-3">
      <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">
        {t(`codingTask.rubrics.${rubric.rubric_key}`)}
      </div>
      <div className="mt-1 text-xl font-semibold text-white">
        {rubric.score != null ? `${rubric.score.toFixed(1)}/10` : "—"}
      </div>
    </div>
  );
}

function CodingTaskCoverageCheckCard({ check }: { check: CodingTaskCoverageCheck }) {
  const t = useTranslations("report");
  const locale = useLocale();
  const statusStyles: Record<string, string> = {
    passed: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
    partial: "border-yellow-500/30 bg-yellow-500/10 text-yellow-200",
    missed: "border-slate-700 bg-slate-900/60 text-slate-300",
  };
  const style = statusStyles[check.status] ?? statusStyles.missed;

  return (
    <div className={`rounded-xl border p-4 ${style}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="text-sm font-medium">{localizeFreeformText(check.title, locale)}</div>
        <div className="text-right">
          <div className="text-[11px] uppercase tracking-[0.16em]">
            {t(`codingTask.checkStatus.${check.status}`)}
          </div>
          {check.score != null && <div className="mt-1 text-sm font-semibold">{check.score.toFixed(1)}/10</div>}
        </div>
      </div>
      {check.evidence && <div className="mt-3 text-sm leading-6 opacity-90">{localizeFreeformText(check.evidence, locale)}</div>}
    </div>
  );
}

function SqlLiveSummaryPanel({ summary }: { summary: NonNullable<AssessmentReport["sql_live_summary"]> }) {
  const t = useTranslations("report");
  const locale = useLocale();

  return (
    <div className="mb-6 rounded-2xl border border-amber-500/20 bg-amber-500/10 p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-[0.24em] text-amber-300">{t("sqlLive.eyebrow")}</div>
          <div className="text-sm font-semibold text-white">{summary.module_title || t("sqlLive.title")}</div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full border border-amber-400/20 bg-slate-900/50 px-3 py-1 text-xs text-slate-200">
            {t("sqlLive.stageCount", { count: summary.stage_count })}
          </span>
          {summary.overall_score != null && (
            <span className="rounded-full border border-amber-400/20 bg-amber-950/40 px-3 py-1 text-xs font-semibold text-amber-200">
              {t("sqlLive.overallScore")}: {summary.overall_score.toFixed(1)}/10
            </span>
          )}
          {summary.validation_score != null && (
            <span className="rounded-full border border-emerald-400/20 bg-emerald-950/40 px-3 py-1 text-xs font-semibold text-emerald-200">
              {t("sqlLive.validationScore")}: {summary.validation_score.toFixed(1)}/10
            </span>
          )}
        </div>
      </div>

      {summary.scenario_title && (
        <div className="mb-3">
          <div className="text-xs uppercase tracking-[0.16em] text-slate-500">{t("sqlLive.task")}</div>
          <div className="mt-1 text-sm font-medium text-white">{localizeFreeformText(summary.scenario_title, locale)}</div>
        </div>
      )}
      {summary.scenario_prompt && (
        <p className="mb-4 text-sm leading-6 text-slate-300">{localizeFreeformText(summary.scenario_prompt, locale)}</p>
      )}

      {summary.rubric_scores.length > 0 && (
        <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {summary.rubric_scores.map((rubric) => (
            <SqlLiveRubricCard key={rubric.rubric_key} rubric={rubric} />
          ))}
        </div>
      )}

      {summary.query_excerpt && (
        <div className="mb-4 rounded-xl border border-slate-700 bg-slate-950/70 p-4">
          <div className="mb-2 text-xs uppercase tracking-[0.16em] text-slate-500">{t("sqlLive.queryExcerpt")}</div>
          <pre className="overflow-x-auto whitespace-pre-wrap text-sm leading-6 text-slate-200">{summary.query_excerpt}</pre>
        </div>
      )}

      {summary.validation_checks.length > 0 && (
        <div className="mb-4">
          <div className="mb-2 text-xs uppercase tracking-[0.16em] text-slate-500">{t("sqlLive.validationChecks")}</div>
          <div className="grid gap-3 lg:grid-cols-2">
            {summary.validation_checks.map((check) => (
              <CodingTaskCoverageCheckCard key={check.check_key} check={check} />
            ))}
          </div>
        </div>
      )}

      <div className="grid gap-3 md:grid-cols-3">
        {summary.stages.map((stage) => (
          <SqlLiveStageCard key={stage.stage_key} stage={stage} />
        ))}
      </div>
    </div>
  );
}

function SqlLiveStageCard({ stage }: { stage: SqlLiveStageSummary }) {
  const t = useTranslations("report");
  const locale = useLocale();

  return (
    <div className="rounded-xl border border-slate-700 bg-slate-900/60 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="text-sm font-semibold text-white">{localizeFreeformText(stage.stage_title, locale)}</div>
        <div className="text-right">
          {stage.stage_score != null && (
            <div className="text-sm font-bold text-amber-300">
              {t("sqlLive.stageScore")}: {stage.stage_score.toFixed(1)}
            </div>
          )}
          {stage.average_answer_quality != null && (
            <div className="text-[11px] text-slate-500">
              {t("sqlLive.answerQuality")}: {stage.average_answer_quality.toFixed(1)}
            </div>
          )}
        </div>
      </div>
      {stage.question_numbers.length > 0 && (
        <div className="mt-2 text-xs text-slate-500">
          {t("sqlLive.questionsCovered", { count: stage.question_numbers.length })}: {stage.question_numbers.join(", ")}
        </div>
      )}
      <div className="mt-3 space-y-2">
        {stage.evidence_items.length > 0 ? stage.evidence_items.map((item, index) => (
          <div key={index} className="text-sm leading-6 text-slate-300">
            {localizeFreeformText(item, locale)}
          </div>
        )) : (
          <div className="text-sm text-slate-500">{t("sqlLive.noEvidence")}</div>
        )}
      </div>
    </div>
  );
}

function SqlLiveRubricCard({ rubric }: { rubric: SqlLiveRubricScore }) {
  const t = useTranslations("report");

  return (
    <div className="rounded-xl border border-amber-500/15 bg-slate-900/60 px-3 py-3">
      <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">
        {t(`sqlLive.rubrics.${rubric.rubric_key}`)}
      </div>
      <div className="mt-1 text-xl font-semibold text-white">
        {rubric.score != null ? `${rubric.score.toFixed(1)}/10` : "—"}
      </div>
    </div>
  );
}

function WrittenCommunicationSummaryPanel({ summary }: { summary: NonNullable<AssessmentReport["written_communication_summary"]> }) {
  const t = useTranslations("report");
  const locale = useLocale();

  return (
    <div className="mb-6 rounded-2xl border border-sky-500/20 bg-sky-500/10 p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-[0.24em] text-sky-300">{t("writtenCommunication.eyebrow")}</div>
          <div className="text-sm font-semibold text-white">{summary.module_title || t("writtenCommunication.title")}</div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full border border-sky-400/20 bg-slate-900/50 px-3 py-1 text-xs text-slate-200">
            {t("writtenCommunication.stageCount", { count: summary.stage_count })}
          </span>
          {summary.overall_score != null && (
            <span className="rounded-full border border-sky-400/20 bg-sky-950/40 px-3 py-1 text-xs font-semibold text-sky-200">
              {t("writtenCommunication.overallScore")}: {summary.overall_score.toFixed(1)}/10
            </span>
          )}
          {summary.clarity_score != null && (
            <span className="rounded-full border border-emerald-400/20 bg-emerald-950/40 px-3 py-1 text-xs font-semibold text-emerald-200">
              {t("writtenCommunication.clarityScore")}: {summary.clarity_score.toFixed(1)}/10
            </span>
          )}
          {summary.structure_score != null && (
            <span className="rounded-full border border-violet-400/20 bg-violet-950/40 px-3 py-1 text-xs font-semibold text-violet-200">
              {t("writtenCommunication.structureScore")}: {summary.structure_score.toFixed(1)}/10
            </span>
          )}
          {summary.audience_awareness_score != null && (
            <span className="rounded-full border border-amber-400/20 bg-amber-950/40 px-3 py-1 text-xs font-semibold text-amber-200">
              {t("writtenCommunication.audienceScore")}: {summary.audience_awareness_score.toFixed(1)}/10
            </span>
          )}
        </div>
      </div>

      {summary.scenario_title && (
        <div className="mb-3">
          <div className="text-xs uppercase tracking-[0.16em] text-slate-500">{t("writtenCommunication.task")}</div>
          <div className="mt-1 text-sm font-medium text-white">{localizeFreeformText(summary.scenario_title, locale)}</div>
        </div>
      )}
      {summary.scenario_prompt && (
        <p className="mb-4 text-sm leading-6 text-slate-300">{localizeFreeformText(summary.scenario_prompt, locale)}</p>
      )}
      {summary.workspace_hint && (
        <p className="mb-4 text-sm leading-6 text-slate-400">{localizeFreeformText(summary.workspace_hint, locale)}</p>
      )}

      {summary.rubric_scores.length > 0 && (
        <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {summary.rubric_scores.map((rubric) => (
            <WrittenCommunicationRubricCard key={rubric.rubric_key} rubric={rubric} />
          ))}
        </div>
      )}

      {(summary.strengths.length > 0 || summary.gaps.length > 0 || summary.next_steps.length > 0) && (
        <div className="mb-4 grid gap-3 lg:grid-cols-3">
          <CodingTaskInsightList title={t("writtenCommunication.strengths")} tone="emerald" items={summary.strengths} />
          <CodingTaskInsightList title={t("writtenCommunication.gaps")} tone="amber" items={summary.gaps} />
          <CodingTaskInsightList title={t("writtenCommunication.nextSteps")} tone="blue" items={summary.next_steps} />
        </div>
      )}

      {summary.writing_excerpt && (
        <div className="mb-4 rounded-xl border border-slate-700 bg-slate-950/70 p-4">
          <div className="mb-2 text-xs uppercase tracking-[0.16em] text-slate-500">{t("writtenCommunication.writingExcerpt")}</div>
          <pre className="overflow-x-auto whitespace-pre-wrap text-sm leading-6 text-slate-200">
            {localizeFreeformText(summary.writing_excerpt, locale)}
          </pre>
        </div>
      )}

      <div className="grid gap-3 md:grid-cols-3">
        {summary.stages.map((stage) => (
          <WrittenCommunicationStageCard key={stage.stage_key} stage={stage} />
        ))}
      </div>
    </div>
  );
}

function WrittenCommunicationStageCard({ stage }: { stage: NonNullable<AssessmentReport["written_communication_summary"]>["stages"][number] }) {
  const t = useTranslations("report");
  const locale = useLocale();

  return (
    <div className="rounded-xl border border-slate-700 bg-slate-900/60 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="text-sm font-semibold text-white">{localizeFreeformText(stage.stage_title, locale)}</div>
        <div className="text-right">
          {stage.stage_score != null && (
            <div className="text-sm font-bold text-sky-300">
              {t("writtenCommunication.stageScore")}: {stage.stage_score.toFixed(1)}
            </div>
          )}
          {stage.average_answer_quality != null && (
            <div className="text-[11px] text-slate-500">
              {t("writtenCommunication.answerQuality")}: {stage.average_answer_quality.toFixed(1)}
            </div>
          )}
        </div>
      </div>
      {stage.question_numbers.length > 0 && (
        <div className="mt-2 text-xs text-slate-500">
          {t("writtenCommunication.questionsCovered", { count: stage.question_numbers.length })}: {stage.question_numbers.join(", ")}
        </div>
      )}
      <div className="mt-3 space-y-2">
        {stage.evidence_items.length > 0 ? stage.evidence_items.map((item, index) => (
          <div key={index} className="text-sm leading-6 text-slate-300">
            {localizeFreeformText(item, locale)}
          </div>
        )) : (
          <div className="text-sm text-slate-500">{t("writtenCommunication.noEvidence")}</div>
        )}
      </div>
    </div>
  );
}

function WrittenCommunicationRubricCard({ rubric }: { rubric: NonNullable<AssessmentReport["written_communication_summary"]>["rubric_scores"][number] }) {
  const t = useTranslations("report");

  return (
    <div className="rounded-xl border border-sky-500/15 bg-slate-900/60 px-3 py-3">
      <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">
        {t(`writtenCommunication.rubrics.${rubric.rubric_key}`)}
      </div>
      <div className="mt-1 text-xl font-semibold text-white">
        {rubric.score != null ? `${rubric.score.toFixed(1)}/10` : "—"}
      </div>
    </div>
  );
}

function SummaryCard({
  summary,
  recommendationConfig,
}: {
  summary: ReportSummaryBlock;
  recommendationConfig: Record<HiringRecommendation, { label: string; color: string; bg: string }>;
}) {
  const t = useTranslations("report");
  const locale = useLocale();
  const rec = recommendationConfig[summary.hiring_recommendation] ?? recommendationConfig.maybe;
  const score = summary.score ?? 0;
  const scoreColor =
    score >= 7 ? "text-green-400" : score >= 5 ? "text-yellow-400" : "text-red-400";
  const ringColor =
    score >= 7 ? "border-green-500/50" : score >= 5 ? "border-yellow-500/50" : "border-red-500/50";

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-2xl p-6 mb-6 flex flex-col sm:flex-row gap-6 items-start sm:items-center">
      {/* Score circle */}
      <div className={`w-20 h-20 rounded-full border-4 ${ringColor} flex flex-col items-center justify-center shrink-0`}>
        <span className={`text-2xl font-bold ${scoreColor}`}>{score.toFixed(1)}</span>
        <span className="text-slate-500 text-xs">{t("scoreOutOfTen")}</span>
      </div>

      {/* Right side */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-3">
          <span className={`inline-flex items-center gap-1.5 border rounded-full px-3 py-1 text-xs font-semibold ${rec.bg} ${rec.color}`}>
            {rec.label}
          </span>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {summary.top_strengths.length > 0 && (
            <div>
              <p className="text-green-400 text-xs font-semibold uppercase tracking-wide mb-1">{t("strengths")}</p>
              <ul className="space-y-1">
                {summary.top_strengths.map((s, i) => (
                  <li key={i} className="text-slate-300 text-sm flex gap-2">
                    <span className="text-green-400 shrink-0">+</span>{localizeFreeformText(s, locale)}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {summary.top_weaknesses.length > 0 && (
            <div>
              <p className="text-yellow-400 text-xs font-semibold uppercase tracking-wide mb-1">{t("toImprove")}</p>
              <ul className="space-y-1">
                {summary.top_weaknesses.map((w, i) => (
                  <li key={i} className="text-slate-300 text-sm flex gap-2">
                    <span className="text-yellow-400 shrink-0">-</span>{localizeFreeformText(w, locale)}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function RoadmapPanel({ phases }: { phases: DevelopmentRoadmapPhase[] }) {
  const t = useTranslations("report");
  const locale = useLocale();

  return (
    <div className="mb-6 rounded-2xl border border-emerald-500/20 bg-emerald-500/10 p-5">
      <div className="mb-4">
        <div className="text-xs uppercase tracking-[0.24em] text-emerald-300">{t("roadmap.eyebrow")}</div>
        <div className="text-sm font-semibold text-white">{t("roadmap.title")}</div>
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        {phases.map((phase) => (
          <div key={phase.phase_key} className="rounded-xl border border-slate-700 bg-slate-900/60 p-4">
            <div className="mb-2 text-[11px] uppercase tracking-[0.18em] text-emerald-300">
              {t(`roadmap.phases.${phase.phase_key}.label`)}
            </div>
            {phase.focus && (
              <div className="mb-3 text-sm font-medium leading-6 text-white">
                {localizeFreeformText(phase.focus, locale)}
              </div>
            )}
            <div className="space-y-2">
              {phase.actions.map((action, index) => (
                <div key={index} className="flex gap-2 text-sm leading-6 text-slate-300">
                  <span className="mt-1 shrink-0 text-emerald-400">•</span>
                  <span>{localizeFreeformText(action, locale)}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function localizeInterviewBlock(block: string, locale: string): string {
  const normalized = String(block || "").trim().toLowerCase();
  if (locale === "ru") {
    const labels: Record<string, string> = {
      intro: "Вводный блок",
      resume_followup: "Разбор резюме",
      technical_foundation: "Техническая база",
      technical_depth: "Техническая глубина",
      behavioral_closing: "Финальный behavioral-блок",
    };
    return labels[normalized] ?? block;
  }
  const labels: Record<string, string> = {
    intro: "Intro",
    resume_followup: "Resume follow-up",
    technical_foundation: "Technical foundation",
    technical_depth: "Technical depth",
    behavioral_closing: "Behavioral closing",
  };
  return labels[normalized] ?? block;
}

function ExplainabilityPanel({
  explainability,
}: {
  explainability: NonNullable<AssessmentReport["explainability_report"]>;
}) {
  const t = useTranslations("report");
  const locale = useLocale();
  const overall = explainability.overall_assessment;
  const trace = explainability.scoring_trace;
  const recommendationLabelMap: Record<HiringRecommendation, string> = {
    strong_yes: t("labels.strongYes"),
    yes: t("labels.yes"),
    maybe: t("labels.maybe"),
    no: t("labels.no"),
  };
  const scoreDelta = (trace.post_penalty_overall_score ?? 0) - (trace.pre_penalty_overall_score ?? 0);
  const signalQualityLabel = t(`summaryModel.signal.${overall.signal_quality}` as "summaryModel.signal.high");

  return (
    <div className="mb-6 rounded-2xl border border-fuchsia-500/20 bg-fuchsia-500/10 p-5">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-[0.24em] text-fuchsia-300">{t("explainability.eyebrow")}</div>
          <div className="text-sm font-semibold text-white">{t("explainability.title")}</div>
          <div className="mt-1 max-w-3xl text-sm leading-6 text-slate-300">
            {localizeFreeformText(overall.summary, locale)}
          </div>
        </div>
        <div className="flex flex-wrap gap-2 text-xs">
          <span className="rounded-full border border-fuchsia-400/30 bg-fuchsia-950/40 px-3 py-1 text-fuchsia-200">
            {t("recommendation")}: {recommendationLabelMap[overall.recommendation] ?? overall.recommendation}
          </span>
          <span className="rounded-full border border-slate-700 bg-slate-950 px-3 py-1 text-slate-300">
            {signalQualityLabel}
          </span>
        </div>
      </div>

      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <ConfidenceStatCard label={t("overallScore")} value={`${overall.overall_score.toFixed(1)}/10`} highlight />
        <ConfidenceStatCard
          label={t("confidence.overall")}
          value={overall.overall_confidence != null ? `${Math.round(overall.overall_confidence * 100)}%` : "—"}
        />
        <ConfidenceStatCard
          label={t("explainability.scoreDelta")}
          value={`${scoreDelta > 0 ? "+" : ""}${scoreDelta.toFixed(1)}`}
        />
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        <div className="rounded-xl border border-emerald-500/20 bg-slate-900/60 p-4">
          <div className="mb-2 text-xs uppercase tracking-[0.18em] text-emerald-300">{t("explainability.strengthsTitle")}</div>
          <div className="space-y-3">
            {explainability.evidence_based_strengths.length === 0 ? (
              <div className="text-sm text-slate-500">{t("empty")}</div>
            ) : (
              explainability.evidence_based_strengths.map((item, idx) => (
                <div key={`${item.title}-${idx}`} className="rounded-lg border border-slate-700 bg-slate-950/70 p-3">
                  <div className="text-sm font-medium text-white">{localizeFreeformText(item.title, locale)}</div>
                  <div className="mt-1 text-xs leading-5 text-slate-300">{localizeFreeformText(item.why_it_matters, locale)}</div>
                  {item.evidence.length > 0 && (
                    <div className="mt-2 text-xs text-slate-400">
                      Q{item.evidence[0].question_number}: {localizeFreeformText(item.evidence[0].evidence_excerpt, locale)}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>

        <div className="rounded-xl border border-amber-500/20 bg-slate-900/60 p-4">
          <div className="mb-2 text-xs uppercase tracking-[0.18em] text-amber-300">{t("explainability.gapsTitle")}</div>
          <div className="space-y-3">
            {explainability.evidence_based_gaps.length === 0 ? (
              <div className="text-sm text-slate-500">{t("empty")}</div>
            ) : (
              explainability.evidence_based_gaps.map((item, idx) => (
                <div key={`${item.title}-${idx}`} className="rounded-lg border border-slate-700 bg-slate-950/70 p-3">
                  <div className="text-sm font-medium text-white">{localizeFreeformText(item.title, locale)}</div>
                  <div className="mt-1 text-xs leading-5 text-slate-300">{localizeFreeformText(item.risk, locale)}</div>
                  {item.evidence.length > 0 && (
                    <div className="mt-2 text-xs text-slate-400">
                      Q{item.evidence[0].question_number}: {localizeFreeformText(item.evidence[0].evidence_excerpt, locale)}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>

        <div className="rounded-xl border border-blue-500/20 bg-slate-900/60 p-4">
          <div className="mb-2 text-xs uppercase tracking-[0.18em] text-blue-300">{t("explainability.growthPlanTitle")}</div>
          <div className="space-y-3">
            {explainability.growth_recommendations.length === 0 ? (
              <div className="text-sm text-slate-500">{t("empty")}</div>
            ) : (
              explainability.growth_recommendations.map((item, idx) => (
                <div key={`${item.title}-${idx}`} className="rounded-lg border border-slate-700 bg-slate-950/70 p-3">
                  <div className="text-sm font-medium text-white">{localizeFreeformText(item.title, locale)}</div>
                  {item.linked_gap && (
                    <div className="mt-1 text-xs text-slate-400">
                      {t("explainability.linkedGap")}: {localizeFreeformText(item.linked_gap, locale)}
                    </div>
                  )}
                  <ul className="mt-2 space-y-1 text-xs text-slate-300">
                    {item.actions.map((action, actionIndex) => (
                      <li key={`${item.title}-action-${actionIndex}`} className="flex gap-2">
                        <span className="mt-1 text-blue-300">•</span>
                        <span>{localizeFreeformText(action, locale)}</span>
                      </li>
                    ))}
                  </ul>
                  <div className="mt-2 text-xs text-slate-400">
                    {t("explainability.successCriteria")}: {localizeFreeformText(item.success_criteria, locale)}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {(trace.penalty_explanations.length > 0 || trace.top_block_signals.length > 0) && (
        <div className="mt-4 rounded-xl border border-slate-700 bg-slate-900/60 p-4">
          <div className="mb-2 text-xs uppercase tracking-[0.18em] text-fuchsia-300">{t("explainability.scoringTraceTitle")}</div>
          {trace.penalty_explanations.length > 0 && (
            <div className="mb-3 space-y-2">
              {trace.penalty_explanations.map((item, idx) => (
                <div key={`${item}-${idx}`} className="text-xs leading-5 text-slate-300">
                  • {localizeFreeformText(item, locale)}
                </div>
              ))}
            </div>
          )}
          {trace.top_block_signals.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {trace.top_block_signals.map((item, idx) => (
                <span
                  key={`${item.block}-${idx}`}
                  className="rounded-full border border-slate-700 bg-slate-950 px-3 py-1 text-xs text-slate-200"
                >
                  {localizeInterviewBlock(item.block, locale)} · {item.score.toFixed(1)} · {Math.round(item.weight * 100)}%
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function localizeConfidenceReason(text: string, locale: string) {
  if (locale !== "ru") return text;

  const translations: Record<string, string> = {
    "No per-question evidence extracted; confidence is limited.": "По ответам не удалось извлечь достаточно подтверждений, поэтому надёжность сигнала ограничена.",
    "Low concrete evidence coverage reduced confidence.": "Низкое покрытие конкретными подтверждениями снизило надёжность сигнала.",
    "High evidence coverage increased confidence.": "Высокое покрытие конкретными подтверждениями повысило надёжность сигнала.",
    "Multiple low-confidence answers reduced certainty.": "Несколько слабых ответов снизили уверенность в выводах.",
    "Several answers contained high-confidence evidence.": "Несколько ответов содержали сильные конкретные подтверждения.",
    "High AI-likelihood signal lowered confidence.": "Высокая вероятность ИИ-генерации снизила надёжность сигнала.",
    "Low AI-likelihood signal improved confidence.": "Низкая вероятность ИИ-генерации повысила надёжность сигнала.",
    "Confidence derived from mixed evidence quality signals.": "Надёжность сигнала сформирована из смешанного качества подтверждений.",
  };

  return translations[text] ?? text;
}

function formatQuestionCountLabel(count: number, locale: string): string {
  if (locale !== "ru") {
    return `${count} question${count === 1 ? "" : "s"}`;
  }

  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return `${count} вопрос`;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return `${count} вопроса`;
  return `${count} вопросов`;
}

function formatQuestionCountPrepositional(count: number, locale: string): string {
  if (locale !== "ru") {
    return formatQuestionCountLabel(count, locale);
  }

  return `${count} ${count === 1 ? "вопросе" : "вопросах"}`;
}

function formatCompetencyCoverageHint(count: number, locale: string): string {
  if (locale === "ru") {
    return `Основано на ${formatQuestionCountPrepositional(count, locale)}`;
  }
  return `Based on ${formatQuestionCountLabel(count, locale)}`;
}

function getEvidenceMetric(
  evidenceCoverage: Record<string, unknown> | null | undefined,
  key: string,
): number | null {
  const raw = evidenceCoverage?.[key];
  return typeof raw === "number" && Number.isFinite(raw) ? raw : null;
}

function formatPercent(value: number | null): string {
  if (value == null) return "—";
  return `${Math.round(value * 100)}%`;
}

function getConfidenceLevel(value: number | null): "high" | "medium" | "low" | null {
  if (value == null) return null;
  if (value >= 0.75) return "high";
  if (value >= 0.5) return "medium";
  return "low";
}

function ConfidencePanel({ report, locale }: { report: AssessmentReport; locale: string }) {
  const t = useTranslations("report");
  const overallConfidence = typeof report.overall_confidence === "number" ? report.overall_confidence : null;
  const confidenceLevel = getConfidenceLevel(overallConfidence);
  const competencyQuestionCounts = new Map<string, number>();
  for (const qa of report.per_question_analysis ?? []) {
    for (const competency of qa.targeted_competencies ?? []) {
      competencyQuestionCounts.set(competency, (competencyQuestionCounts.get(competency) ?? 0) + 1);
    }
  }
  const competencyConfidence = Object.entries(report.competency_confidence ?? {})
    .filter((entry): entry is [string, number] => typeof entry[1] === "number" && Number.isFinite(entry[1]))
    .sort((a, b) => b[1] - a[1]);
  const questionsAnalyzed = getEvidenceMetric(report.evidence_coverage, "questions_analyzed");
  const highConfidenceQuestions = getEvidenceMetric(report.evidence_coverage, "high_confidence_questions");
  const lowConfidenceQuestions = getEvidenceMetric(report.evidence_coverage, "low_confidence_questions");
  const concreteEvidenceRatio = getEvidenceMetric(report.evidence_coverage, "concrete_evidence_ratio");
  const avgAiLikelihood = getEvidenceMetric(report.evidence_coverage, "avg_ai_likelihood");
  const confidenceReasons = (report.confidence_reasons ?? []).filter(Boolean);

  const hasData = Boolean(
    overallConfidence != null ||
    report.decision_policy_version ||
    competencyConfidence.length > 0 ||
    questionsAnalyzed != null ||
    highConfidenceQuestions != null ||
    lowConfidenceQuestions != null ||
    concreteEvidenceRatio != null ||
    avgAiLikelihood != null ||
    confidenceReasons.length > 0,
  );

  if (!hasData) return null;

  const levelStyles: Record<NonNullable<typeof confidenceLevel>, string> = {
    high: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
    medium: "border-yellow-500/30 bg-yellow-500/10 text-yellow-200",
    low: "border-rose-500/30 bg-rose-500/10 text-rose-200",
  };

  return (
    <div className="mb-6 rounded-2xl border border-sky-500/20 bg-sky-500/10 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-[0.24em] text-sky-300">{t("confidence.eyebrow")}</div>
          <div className="text-sm font-semibold text-white">{t("confidence.title")}</div>
          <div className="mt-1 max-w-2xl text-sm leading-6 text-slate-300">{t("confidence.description")}</div>
        </div>
        <div className="flex flex-wrap gap-2 text-xs">
          {confidenceLevel && (
            <span className={`rounded-full border px-3 py-1 ${levelStyles[confidenceLevel]}`}>
              {t(`confidence.levels.${confidenceLevel}`)}
            </span>
          )}
          <span className="rounded-full border border-slate-700 bg-slate-950 px-3 py-1 text-slate-300">
            {t("confidence.policyVersion")}: {report.decision_policy_version ?? t("confidence.notAvailable")}
          </span>
        </div>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <ConfidenceStatCard label={t("confidence.overall")} value={formatPercent(overallConfidence)} highlight />
        <ConfidenceStatCard label={t("confidence.questionsAnalyzed")} value={questionsAnalyzed != null ? String(questionsAnalyzed) : "—"} />
        <ConfidenceStatCard label={t("confidence.highConfidenceQuestions")} value={highConfidenceQuestions != null ? String(highConfidenceQuestions) : "—"} />
        <ConfidenceStatCard label={t("confidence.lowConfidenceQuestions")} value={lowConfidenceQuestions != null ? String(lowConfidenceQuestions) : "—"} />
        <ConfidenceStatCard label={t("confidence.concreteEvidenceRatio")} value={formatPercent(concreteEvidenceRatio)} />
      </div>

      <div className="mt-3">
        <ConfidenceStatCard label={t("confidence.avgAiLikelihood")} value={formatPercent(avgAiLikelihood)} />
      </div>

      {confidenceReasons.length > 0 && (
        <div className="mt-4">
          <div className="mb-2 text-xs uppercase tracking-[0.18em] text-sky-300">{t("confidence.reasons")}</div>
          <div className="space-y-2">
            {confidenceReasons.map((reason) => (
              <div key={reason} className="flex gap-2 rounded-xl border border-slate-700 bg-slate-900/60 px-3 py-2 text-sm text-slate-300">
                <span className="mt-1 shrink-0 text-sky-300">•</span>
                <span>{localizeConfidenceReason(reason, locale)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {competencyConfidence.length > 0 && (
        <div className="mt-4">
          <div className="mb-2 text-xs uppercase tracking-[0.18em] text-sky-300">{t("confidence.competency")}</div>
          <div className="grid gap-2 md:grid-cols-2">
            {competencyConfidence.map(([name, value]) => (
              <div key={name} className="rounded-xl border border-slate-700 bg-slate-900/60 px-3 py-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm text-white">{localizeCompetencyLabel(name, locale)}</div>
                  <div className="text-xs font-semibold text-sky-300">{formatPercent(value)}</div>
                </div>
                {(competencyQuestionCounts.get(name) ?? 0) > 0 && (
                  <div className="mt-1 text-xs text-slate-500">
                    {formatCompetencyCoverageHint(competencyQuestionCounts.get(name) ?? 0, locale)}
                  </div>
                )}
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-700">
                  <div className="h-full rounded-full bg-sky-400" style={{ width: `${Math.round(value * 100)}%` }} />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ConfidenceStatCard({
  label,
  value,
  highlight = false,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <div className={`rounded-xl border px-3 py-3 ${highlight ? "border-sky-400/30 bg-sky-950/40" : "border-slate-700 bg-slate-900/60"}`}>
      <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">{label}</div>
      <div className={`mt-1 text-xl font-semibold ${highlight ? "text-sky-200" : "text-white"}`}>{value}</div>
    </div>
  );
}

function ScoreCard({ label, score, highlight = false }: { label: string; score: number | null; highlight?: boolean }) {
  const t = useTranslations("report");
  const value = score ?? 0;
  const pct = (value / 10) * 100;
  return (
    <div className={`bg-slate-800 border rounded-xl p-4 ${highlight ? "border-blue-500/40" : "border-slate-700"}`}>
      <div className="text-slate-400 text-xs mb-2">{label}</div>
      <div className={`text-2xl font-bold mb-2 ${highlight ? "text-blue-400" : "text-white"}`}>
        {value.toFixed(1)}
        <span className="text-slate-500 text-sm font-normal">{t("scoreOutOfTen")}</span>
      </div>
      <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${highlight ? "bg-blue-500" : "bg-slate-400"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function CompetencyHeatmap({ scores }: { scores: CompetencyScore[] }) {
  const t = useTranslations("report");
  const locale = useLocale();
  // Group by category
  const groups: Record<string, CompetencyScore[]> = {};
  for (const cs of scores) {
    if (!groups[cs.category]) groups[cs.category] = [];
    groups[cs.category].push(cs);
  }

  return (
    <div className="space-y-4">
      {Object.entries(groups).map(([category, items]) => (
        <div key={category}>
          <div className="text-xs text-slate-500 uppercase tracking-wide mb-2">
            {getCategoryLabel(t, category)}
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {items.map((cs, i) => {
              const cellClass =
                cs.score >= 7
                  ? "bg-green-500/30 border-green-500/50 text-green-300"
                  : cs.score >= 5
                  ? "bg-yellow-500/30 border-yellow-500/50 text-yellow-300"
                  : "bg-red-500/30 border-red-500/50 text-red-300";
              return (
                <div key={i} className={`border rounded-lg px-3 py-2 ${cellClass}`}>
                  <div className="text-xs font-medium truncate">{localizeCompetencyLabel(cs.competency, locale)}</div>
                  <div className="text-lg font-bold mt-0.5">{cs.score.toFixed(1)}</div>
                  {cs.evidence && (
                    <div className="text-xs opacity-70 mt-1 line-clamp-2">{localizeEvidenceText(cs.evidence, locale)}</div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

function SkillMatrix({ tags }: { tags: SkillTag[] }) {
  const t = useTranslations("report");
  const strong = tags.filter((t) => t.proficiency === "expert" || t.proficiency === "advanced");
  const develop = tags.filter((t) => t.proficiency === "beginner" || t.proficiency === "intermediate");

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
      <div>
        <div className="text-xs text-green-400 uppercase tracking-wide font-semibold mb-2">
          {t("strongSkills")} ({t("strengthBand")})
        </div>
        <div className="flex flex-wrap gap-1.5">
          {strong.length === 0 ? (
            <span className="text-slate-500 text-xs">{t("empty")}</span>
          ) : (
            strong.map((tag, i) => (
              <span key={i} className="px-2.5 py-1 rounded-full text-xs font-medium bg-green-500/20 text-green-400">
                {tag.skill}
                {tag.mentions_count > 1 && <span className="ml-1 opacity-60">x{tag.mentions_count}</span>}
              </span>
            ))
          )}
        </div>
      </div>
      <div>
        <div className="text-xs text-yellow-400 uppercase tracking-wide font-semibold mb-2">
          {t("developSkills")} ({t("developBand")})
        </div>
        <div className="flex flex-wrap gap-1.5">
          {develop.length === 0 ? (
            <span className="text-slate-500 text-xs">{t("empty")}</span>
          ) : (
            develop.map((tag, i) => (
              <span key={i} className="px-2.5 py-1 rounded-full text-xs font-medium bg-yellow-500/20 text-yellow-400">
                {tag.skill}
                {tag.mentions_count > 1 && <span className="ml-1 opacity-60">x{tag.mentions_count}</span>}
              </span>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

function CompetencyRow({ cs }: { cs: CompetencyScore }) {
  const t = useTranslations("report");
  const locale = useLocale();
  const pct = (cs.score / 10) * 100;
  const categoryColor = CATEGORY_COLORS[cs.category] ?? "bg-slate-700 text-slate-400 border-slate-600";
  const scoreColor = cs.score >= 7 ? "text-green-400" : cs.score >= 5 ? "text-yellow-400" : "text-red-400";
  const barColor = cs.score >= 7 ? "bg-green-500" : cs.score >= 5 ? "bg-yellow-500" : "bg-red-500";

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-slate-200 text-sm truncate">{localizeCompetencyLabel(cs.competency, locale)}</span>
          <span className={`text-xs px-1.5 py-0.5 rounded border shrink-0 ${categoryColor}`}>
            {getCategoryLabel(t, cs.category)}
          </span>
        </div>
        <span className={`text-sm font-bold shrink-0 ${scoreColor}`}>{cs.score.toFixed(1)}</span>
      </div>
      <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${barColor}`} style={{ width: `${pct}%` }} />
      </div>
      {cs.evidence && (
        <p className="text-slate-500 text-xs">{localizeEvidenceText(cs.evidence, locale)}</p>
      )}
    </div>
  );
}

function SkillBadge({ tag }: { tag: SkillTag }) {
  const color = PROFICIENCY_COLORS[tag.proficiency] ?? PROFICIENCY_COLORS.intermediate;
  return (
    <span className={`px-2.5 py-1 rounded-full text-xs font-medium ${color}`}>
      {tag.skill}
      {tag.mentions_count > 1 && <span className="ml-1 opacity-60">x{tag.mentions_count}</span>}
    </span>
  );
}

function RedFlagRow({ flag }: { flag: RedFlag }) {
  const t = useTranslations("report");
  const locale = useLocale();
  const style = SEVERITY_COLORS[flag.severity] ?? SEVERITY_COLORS.low;
  return (
    <div className={`border rounded-lg px-4 py-3 ${style}`}>
      <div className="flex items-center gap-2 mb-1">
        <span className="text-sm font-medium">{t("alert")}: {localizeFreeformText(flag.flag, locale)}</span>
        <span className="text-xs opacity-70 capitalize">{t(`severity.${flag.severity}`)}</span>
      </div>
      {flag.evidence && <p className="text-xs opacity-80">{localizeFreeformText(flag.evidence, locale)}</p>}
    </div>
  );
}

function QuestionAccordion({ qa, expanded, onToggle }: { qa: QuestionAnalysis; expanded: boolean; onToggle: () => void }) {
  const t = useTranslations("report");
  const locale = useLocale();
  const depthColor: Record<string, string> = {
    expert: "text-green-400",
    strong: "text-blue-400",
    adequate: "text-yellow-400",
    surface: "text-orange-400",
    none: "text-red-400",
  };
  return (
    <div id={`question-analysis-${qa.question_number}`} className="scroll-mt-24 bg-slate-800 border border-slate-700 rounded-lg overflow-hidden">
      <button
        onClick={onToggle}
        className="grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-4 px-5 py-4 text-left transition-colors hover:bg-slate-750 md:gap-6 md:px-6"
      >
        <div className="flex min-w-0 items-center gap-3 pr-2 md:gap-4">
          <span className="text-slate-500 text-xs shrink-0">{t("questionShort", {number: qa.question_number})}</span>
          {qa.stage_title && (
            <span className="rounded-full border border-violet-500/20 bg-violet-500/10 px-2 py-0.5 text-[11px] text-violet-300">
              {localizeFreeformText(qa.stage_title, locale)}
            </span>
          )}
          <span className="min-w-0 text-slate-300 text-sm font-medium leading-6 md:text-[1.02rem]">
            {(qa.targeted_competencies.map((item) => localizeCompetencyLabel(item, locale)).join(", ")) || t("general")}
          </span>
        </div>
        <div className="flex min-w-[132px] items-center justify-end gap-4 pl-2 md:min-w-[156px] md:gap-5">
          <span className={`text-right text-xs font-medium ${depthColor[qa.depth] ?? "text-slate-400"} capitalize md:text-sm`}>{t(`depth.${qa.depth}`)}</span>
          <span className="w-10 text-right text-sm font-bold text-white md:text-base">{qa.answer_quality.toFixed(1)}</span>
          <span className="w-5 text-center text-sm text-slate-500">{expanded ? "▲" : "▼"}</span>
        </div>
      </button>
      {expanded && (
        <div className="space-y-3 border-t border-slate-700 px-5 pb-4 pt-4 md:px-6">
          {qa.evidence && (
            <div>
              <p className="text-slate-500 text-xs uppercase tracking-wide mb-1">{t("evidence")}</p>
              <p className="text-slate-300 text-sm">{localizeEvidenceText(qa.evidence, locale)}</p>
            </div>
          )}
          {qa.why_asked && (
            <div>
              <p className="text-slate-500 text-xs uppercase tracking-wide mb-1">{t("whyAsked")}</p>
              <p className="text-slate-300 text-sm">{localizeFreeformText(qa.why_asked, locale)}</p>
            </div>
          )}
          {qa.what_was_scored && (
            <div>
              <p className="text-slate-500 text-xs uppercase tracking-wide mb-1">{t("whatWasScored")}</p>
              <p className="text-slate-300 text-sm">{localizeFreeformText(qa.what_was_scored, locale)}</p>
            </div>
          )}
          {qa.scored_metrics && qa.scored_metrics.length > 0 && (
            <div>
              <p className="text-slate-500 text-xs uppercase tracking-wide mb-1">{t("scoredMetrics")}</p>
              <div className="flex flex-wrap gap-1.5">
                {qa.scored_metrics.map((metric) => (
                  <span key={metric} className="rounded-full border border-sky-500/30 bg-sky-500/10 px-2 py-0.5 text-xs text-sky-200">
                    {localizeScoredMetric(metric, locale)}
                  </span>
                ))}
              </div>
            </div>
          )}
          {qa.skills_mentioned.length > 0 && (
            <div>
              <p className="text-slate-500 text-xs uppercase tracking-wide mb-1">{t("skillsMentioned")}</p>
              <div className="flex flex-wrap gap-1.5">
                {qa.skills_mentioned.map((s, i) => (
                  <span key={i} className={`px-2 py-0.5 rounded text-xs ${PROFICIENCY_COLORS[s.proficiency] ?? PROFICIENCY_COLORS.intermediate}`}>
                    {s.skill}
                  </span>
                ))}
              </div>
            </div>
          )}
          {qa.red_flags.length > 0 && (
            <div>
              <p className="text-slate-500 text-xs uppercase tracking-wide mb-1">{t("flags")}</p>
              <ul className="space-y-1">
                {qa.red_flags.map((rf, i) => (
                  <li key={i} className="text-red-400 text-xs">{t("alert")}: {localizeFreeformText(rf, locale)}</li>
                ))}
              </ul>
            </div>
          )}
          <div className="flex gap-4 text-xs">
            <span className="text-slate-500">{t("specificity")}: <span className="text-slate-300 capitalize">{t(`specificityValue.${qa.specificity}`)}</span></span>
          </div>
        </div>
      )}
    </div>
  );
}

function Section({ title, children, color }: { title: string; children: React.ReactNode; color: string }) {
  const colors: Record<string, string> = {
    green: "text-green-400",
    yellow: "text-yellow-400",
    blue: "text-blue-400",
    cyan: "text-cyan-400",
    purple: "text-purple-400",
    red: "text-red-400",
  };
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl p-6 mb-4">
      <h2 className={`font-semibold mb-3 ${colors[color] ?? "text-white"}`}>{title}</h2>
      <ul className="space-y-2">{children}</ul>
    </div>
  );
}

function ListItem({ text, bullet, color }: { text: string; bullet: string; color: string }) {
  const locale = useLocale();
  return (
    <li className="flex gap-3 text-sm text-slate-300">
      <span className={`${color} shrink-0 mt-0.5`}>{bullet}</span>
      {localizeFreeformText(text, locale)}
    </li>
  );
}
