import uuid
from datetime import datetime

from pydantic import BaseModel, model_validator


class CompetencyScore(BaseModel):
    competency: str
    category: str
    score: float
    weight: float
    evidence: str
    reasoning: str = ""


class QuestionAnalysis(BaseModel):
    question_number: int
    targeted_competencies: list[str] = []
    answer_quality: float
    evidence: str = ""
    skills_mentioned: list[dict] = []
    red_flags: list[str] = []
    specificity: str = "medium"
    depth: str = "adequate"
    ai_likelihood: float | None = None
    stage_key: str | None = None
    stage_title: str | None = None


class SkillTag(BaseModel):
    skill: str
    proficiency: str
    mentions_count: int = 1


class RedFlag(BaseModel):
    flag: str
    evidence: str
    severity: str = "low"


class ReportSummaryBlock(BaseModel):
    score: float | None
    hiring_recommendation: str
    top_strengths: list[str]
    top_weaknesses: list[str]


class InterviewSummaryModel(BaseModel):
    class TopicOutcome(BaseModel):
        slot: int
        label: str
        signal: str
        outcome: str
        verification_target: str | None = None

    role: str
    core_topics: int
    total_turns: int
    extra_turns: int
    covered_competencies: int
    coverage_label: str
    signal_quality: str
    validated_topics: int = 0
    partial_topics: int = 0
    unverified_claim_topics: int = 0
    honest_gaps: int
    generic_or_evasive_topics: int
    strong_topics: int
    topic_outcomes: list[TopicOutcome] = []


class ReportModuleSession(BaseModel):
    module_type: str
    module_title: str | None = None
    scenario_id: str | None = None
    scenario_title: str | None = None
    scenario_prompt: str | None = None
    stage_key: str | None = None
    stage_title: str | None = None
    stage_index: int = 0
    stage_count: int = 0


class SystemDesignStageSummary(BaseModel):
    stage_key: str
    stage_title: str
    question_numbers: list[int] = []
    average_answer_quality: float | None = None
    evidence_items: list[str] = []


class SystemDesignSummary(BaseModel):
    module_title: str | None = None
    scenario_id: str | None = None
    scenario_title: str | None = None
    scenario_prompt: str | None = None
    stage_count: int = 0
    stages: list[SystemDesignStageSummary] = []


class AssessmentReportResponse(BaseModel):
    id: uuid.UUID
    interview_id: uuid.UUID
    candidate_id: uuid.UUID
    overall_score: float | None
    hard_skills_score: float | None
    soft_skills_score: float | None
    communication_score: float | None
    problem_solving_score: float | None = None
    strengths: list[str]
    weaknesses: list[str]
    recommendations: list[str]
    hiring_recommendation: str
    interview_summary: str | None
    model_version: str
    created_at: datetime

    # Scientific assessment fields
    competency_scores: list[CompetencyScore] | None = None
    per_question_analysis: list[QuestionAnalysis] | None = None
    skill_tags: list[SkillTag] | None = None
    red_flags: list[RedFlag] | None = None
    response_consistency: float | None = None
    overall_confidence: float | None = None
    competency_confidence: dict[str, float] | None = None
    confidence_reasons: list[str] | None = None
    evidence_coverage: dict | None = None
    decision_policy_version: str | None = None
    cheat_risk_score: float | None = None
    cheat_flags: list[str] | None = None
    summary: ReportSummaryBlock | None = None
    summary_model: InterviewSummaryModel | None = None
    module_session: ReportModuleSession | None = None
    system_design_summary: SystemDesignSummary | None = None

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _pull_summary_model(cls, data):
        def _get_value(source, key):
            if isinstance(source, dict):
                return source.get(key)
            return getattr(source, key, None)

        def _set_value(source, key, value):
            if isinstance(source, dict):
                source[key] = value
            else:
                setattr(source, key, value)

        full_report_json = _get_value(data, "full_report_json")
        per_question_analysis = _get_value(data, "per_question_analysis")

        if isinstance(full_report_json, dict):
            summary_model = full_report_json.get("summary_model")
            _set_value(data, "summary_model", summary_model)

            interview_meta = full_report_json.get("interview_meta")
            if isinstance(interview_meta, dict):
                module_type = str(interview_meta.get("module_type") or "").strip().lower()
                module_title = str(interview_meta.get("module_title") or "").strip() or None
                stage_plan = interview_meta.get("module_stage_plan") if isinstance(interview_meta.get("module_stage_plan"), list) else []
                stage_index_raw = interview_meta.get("module_stage_index")
                try:
                    stage_index = int(stage_index_raw)
                except (TypeError, ValueError):
                    stage_index = 0
                stage_index = max(stage_index, 0)
                current_stage = stage_plan[stage_index] if stage_plan and stage_index < len(stage_plan) else {}
                module_session = {
                    "module_type": module_type,
                    "module_title": module_title,
                    "scenario_id": str(interview_meta.get("module_scenario_id") or "").strip() or None,
                    "scenario_title": str(interview_meta.get("module_scenario_title") or "").strip() or None,
                    "scenario_prompt": str(interview_meta.get("module_scenario_prompt") or "").strip() or None,
                    "stage_key": str(current_stage.get("stage_key") or interview_meta.get("module_stage_key") or "").strip() or None,
                    "stage_title": str(current_stage.get("stage_title") or interview_meta.get("module_stage_title") or "").strip() or None,
                    "stage_index": stage_index,
                    "stage_count": len(stage_plan),
                } if module_type else None
                _set_value(data, "module_session", module_session)

                if module_type == "system_design":
                    question_history = interview_meta.get("module_question_history") if isinstance(interview_meta.get("module_question_history"), list) else []
                    stage_map: dict[int, dict[str, str | None]] = {}
                    for item in question_history:
                        if not isinstance(item, dict):
                            continue
                        try:
                            assistant_turn = int(item.get("assistant_turn") or 0)
                        except (TypeError, ValueError):
                            assistant_turn = 0
                        if assistant_turn <= 0:
                            continue
                        stage_map[assistant_turn] = {
                            "stage_key": str(item.get("stage_key") or "").strip() or None,
                            "stage_title": str(item.get("stage_title") or "").strip() or None,
                        }

                    enriched_per_q: list[dict] = []
                    if isinstance(per_question_analysis, list):
                        for raw_item in per_question_analysis:
                            if isinstance(raw_item, dict):
                                question_number = raw_item.get("question_number")
                                try:
                                    question_number = int(question_number or 0)
                                except (TypeError, ValueError):
                                    question_number = 0
                                stage_meta = stage_map.get(question_number, {})
                                enriched = dict(raw_item)
                                if stage_meta.get("stage_key"):
                                    enriched["stage_key"] = stage_meta["stage_key"]
                                if stage_meta.get("stage_title"):
                                    enriched["stage_title"] = stage_meta["stage_title"]
                                enriched_per_q.append(enriched)
                            else:
                                enriched_per_q.append(raw_item)
                        _set_value(data, "per_question_analysis", enriched_per_q)
                    else:
                        enriched_per_q = []

                    stages: list[dict] = []
                    for stage in stage_plan:
                        if not isinstance(stage, dict):
                            continue
                        stage_key = str(stage.get("stage_key") or "").strip()
                        stage_title = str(stage.get("stage_title") or "").strip()
                        if not stage_key or not stage_title:
                            continue
                        stage_questions = [
                            item for item in enriched_per_q
                            if isinstance(item, dict) and item.get("stage_key") == stage_key
                        ]
                        qualities = [
                            float(item.get("answer_quality"))
                            for item in stage_questions
                            if isinstance(item.get("answer_quality"), (int, float))
                        ]
                        evidence_items = [
                            str(item.get("evidence") or "").strip()
                            for item in stage_questions
                            if str(item.get("evidence") or "").strip()
                        ]
                        stages.append(
                            {
                                "stage_key": stage_key,
                                "stage_title": stage_title,
                                "question_numbers": [
                                    int(item.get("question_number"))
                                    for item in stage_questions
                                    if isinstance(item.get("question_number"), int)
                                ],
                                "average_answer_quality": round(sum(qualities) / len(qualities), 2) if qualities else None,
                                "evidence_items": evidence_items[:3],
                            }
                        )

                    _set_value(
                        data,
                        "system_design_summary",
                        {
                            "module_title": module_title,
                            "scenario_id": module_session["scenario_id"] if module_session else None,
                            "scenario_title": module_session["scenario_title"] if module_session else None,
                            "scenario_prompt": module_session["scenario_prompt"] if module_session else None,
                            "stage_count": len(stage_plan),
                            "stages": stages,
                        },
                    )
        return data

    @model_validator(mode="after")
    def _build_summary(self) -> "AssessmentReportResponse":
        self.summary = ReportSummaryBlock(
            score=self.overall_score,
            hiring_recommendation=self.hiring_recommendation,
            top_strengths=self.strengths[:2],
            top_weaknesses=self.weaknesses[:2],
        )
        return self
