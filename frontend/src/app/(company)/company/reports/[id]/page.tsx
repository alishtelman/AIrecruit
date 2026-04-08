"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useParams } from "next/navigation";
import { useRouter } from "@/i18n/navigation";
import { CompanyWorkspaceHeader } from "@/components/company-workspace-header";
import { useAuth } from "@/hooks/useAuth";
import { companyApi } from "@/lib/api";
import type { AssessmentReport, HiringRecommendation, CompetencyScore, SkillTag, RedFlag, QuestionAnalysis, ProctoringTimeline, ProctoringTimelineEvent, SystemDesignStageSummary } from "@/lib/types";

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

        {report.summary_model && <InterviewSummaryPanel summaryModel={report.summary_model} />}
        {report.system_design_summary && <SystemDesignSummaryPanel summary={report.system_design_summary} />}

        <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 mb-8">
          <ScoreCard label={t("overallScore")} score={report.overall_score} highlight />
          <ScoreCard label={t("hardSkills")} score={report.hard_skills_score} />
          <ScoreCard label={t("softSkills")} score={report.soft_skills_score} />
          <ScoreCard label={t("communication")} score={report.communication_score} />
          <ScoreCard label={t("problemSolving")} score={report.problem_solving_score} />
          {report.response_consistency != null && <ScoreCard label={t("consistency")} score={report.response_consistency} />}
        </div>

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

function SystemDesignSummaryPanel({ summary }: { summary: NonNullable<AssessmentReport["system_design_summary"]> }) {
  const t = useTranslations("report");

  return (
    <div className="mb-6 rounded-2xl border border-violet-500/20 bg-violet-500/10 p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-[0.24em] text-violet-300">{t("systemDesign.eyebrow")}</div>
          <div className="text-sm font-semibold text-white">{summary.module_title || t("systemDesign.title")}</div>
        </div>
        <span className="rounded-full border border-violet-400/20 bg-slate-900/50 px-3 py-1 text-xs text-slate-200">
          {t("systemDesign.stageCount", { count: summary.stage_count })}
        </span>
      </div>

      {summary.scenario_title && (
        <div className="mb-3">
          <div className="text-xs uppercase tracking-[0.16em] text-slate-500">{t("systemDesign.scenario")}</div>
          <div className="mt-1 text-sm font-medium text-white">{summary.scenario_title}</div>
        </div>
      )}
      {summary.scenario_prompt && <p className="mb-4 text-sm leading-6 text-slate-300">{summary.scenario_prompt}</p>}

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
        {stage.average_answer_quality != null && (
          <div className="text-sm font-bold text-violet-300">{stage.average_answer_quality.toFixed(1)}</div>
        )}
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
    </div>
  );
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
