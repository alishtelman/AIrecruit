"use client";

import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { useAuth } from "@/hooks/useAuth";
import { reportApi } from "@/lib/api";
import type { AssessmentReport, HiringRecommendation, CompetencyScore, SkillTag, RedFlag, QuestionAnalysis, ReportSummaryBlock, SystemDesignStageSummary, SystemDesignRubricScore, DevelopmentRoadmapPhase, CodingTaskStageSummary, CodingTaskRubricScore, CodingTaskCoverageCheck } from "@/lib/types";

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
  if (locale === "ru" && text === "Mock evidence from response") return "Тестовое подтверждение из ответа";
  if (locale === "ru" && text.startsWith("Mock evidence for ")) {
    const competency = text.slice("Mock evidence for ".length);
    return `Тестовое подтверждение по компетенции «${localizeCompetencyLabel(competency, locale)}»`;
  }
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

function getCategoryLabel(t: ReturnType<typeof useTranslations>, category: string) {
  if (category === "technical_core") return t("labels.technicalCore");
  if (category === "technical_breadth") return t("labels.technicalBreadth");
  if (category === "problem_solving") return t("labels.problemSolving");
  if (category === "communication") return t("labels.communication");
  if (category === "behavioral") return t("labels.behavioral");
  return category;
}

function InterviewSummaryPanel({ summaryModel }: { summaryModel: AssessmentReport["summary_model"] }) {
  const t = useTranslations("report");

  if (!summaryModel) return null;

  const items = [
    { label: t("summaryModel.coreTopics"), value: summaryModel.core_topics },
    { label: t("summaryModel.extraTurns"), value: summaryModel.extra_turns },
    { label: t("summaryModel.coveredCompetencies"), value: summaryModel.covered_competencies },
    { label: t("summaryModel.strongTopics"), value: summaryModel.strong_topics },
    { label: t("summaryModel.honestGaps"), value: summaryModel.honest_gaps },
    { label: t("summaryModel.genericTopics"), value: summaryModel.generic_or_evasive_topics },
  ];

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

        {report.summary_model && <InterviewSummaryPanel summaryModel={report.summary_model} />}
        {report.system_design_summary && <SystemDesignSummaryPanel summary={report.system_design_summary} />}
        {report.coding_task_summary && <CodingTaskSummaryPanel summary={report.coding_task_summary} />}

        {/* Recommendation badge */}
        <div className={`inline-flex items-center gap-2 border rounded-full px-4 py-1.5 text-sm font-semibold mb-6 ${rec.bg} ${rec.color}`}>
          {t("recommendation")}: {rec.label}
        </div>

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
          <div className="mt-6">
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
        </div>
      </div>

      {summary.scenario_title && (
        <div className="mb-3">
          <div className="text-xs uppercase tracking-[0.16em] text-slate-500">{t("codingTask.task")}</div>
          <div className="mt-1 text-sm font-medium text-white">{localizeFreeformText(summary.scenario_title, locale)}</div>
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

      <div className="grid gap-3 md:grid-cols-3">
        {summary.stages.map((stage) => (
          <CodingTaskStageCard key={stage.stage_key} stage={stage} />
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
    <div className="bg-slate-800 border border-slate-700 rounded-lg overflow-hidden">
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
