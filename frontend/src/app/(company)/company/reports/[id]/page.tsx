"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useParams } from "next/navigation";
import { useRouter } from "@/i18n/navigation";
import { CompanyWorkspaceHeader } from "@/components/company-workspace-header";
import { useAuth } from "@/hooks/useAuth";
import { companyApi } from "@/lib/api";
import type { AssessmentReport, HiringRecommendation, CompetencyScore, SkillTag, RedFlag, QuestionAnalysis, ProctoringTimeline, ProctoringTimelineEvent, SystemDesignStageSummary, SystemDesignRubricScore, BehavioralInterviewStageSummary, BehavioralInterviewRubricScore, CodingTaskStageSummary, CodingTaskRubricScore, CodingTaskCoverageCheck, SqlLiveStageSummary, SqlLiveRubricScore } from "@/lib/types";

const RECOMMENDATION_CONFIG: Record<HiringRecommendation, { color: string; bg: string }> = {
  strong_yes: { color: "text-green-400", bg: "bg-green-500/10 border-green-500/30" },
  yes:        { color: "text-blue-400",  bg: "bg-blue-500/10 border-blue-500/30" },
  maybe:      { color: "text-yellow-400",bg: "bg-yellow-500/10 border-yellow-500/30" },
  no:         { color: "text-red-400",   bg: "bg-red-500/10 border-red-500/30" },
};

const CATEGORY_COLORS: Record<string, string> = {
  technical_core: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  technical_breadth: "bg-cyan-500/15 text-cyan-400 border-cyan-500/30",
  problem_solving: "bg-purple-500/15 text-purple-400 border-purple-500/30",
  communication: "bg-green-500/15 text-green-400 border-green-500/30",
  behavioral: "bg-orange-500/15 text-orange-400 border-orange-500/30",
};

const PROFICIENCY_COLORS: Record<string, string> = {
  expert: "bg-green-500/20 text-green-400", advanced: "bg-blue-500/20 text-blue-400",
  intermediate: "bg-yellow-500/20 text-yellow-400", beginner: "bg-slate-500/20 text-slate-400",
};

const SEVERITY_COLORS: Record<string, string> = {
  high: "border-red-500/40 bg-red-500/10 text-red-300",
  medium: "border-yellow-500/40 bg-yellow-500/10 text-yellow-300",
  low: "border-slate-600 bg-slate-800 text-slate-400",
};

const TIMELINE_RISK_STYLES: Record<"low" | "medium" | "high", string> = {
  low: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  medium: "bg-yellow-500/15 text-yellow-300 border-yellow-500/30",
  high: "bg-red-500/15 text-red-300 border-red-500/30",
};

export default function CompanyReportPage() {
  const locale = useLocale();
  const t = useTranslations("report");
  const dashboardT = useTranslations("companyDashboard");
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { loading: authLoading, logout } = useAuth({
    redirectTo: "/company/login",
    allowedRoles: ["company_admin", "company_member"],
    unauthorizedRedirectTo: "/candidate/dashboard",
  });
  const [report, setReport] = useState<AssessmentReport | null>(null);
  const [timeline, setTimeline] = useState<ProctoringTimeline | null>(null);
  const [error, setError] = useState("");
  const [expandedQ, setExpandedQ] = useState<number | null>(null);

  useEffect(() => {
    if (!id || authLoading) return;
    companyApi
      .getReport(id)
      .then((data) => {
        setReport(data);
        return companyApi.getReportProctoringTimeline(id)
          .then(setTimeline)
          .catch(() => {
            setTimeline(null);
          });
      })
      .catch(() => setError(t("loadFailed")));
  }, [id, authLoading, t]);

  if (authLoading || (!report && !error)) {
    return <div className="min-h-screen bg-slate-900 flex items-center justify-center"><div className="text-slate-400">{t("loadFailed")}</div></div>;
  }

  if (error || !report) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center px-4">
        <div className="text-center">
          <div className="text-red-400 mb-4">{error}</div>
          <button onClick={() => router.back()} className="text-blue-400 hover:underline text-sm">← {t("backToDashboard")}</button>
        </div>
      </div>
    );
  }

  const rec = RECOMMENDATION_CONFIG[report.hiring_recommendation];

  return (
    <div className="ai-shell min-h-screen px-4 py-10">
      <div className="ai-section max-w-4xl mx-auto">
        <CompanyWorkspaceHeader onLogout={logout} />
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
          <button onClick={() => router.back()} className="text-slate-400 hover:text-white text-sm inline-block transition-colors">
            ← {t("backToDashboard")}
          </button>
        </div>

        <div className="ai-panel-strong mb-6 rounded-[2rem] p-7">
          <h1 className="mb-2 text-3xl font-semibold tracking-[-0.03em] text-white">{t("title")}</h1>
          {report.interview_summary && <p className="max-w-3xl text-slate-400">{report.interview_summary}</p>}

        <div className={`mt-5 inline-flex items-center gap-2 border rounded-full px-4 py-1.5 text-sm font-semibold ${rec.bg} ${rec.color}`}>
          {t("recommendation")}: {dashboardT(`recommendations.${report.hiring_recommendation}`)}
        </div>
        </div>

        {report.module_session?.scenario_title && <ModuleSessionBanner session={report.module_session} />}

        {report.summary_model && <InterviewSummaryPanel summaryModel={report.summary_model} />}
        {report.system_design_summary && <SystemDesignSummaryPanel summary={report.system_design_summary} />}
        {report.behavioral_interview_summary && <BehavioralInterviewSummaryPanel summary={report.behavioral_interview_summary} />}
        {report.coding_task_summary && <CodingTaskSummaryPanel summary={report.coding_task_summary} />}
        {report.sql_live_summary && <SqlLiveSummaryPanel summary={report.sql_live_summary} />}
        {report.written_communication_summary && <WrittenCommunicationSummaryPanel summary={report.written_communication_summary} />}

        <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 mb-8">
          <ScoreCard label={t("overallScore")} score={report.overall_score} highlight />
          <ScoreCard label={t("hardSkills")} score={report.hard_skills_score} />
          <ScoreCard label={t("softSkills")} score={report.soft_skills_score} />
          <ScoreCard label={t("communication")} score={report.communication_score} />
          <ScoreCard label={t("problemSolving")} score={report.problem_solving_score} />
          {report.response_consistency != null && <ScoreCard label={t("consistency")} score={report.response_consistency} />}
        </div>

        <ConfidencePanel report={report} locale={locale} />
        {report.explainability_report && (
          <ExplainabilityPanel explainability={report.explainability_report} />
        )}

        {report.competency_scores && report.competency_scores.length > 0 && (
          <Section title={t("competencyHeatmap")} color="blue">
            <CompetencyHeatmap scores={report.competency_scores} />
          </Section>
        )}

        {report.skill_tags && report.skill_tags.length > 0 && (
          <Section title={t("skillsIdentified")} color="cyan"><SkillMatrix tags={report.skill_tags} /></Section>
        )}

        {report.red_flags && report.red_flags.length > 0 && (
          <Section title={t("redFlags")} color="red">
            <div className="space-y-3">
              {report.red_flags.map((rf, i) => <RedFlagRow key={i} flag={rf} />)}
            </div>
          </Section>
        )}

        {report.strengths.length > 0 && (
          <Section title={t("strengths")} color="green">
            {report.strengths.map((s, i) => <ListItem key={i} text={s} bullet="✓" color="text-green-400" />)}
          </Section>
        )}

        {report.weaknesses.length > 0 && (
          <Section title={t("areasToImprove")} color="yellow">
            {report.weaknesses.map((w, i) => <ListItem key={i} text={w} bullet="△" color="text-yellow-400" />)}
          </Section>
        )}

        {report.recommendations.length > 0 && (
          <Section title={t("recommendations")} color="purple">
            {report.recommendations.map((r, i) => <ListItem key={i} text={r} bullet="→" color="text-purple-400" />)}
          </Section>
        )}

        {report.per_question_analysis && report.per_question_analysis.length > 0 && (
          <div className="mt-6">
            <h2 className="text-white font-semibold mb-3">{t("perQuestionAnalysis")}</h2>
            <div className="space-y-2">
              {report.per_question_analysis.map((qa, i) => (
                <QuestionAccordion key={i} qa={qa} expanded={expandedQ === i} onToggle={() => setExpandedQ(expandedQ === i ? null : i)} />
              ))}
            </div>
          </div>
        )}

        {/* Cheat risk */}
        {report.cheat_risk_score != null && report.cheat_risk_score > 0 && (
          <div className="bg-slate-800 border border-orange-500/40 rounded-xl p-5 mb-4 mt-4">
            <div className="flex items-center gap-3 mb-2">
              <span className="text-orange-400 font-semibold text-sm">{t("behavioralRisk")}</span>
              <span className={`text-xs px-2 py-0.5 rounded-full font-bold ${
                report.cheat_risk_score >= 0.7 ? "bg-red-500/20 text-red-400" :
                report.cheat_risk_score >= 0.4 ? "bg-orange-500/20 text-orange-400" :
                "bg-yellow-500/20 text-yellow-400"
              }`}>
                {t("risk")}: {Math.round(report.cheat_risk_score * 100)}%
              </span>
            </div>
            {report.cheat_flags && report.cheat_flags.length > 0 && (
              <ul className="space-y-1">
                {report.cheat_flags.map((f, i) => (
                  <li key={i} className="text-orange-300 text-xs flex gap-2">
                    <span className="text-orange-500 mt-0.5 shrink-0">•</span>{f}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {timeline && (
          <Section title={t("proctoringTimeline")} color="cyan">
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="rounded-full border border-slate-600 px-2.5 py-1 text-slate-300">
                  {t("proctoringPolicy")}: {t(`proctoringPolicyMode.${timeline.policy_mode}`)}
                </span>
                <span className={`rounded-full border px-2.5 py-1 ${TIMELINE_RISK_STYLES[timeline.risk_level]}`}>
                  {t("proctoringRisk")}: {t(`proctoringRiskLevel.${timeline.risk_level}`)}
                </span>
                <span className="rounded-full border border-slate-600 px-2.5 py-1 text-slate-300">
                  {t("proctoringTotalEvents")}: {timeline.total_events}
                </span>
                <span className="rounded-full border border-slate-600 px-2.5 py-1 text-slate-300">
                  {t("proctoringHighSeverity")}: {timeline.high_severity_count}
                </span>
                {timeline.speech_activity_pct != null && (
                  <span className="rounded-full border border-slate-600 px-2.5 py-1 text-slate-300">
                    {t("proctoringSpeechActivity")}: {Math.round(timeline.speech_activity_pct * 100)}%
                  </span>
                )}
                {timeline.silence_pct != null && (
                  <span className="rounded-full border border-slate-600 px-2.5 py-1 text-slate-300">
                    {t("proctoringSilence")}: {Math.round(timeline.silence_pct * 100)}%
                  </span>
                )}
                {timeline.long_silence_count > 0 && (
                  <span className="rounded-full border border-slate-600 px-2.5 py-1 text-slate-300">
                    {t("proctoringLongSilence")}: {timeline.long_silence_count}
                  </span>
                )}
                {timeline.speech_segment_count > 0 && (
                  <span className="rounded-full border border-slate-600 px-2.5 py-1 text-slate-300">
                    {t("proctoringSpeechSegments")}: {timeline.speech_segment_count}
                  </span>
                )}
              </div>

              {timeline.events.length === 0 ? (
                <div className="rounded-lg border border-slate-700 bg-slate-900/60 px-3 py-2 text-sm text-slate-400">
                  {t("proctoringNoEvents")}
                </div>
              ) : (
                <div className="space-y-2">
                  {timeline.events.map((event, idx) => (
                    <TimelineEventRow key={`${event.event_type}-${idx}`} event={event} />
                  ))}
                </div>
              )}
            </div>
          </Section>
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
}: {
  session: NonNullable<AssessmentReport["module_session"]>;
}) {
  const t = useTranslations("report");

  return (
    <div className="mb-6 rounded-2xl border border-cyan-500/20 bg-cyan-500/10 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-[0.24em] text-cyan-300">{t("moduleSession.eyebrow")}</div>
          <div className="mt-1 text-sm font-semibold text-white">{session.module_title || t("moduleSession.titleFallback")}</div>
          <div className="mt-2 text-lg font-semibold text-white">{session.scenario_title}</div>
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
      {session.stack_focus && <p className="mt-3 text-sm leading-6 text-slate-200">{session.stack_focus}</p>}
      {session.scenario_prompt && <p className="mt-3 text-sm leading-6 text-slate-300">{session.scenario_prompt}</p>}
      {session.workspace_hint && <p className="mt-3 text-sm leading-6 text-slate-400">{session.workspace_hint}</p>}
    </div>
  );
}

function CodingTaskSummaryPanel({ summary }: { summary: NonNullable<AssessmentReport["coding_task_summary"]> }) {
  const t = useTranslations("report");

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
          <div className="mt-1 text-sm font-medium text-white">{summary.scenario_title}</div>
        </div>
      )}
      {summary.stack_focus && (
        <div className="mb-3">
          <div className="text-xs uppercase tracking-[0.16em] text-slate-500">{t("codingTask.stackFocus")}</div>
          <div className="mt-1 text-sm text-slate-200">{summary.stack_focus}</div>
        </div>
      )}
      {summary.preferred_language && (
        <div className="mb-3 text-xs text-slate-400">
          {t("codingTask.preferredLanguage")}: <span className="font-medium text-slate-200">{summary.preferred_language}</span>
        </div>
      )}
      {summary.scenario_prompt && <p className="mb-4 text-sm leading-6 text-slate-300">{summary.scenario_prompt}</p>}

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
          <pre className="overflow-x-auto whitespace-pre-wrap text-sm leading-6 text-slate-200">{summary.implementation_excerpt}</pre>
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
            {item}
          </div>
        ))}
      </div>
    </div>
  );
}

function CodingTaskStageCard({ stage }: { stage: CodingTaskStageSummary }) {
  const t = useTranslations("report");

  return (
    <div className="rounded-xl border border-slate-700 bg-slate-900/60 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="text-sm font-semibold text-white">{stage.stage_title}</div>
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
            {item}
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
  const statusStyles: Record<string, string> = {
    passed: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
    partial: "border-yellow-500/30 bg-yellow-500/10 text-yellow-200",
    missed: "border-slate-700 bg-slate-900/60 text-slate-300",
  };
  const style = statusStyles[check.status] ?? statusStyles.missed;

  return (
    <div className={`rounded-xl border p-4 ${style}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="text-sm font-medium">{check.title}</div>
        <div className="text-right">
          <div className="text-[11px] uppercase tracking-[0.16em]">
            {t(`codingTask.checkStatus.${check.status}`)}
          </div>
          {check.score != null && <div className="mt-1 text-sm font-semibold">{check.score.toFixed(1)}/10</div>}
        </div>
      </div>
      {check.evidence && <div className="mt-3 text-sm leading-6 opacity-90">{check.evidence}</div>}
    </div>
  );
}

function SqlLiveSummaryPanel({ summary }: { summary: NonNullable<AssessmentReport["sql_live_summary"]> }) {
  const t = useTranslations("report");

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
          <div className="mt-1 text-sm font-medium text-white">{summary.scenario_title}</div>
        </div>
      )}
      {summary.scenario_prompt && <p className="mb-4 text-sm leading-6 text-slate-300">{summary.scenario_prompt}</p>}

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

  return (
    <div className="rounded-xl border border-slate-700 bg-slate-900/60 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="text-sm font-semibold text-white">{stage.stage_title}</div>
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
            {item}
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
          <div className="mt-1 text-sm font-medium text-white">{summary.scenario_title}</div>
        </div>
      )}
      {summary.scenario_prompt && <p className="mb-4 text-sm leading-6 text-slate-300">{summary.scenario_prompt}</p>}
      {summary.workspace_hint && <p className="mb-4 text-sm leading-6 text-slate-400">{summary.workspace_hint}</p>}

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
          <pre className="overflow-x-auto whitespace-pre-wrap text-sm leading-6 text-slate-200">{summary.writing_excerpt}</pre>
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

  return (
    <div className="rounded-xl border border-slate-700 bg-slate-900/60 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="text-sm font-semibold text-white">{stage.stage_title}</div>
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
            {item}
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

function BehavioralInterviewSummaryPanel({ summary }: { summary: NonNullable<AssessmentReport["behavioral_interview_summary"]> }) {
  const t = useTranslations("report");

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
          <div className="mt-1 text-sm font-medium text-white">{summary.scenario_title}</div>
        </div>
      )}
      {summary.scenario_prompt && <p className="mb-4 text-sm leading-6 text-slate-300">{summary.scenario_prompt}</p>}

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

  return (
    <div className="rounded-xl border border-slate-700 bg-slate-900/60 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="text-sm font-semibold text-white">{stage.stage_title}</div>
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
            {item}
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

function SystemDesignSummaryPanel({ summary }: { summary: NonNullable<AssessmentReport["system_design_summary"]> }) {
  const t = useTranslations("report");

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
          <div className="mt-1 text-sm font-medium text-white">{summary.scenario_title}</div>
        </div>
      )}
      {summary.scenario_prompt && <p className="mb-4 text-sm leading-6 text-slate-300">{summary.scenario_prompt}</p>}

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

  return (
    <div className="rounded-xl border border-slate-700 bg-slate-900/60 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="text-sm font-semibold text-white">{stage.stage_title}</div>
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
            {item}
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

function localizeConfidenceReason(text: string, locale: string) {
  if (locale !== "ru") return text;

  const translations: Record<string, string> = {
    "No per-question evidence extracted; confidence is limited.": "По ответам не удалось извлечь достаточно evidence, поэтому confidence ограничен.",
    "Low concrete evidence coverage reduced confidence.": "Низкое покрытие конкретными evidence снизило confidence.",
    "High evidence coverage increased confidence.": "Высокое покрытие evidence повысило confidence.",
    "Multiple low-confidence answers reduced certainty.": "Несколько слабых ответов снизили уверенность в выводах.",
    "Several answers contained high-confidence evidence.": "Несколько ответов содержали сильные evidence.",
    "High AI-likelihood signal lowered confidence.": "Высокий AI-likelihood сигнал снизил confidence.",
    "Low AI-likelihood signal improved confidence.": "Низкий AI-likelihood сигнал повысил confidence.",
    "Confidence derived from mixed evidence quality signals.": "Confidence сформирован на основе смешанного качества evidence.",
  };

  return translations[text] ?? text;
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
                  <div className="text-sm text-white">{name}</div>
                  <div className="text-xs font-semibold text-sky-300">{formatPercent(value)}</div>
                </div>
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

  return (
    <div className="mb-6 rounded-2xl border border-fuchsia-500/20 bg-fuchsia-500/10 p-5">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-[0.24em] text-fuchsia-300">{t("explainability.eyebrow")}</div>
          <div className="text-sm font-semibold text-white">{t("explainability.title")}</div>
          <div className="mt-1 max-w-3xl text-sm leading-6 text-slate-300">{overall.summary}</div>
        </div>
        <div className="flex flex-wrap gap-2 text-xs">
          <span className="rounded-full border border-fuchsia-400/30 bg-fuchsia-950/40 px-3 py-1 text-fuchsia-200">
            {t("recommendation")}: {recommendationLabelMap[overall.recommendation] ?? overall.recommendation}
          </span>
          <span className="rounded-full border border-slate-700 bg-slate-950 px-3 py-1 text-slate-300">
            {t(`summaryModel.signal.${overall.signal_quality}`)}
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
                  <div className="text-sm font-medium text-white">{item.title}</div>
                  <div className="mt-1 text-xs leading-5 text-slate-300">{item.why_it_matters}</div>
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
                  <div className="text-sm font-medium text-white">{item.title}</div>
                  <div className="mt-1 text-xs leading-5 text-slate-300">{item.risk}</div>
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
                  <div className="text-sm font-medium text-white">{item.title}</div>
                  {item.linked_gap && <div className="mt-1 text-xs text-slate-400">{t("explainability.linkedGap")}: {item.linked_gap}</div>}
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
                  • {item}
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
  const value = score ?? 0;
  return (
    <div className={`bg-slate-800 border rounded-xl p-4 ${highlight ? "border-blue-500/40" : "border-slate-700"}`}>
      <div className="text-slate-400 text-xs mb-2">{label}</div>
      <div className={`text-2xl font-bold mb-2 ${highlight ? "text-blue-400" : "text-white"}`}>
        {value.toFixed(1)}<span className="text-slate-500 text-sm font-normal">/10</span>
      </div>
      <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${highlight ? "bg-blue-500" : "bg-slate-400"}`} style={{ width: `${(value / 10) * 100}%` }} />
      </div>
    </div>
  );
}

function CompetencyHeatmap({ scores }: { scores: CompetencyScore[] }) {
  const t = useTranslations("report");
  const groups: Record<string, CompetencyScore[]> = {};
  for (const cs of scores) { if (!groups[cs.category]) groups[cs.category] = []; groups[cs.category].push(cs); }
  return (
    <div className="space-y-4">
      {Object.entries(groups).map(([category, items]) => (
        <div key={category}>
          <div className="text-xs text-slate-500 uppercase tracking-wide mb-2">{CATEGORY_COLORS[category] ? t(`labels.${category}`) : category}</div>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {items.map((cs, i) => {
              const cellClass = cs.score >= 7 ? "bg-green-500/30 border-green-500/50 text-green-300" : cs.score >= 5 ? "bg-yellow-500/30 border-yellow-500/50 text-yellow-300" : "bg-red-500/30 border-red-500/50 text-red-300";
              return (
                <div key={i} className={`border rounded-lg px-3 py-2 ${cellClass}`}>
                  <div className="text-xs font-medium truncate">{cs.competency}</div>
                  <div className="text-lg font-bold mt-0.5">{cs.score.toFixed(1)}</div>
                  {cs.evidence && <div className="text-xs opacity-70 mt-1 line-clamp-2">{cs.evidence}</div>}
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
        <div className="text-xs text-green-400 uppercase tracking-wide font-semibold mb-2">{t("strongSkills")} ({t("strengthBand")})</div>
        <div className="flex flex-wrap gap-1.5">
          {strong.length === 0 ? <span className="text-slate-500 text-xs">—</span> : strong.map((tag, i) => (
            <span key={i} className="px-2.5 py-1 rounded-full text-xs font-medium bg-green-500/20 text-green-400">{tag.skill}{tag.mentions_count > 1 && <span className="ml-1 opacity-60">×{tag.mentions_count}</span>}</span>
          ))}
        </div>
      </div>
      <div>
        <div className="text-xs text-yellow-400 uppercase tracking-wide font-semibold mb-2">{t("developSkills")} ({t("developBand")})</div>
        <div className="flex flex-wrap gap-1.5">
          {develop.length === 0 ? <span className="text-slate-500 text-xs">—</span> : develop.map((tag, i) => (
            <span key={i} className="px-2.5 py-1 rounded-full text-xs font-medium bg-yellow-500/20 text-yellow-400">{tag.skill}{tag.mentions_count > 1 && <span className="ml-1 opacity-60">×{tag.mentions_count}</span>}</span>
          ))}
        </div>
      </div>
    </div>
  );
}

function RedFlagRow({ flag }: { flag: RedFlag }) {
  const t = useTranslations("report");
  const style = SEVERITY_COLORS[flag.severity] ?? SEVERITY_COLORS.low;
  return (
    <div className={`border rounded-lg px-4 py-3 ${style}`}>
      <div className="flex items-center gap-2 mb-1"><span className="text-sm font-medium">{t("alert")} {flag.flag}</span><span className="text-xs opacity-70 capitalize">{t(`severity.${flag.severity}`)}</span></div>
      {flag.evidence && <p className="text-xs opacity-80">{flag.evidence}</p>}
    </div>
  );
}

function TimelineEventRow({ event }: { event: ProctoringTimelineEvent }) {
  const t = useTranslations("report");
  const severityStyle = SEVERITY_COLORS[event.severity] ?? SEVERITY_COLORS.low;
  const eventLabel = event.event_type.replace(/_/g, " ");
  const timeLabel = event.occurred_at ? new Date(event.occurred_at).toLocaleTimeString() : "—";
  const detailEntries = formatProctoringEventDetails(event.details);

  return (
    <div className={`rounded-lg border px-3 py-2 text-sm ${severityStyle}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="font-medium capitalize">{eventLabel}</div>
        <div className="text-[11px] opacity-80">
          {t("proctoringEventTime")}: {timeLabel}
        </div>
      </div>
      <div className="mt-1 text-xs opacity-80">
        {t("proctoringEventSource")}: {event.source || "client"}
      </div>
      {detailEntries.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-2 text-[11px] opacity-80">
          {detailEntries.map((item) => (
            <span key={item} className="rounded-full border border-current/20 px-2 py-0.5">
              {item}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function formatProctoringEventDetails(details: Record<string, unknown>): string[] {
  return Object.entries(details)
    .map(([key, value]) => {
      if (value == null) return null;
      if (typeof value === "number" && key.endsWith("_pct")) {
        return `${key.replace(/_/g, " ")}: ${Math.round(value * 100)}%`;
      }
      return `${key.replace(/_/g, " ")}: ${String(value)}`;
    })
    .filter((item): item is string => Boolean(item));
}

function QuestionAccordion({ qa, expanded, onToggle }: { qa: QuestionAnalysis; expanded: boolean; onToggle: () => void }) {
  const t = useTranslations("report");
  const depthColor: Record<string, string> = { expert: "text-green-400", strong: "text-blue-400", adequate: "text-yellow-400", surface: "text-orange-400", none: "text-red-400" };
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg overflow-hidden">
      <button onClick={onToggle} className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-slate-750 transition-colors">
        <div className="flex items-center gap-3">
          <span className="text-slate-500 text-xs">{t("questionShort", { number: qa.question_number })}</span>
          {qa.stage_title && (
            <span className="rounded-full border border-violet-500/20 bg-violet-500/10 px-2 py-0.5 text-[11px] text-violet-300">
              {qa.stage_title}
            </span>
          )}
          <span className="text-slate-300 text-sm font-medium">{qa.targeted_competencies.join(", ") || t("general")}</span>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <span className={`text-xs font-medium ${depthColor[qa.depth] ?? "text-slate-400"} capitalize`}>{t(`depth.${qa.depth}`)}</span>
          <span className="text-white text-sm font-bold">{qa.answer_quality.toFixed(1)}</span>
          <span className="text-slate-500 text-xs">{expanded ? "▲" : "▼"}</span>
        </div>
      </button>
      {expanded && (
        <div className="px-4 pb-4 space-y-3 border-t border-slate-700">
          {qa.evidence && <div><p className="text-slate-500 text-xs uppercase tracking-wide mb-1">{t("evidence")}</p><p className="text-slate-300 text-sm">{qa.evidence}</p></div>}
          {qa.skills_mentioned.length > 0 && (
            <div><p className="text-slate-500 text-xs uppercase tracking-wide mb-1">{t("skillsMentioned")}</p>
              <div className="flex flex-wrap gap-1.5">{qa.skills_mentioned.map((s, i) => <span key={i} className={`px-2 py-0.5 rounded text-xs ${PROFICIENCY_COLORS[s.proficiency] ?? PROFICIENCY_COLORS.intermediate}`}>{s.skill}</span>)}</div>
            </div>
          )}
          {qa.red_flags.length > 0 && <div><p className="text-slate-500 text-xs uppercase tracking-wide mb-1">{t("flags")}</p><ul className="space-y-1">{qa.red_flags.map((rf, i) => <li key={i} className="text-red-400 text-xs">{t("alert")} {rf}</li>)}</ul></div>}
          <div className="flex flex-wrap gap-4 text-xs">
            <span className="text-slate-500">{t("specificity")}: <span className="text-slate-300 capitalize">{t(`specificityValue.${qa.specificity}`)}</span></span>
            {qa.ai_likelihood != null && qa.ai_likelihood > 0.1 && (
              <span className={`font-medium ${qa.ai_likelihood >= 0.7 ? "text-red-400" : qa.ai_likelihood >= 0.4 ? "text-orange-400" : "text-yellow-400"}`}>
                {t("aiLikelihood")}: {Math.round(qa.ai_likelihood * 100)}%
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Section({ title, children, color }: { title: string; children: React.ReactNode; color: string }) {
  const colors: Record<string, string> = { green: "text-green-400", yellow: "text-yellow-400", blue: "text-blue-400", cyan: "text-cyan-400", purple: "text-purple-400", red: "text-red-400" };
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl p-6 mb-4">
      <h2 className={`font-semibold mb-3 ${colors[color] ?? "text-white"}`}>{title}</h2>
      <ul className="space-y-2">{children}</ul>
    </div>
  );
}

function ListItem({ text, bullet, color }: { text: string; bullet: string; color: string }) {
  return <li className="flex gap-3 text-sm text-slate-300"><span className={`${color} shrink-0 mt-0.5`}>{bullet}</span>{text}</li>;
}
