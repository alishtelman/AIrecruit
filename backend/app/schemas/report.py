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


class DevelopmentRoadmapPhase(BaseModel):
    phase_key: str
    focus: str | None = None
    actions: list[str] = []


class DevelopmentRoadmap(BaseModel):
    phases: list[DevelopmentRoadmapPhase] = []


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
    stack_focus: str | None = None
    preferred_language: str | None = None
    workspace_hint: str | None = None
    stage_key: str | None = None
    stage_title: str | None = None
    stage_index: int = 0
    stage_count: int = 0


class SystemDesignStageSummary(BaseModel):
    stage_key: str
    stage_title: str
    question_numbers: list[int] = []
    average_answer_quality: float | None = None
    stage_score: float | None = None
    evidence_items: list[str] = []


class SystemDesignRubricScore(BaseModel):
    rubric_key: str
    score: float | None = None


class SystemDesignSummary(BaseModel):
    module_title: str | None = None
    scenario_id: str | None = None
    scenario_title: str | None = None
    scenario_prompt: str | None = None
    stage_count: int = 0
    overall_score: float | None = None
    rubric_scores: list[SystemDesignRubricScore] = []
    stages: list[SystemDesignStageSummary] = []


class CodingTaskStageSummary(BaseModel):
    stage_key: str
    stage_title: str
    question_numbers: list[int] = []
    average_answer_quality: float | None = None
    stage_score: float | None = None
    evidence_items: list[str] = []


class CodingTaskRubricScore(BaseModel):
    rubric_key: str
    score: float | None = None


class CodingTaskCoverageCheck(BaseModel):
    check_key: str
    title: str
    status: str
    score: float | None = None
    evidence: str | None = None


class CodingTaskSummary(BaseModel):
    module_title: str | None = None
    scenario_id: str | None = None
    scenario_title: str | None = None
    scenario_prompt: str | None = None
    stack_focus: str | None = None
    preferred_language: str | None = None
    workspace_hint: str | None = None
    stage_count: int = 0
    overall_score: float | None = None
    coverage_score: float | None = None
    runner_score: float | None = None
    stack_score: float | None = None
    rubric_scores: list[CodingTaskRubricScore] = []
    coverage_checks: list[CodingTaskCoverageCheck] = []
    runner_checks: list[CodingTaskCoverageCheck] = []
    stack_checks: list[CodingTaskCoverageCheck] = []
    stages: list[CodingTaskStageSummary] = []
    implementation_excerpt: str | None = None
    has_code_submission: bool = False
    code_signal_score: float | None = None


class SqlLiveStageSummary(BaseModel):
    stage_key: str
    stage_title: str
    question_numbers: list[int] = []
    average_answer_quality: float | None = None
    stage_score: float | None = None
    evidence_items: list[str] = []


class SqlLiveRubricScore(BaseModel):
    rubric_key: str
    score: float | None = None


class SqlLiveSummary(BaseModel):
    module_title: str | None = None
    scenario_id: str | None = None
    scenario_title: str | None = None
    scenario_prompt: str | None = None
    stage_count: int = 0
    overall_score: float | None = None
    validation_score: float | None = None
    rubric_scores: list[SqlLiveRubricScore] = []
    validation_checks: list[CodingTaskCoverageCheck] = []
    stages: list[SqlLiveStageSummary] = []
    query_excerpt: str | None = None
    has_query_submission: bool = False


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
    development_roadmap: DevelopmentRoadmap | None = None
    summary_model: InterviewSummaryModel | None = None
    module_session: ReportModuleSession | None = None
    system_design_summary: SystemDesignSummary | None = None
    coding_task_summary: CodingTaskSummary | None = None
    sql_live_summary: SqlLiveSummary | None = None

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
                    "stack_focus": str(interview_meta.get("module_stack_focus") or "").strip() or None,
                    "preferred_language": str(interview_meta.get("module_preferred_language") or "").strip() or None,
                    "workspace_hint": str(interview_meta.get("module_workspace_hint") or "").strip() or None,
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

                    explicit_evaluation = (
                        full_report_json.get("system_design_evaluation")
                        if isinstance(full_report_json.get("system_design_evaluation"), dict)
                        else None
                    )
                    stages: list[dict] = []
                    rubric_scores = []
                    overall_score = None
                    if explicit_evaluation:
                        explicit_stages = explicit_evaluation.get("stages")
                        if isinstance(explicit_stages, list):
                            for stage in explicit_stages:
                                if not isinstance(stage, dict):
                                    continue
                                stages.append(
                                    {
                                        "stage_key": str(stage.get("stage_key") or "").strip(),
                                        "stage_title": str(stage.get("stage_title") or "").strip(),
                                        "question_numbers": [
                                            int(item)
                                            for item in stage.get("question_numbers", [])
                                            if isinstance(item, int)
                                        ],
                                        "average_answer_quality": stage.get("average_answer_quality"),
                                        "stage_score": stage.get("stage_score"),
                                        "evidence_items": [
                                            str(item).strip()
                                            for item in stage.get("evidence_items", [])
                                            if str(item).strip()
                                        ],
                                    }
                                )
                        explicit_rubrics = explicit_evaluation.get("rubric_scores")
                        if isinstance(explicit_rubrics, list):
                            rubric_scores = [
                                {
                                    "rubric_key": str(item.get("rubric_key") or "").strip(),
                                    "score": item.get("score"),
                                }
                                for item in explicit_rubrics
                                if isinstance(item, dict) and str(item.get("rubric_key") or "").strip()
                            ]
                        overall_score = explicit_evaluation.get("overall_score")
                    else:
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
                                    "stage_score": None,
                                    "evidence_items": evidence_items[:3],
                                }
                            )

                    _set_value(
                        data,
                        "system_design_summary",
                        {
                            "module_title": (
                                explicit_evaluation.get("module_title")
                                if explicit_evaluation and explicit_evaluation.get("module_title")
                                else module_title
                            ),
                            "scenario_id": (
                                explicit_evaluation.get("scenario_id")
                                if explicit_evaluation and explicit_evaluation.get("scenario_id")
                                else module_session["scenario_id"] if module_session else None
                            ),
                            "scenario_title": (
                                explicit_evaluation.get("scenario_title")
                                if explicit_evaluation and explicit_evaluation.get("scenario_title")
                                else module_session["scenario_title"] if module_session else None
                            ),
                            "scenario_prompt": (
                                explicit_evaluation.get("scenario_prompt")
                                if explicit_evaluation and explicit_evaluation.get("scenario_prompt")
                                else module_session["scenario_prompt"] if module_session else None
                            ),
                            "stage_count": int(explicit_evaluation.get("stage_count") or len(stage_plan)) if explicit_evaluation else len(stage_plan),
                            "overall_score": overall_score,
                            "rubric_scores": rubric_scores,
                            "stages": stages,
                        },
                    )
                elif module_type == "coding_task":
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

                    explicit_evaluation = (
                        full_report_json.get("coding_task_evaluation")
                        if isinstance(full_report_json.get("coding_task_evaluation"), dict)
                        else None
                    )
                    stages: list[dict] = []
                    rubric_scores = []
                    coverage_checks = []
                    runner_checks = []
                    stack_checks = []
                    overall_score = None
                    coverage_score = None
                    runner_score = None
                    stack_score = None
                    implementation_excerpt = None
                    has_code_submission = False
                    code_signal_score = None
                    if explicit_evaluation:
                        explicit_stages = explicit_evaluation.get("stages")
                        if isinstance(explicit_stages, list):
                            for stage in explicit_stages:
                                if not isinstance(stage, dict):
                                    continue
                                stages.append(
                                    {
                                        "stage_key": str(stage.get("stage_key") or "").strip(),
                                        "stage_title": str(stage.get("stage_title") or "").strip(),
                                        "question_numbers": [
                                            int(item)
                                            for item in stage.get("question_numbers", [])
                                            if isinstance(item, int)
                                        ],
                                        "average_answer_quality": stage.get("average_answer_quality"),
                                        "stage_score": stage.get("stage_score"),
                                        "evidence_items": [
                                            str(item).strip()
                                            for item in stage.get("evidence_items", [])
                                            if str(item).strip()
                                        ],
                                    }
                                )
                        explicit_rubrics = explicit_evaluation.get("rubric_scores")
                        if isinstance(explicit_rubrics, list):
                            rubric_scores = [
                                {
                                    "rubric_key": str(item.get("rubric_key") or "").strip(),
                                    "score": item.get("score"),
                                }
                                for item in explicit_rubrics
                                if isinstance(item, dict) and str(item.get("rubric_key") or "").strip()
                            ]
                        explicit_checks = explicit_evaluation.get("coverage_checks")
                        if isinstance(explicit_checks, list):
                            coverage_checks = [
                                {
                                    "check_key": str(item.get("check_key") or "").strip(),
                                    "title": str(item.get("title") or "").strip(),
                                    "status": str(item.get("status") or "missed").strip(),
                                    "score": item.get("score"),
                                    "evidence": str(item.get("evidence") or "").strip() or None,
                                }
                                for item in explicit_checks
                                if isinstance(item, dict) and str(item.get("check_key") or "").strip()
                            ]
                        explicit_runner_checks = explicit_evaluation.get("runner_checks")
                        if isinstance(explicit_runner_checks, list):
                            runner_checks = [
                                {
                                    "check_key": str(item.get("check_key") or "").strip(),
                                    "title": str(item.get("title") or "").strip(),
                                    "status": str(item.get("status") or "missed").strip(),
                                    "score": item.get("score"),
                                    "evidence": str(item.get("evidence") or "").strip() or None,
                                }
                                for item in explicit_runner_checks
                                if isinstance(item, dict) and str(item.get("check_key") or "").strip()
                            ]
                        explicit_stack_checks = explicit_evaluation.get("stack_checks")
                        if isinstance(explicit_stack_checks, list):
                            stack_checks = [
                                {
                                    "check_key": str(item.get("check_key") or "").strip(),
                                    "title": str(item.get("title") or "").strip(),
                                    "status": str(item.get("status") or "missed").strip(),
                                    "score": item.get("score"),
                                    "evidence": str(item.get("evidence") or "").strip() or None,
                                }
                                for item in explicit_stack_checks
                                if isinstance(item, dict) and str(item.get("check_key") or "").strip()
                            ]
                        overall_score = explicit_evaluation.get("overall_score")
                        coverage_score = explicit_evaluation.get("coverage_score")
                        runner_score = explicit_evaluation.get("runner_score")
                        stack_score = explicit_evaluation.get("stack_score")
                        implementation_excerpt = (
                            str(explicit_evaluation.get("implementation_excerpt") or "").strip() or None
                        )
                        has_code_submission = bool(explicit_evaluation.get("has_code_submission"))
                        code_signal_score = explicit_evaluation.get("code_signal_score")
                    else:
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
                                    "stage_score": None,
                                    "evidence_items": evidence_items[:3],
                                }
                            )

                    _set_value(
                        data,
                        "coding_task_summary",
                        {
                            "module_title": (
                                explicit_evaluation.get("module_title")
                                if explicit_evaluation and explicit_evaluation.get("module_title")
                                else module_title
                            ),
                            "scenario_id": (
                                explicit_evaluation.get("scenario_id")
                                if explicit_evaluation and explicit_evaluation.get("scenario_id")
                                else module_session["scenario_id"] if module_session else None
                            ),
                            "scenario_title": (
                                explicit_evaluation.get("scenario_title")
                                if explicit_evaluation and explicit_evaluation.get("scenario_title")
                                else module_session["scenario_title"] if module_session else None
                            ),
                            "scenario_prompt": (
                                explicit_evaluation.get("scenario_prompt")
                                if explicit_evaluation and explicit_evaluation.get("scenario_prompt")
                                else module_session["scenario_prompt"] if module_session else None
                            ),
                            "stack_focus": (
                                explicit_evaluation.get("stack_focus")
                                if explicit_evaluation and explicit_evaluation.get("stack_focus")
                                else module_session["stack_focus"] if module_session else None
                            ),
                            "preferred_language": (
                                explicit_evaluation.get("preferred_language")
                                if explicit_evaluation and explicit_evaluation.get("preferred_language")
                                else module_session["preferred_language"] if module_session else None
                            ),
                            "workspace_hint": (
                                explicit_evaluation.get("workspace_hint")
                                if explicit_evaluation and explicit_evaluation.get("workspace_hint")
                                else module_session["workspace_hint"] if module_session else None
                            ),
                            "stage_count": int(explicit_evaluation.get("stage_count") or len(stage_plan)) if explicit_evaluation else len(stage_plan),
                            "overall_score": overall_score,
                            "coverage_score": coverage_score,
                            "runner_score": runner_score,
                            "stack_score": stack_score,
                            "rubric_scores": rubric_scores,
                            "coverage_checks": coverage_checks,
                            "runner_checks": runner_checks,
                            "stack_checks": stack_checks,
                            "stages": stages,
                            "implementation_excerpt": implementation_excerpt,
                            "has_code_submission": has_code_submission,
                            "code_signal_score": code_signal_score,
                        },
                    )
                elif module_type == "sql_live":
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

                    explicit_evaluation = (
                        full_report_json.get("sql_live_evaluation")
                        if isinstance(full_report_json.get("sql_live_evaluation"), dict)
                        else None
                    )
                    stages: list[dict] = []
                    rubric_scores = []
                    validation_checks = []
                    overall_score = None
                    validation_score = None
                    query_excerpt = None
                    has_query_submission = False
                    if explicit_evaluation:
                        explicit_stages = explicit_evaluation.get("stages")
                        if isinstance(explicit_stages, list):
                            for stage in explicit_stages:
                                if not isinstance(stage, dict):
                                    continue
                                stages.append(
                                    {
                                        "stage_key": str(stage.get("stage_key") or "").strip(),
                                        "stage_title": str(stage.get("stage_title") or "").strip(),
                                        "question_numbers": [
                                            int(item)
                                            for item in stage.get("question_numbers", [])
                                            if isinstance(item, int)
                                        ],
                                        "average_answer_quality": stage.get("average_answer_quality"),
                                        "stage_score": stage.get("stage_score"),
                                        "evidence_items": [
                                            str(item).strip()
                                            for item in stage.get("evidence_items", [])
                                            if str(item).strip()
                                        ],
                                    }
                                )
                        explicit_rubrics = explicit_evaluation.get("rubric_scores")
                        if isinstance(explicit_rubrics, list):
                            rubric_scores = [
                                {
                                    "rubric_key": str(item.get("rubric_key") or "").strip(),
                                    "score": item.get("score"),
                                }
                                for item in explicit_rubrics
                                if isinstance(item, dict) and str(item.get("rubric_key") or "").strip()
                            ]
                        explicit_checks = explicit_evaluation.get("validation_checks")
                        if isinstance(explicit_checks, list):
                            validation_checks = [
                                {
                                    "check_key": str(item.get("check_key") or "").strip(),
                                    "title": str(item.get("title") or "").strip(),
                                    "status": str(item.get("status") or "missed").strip(),
                                    "score": item.get("score"),
                                    "evidence": str(item.get("evidence") or "").strip() or None,
                                }
                                for item in explicit_checks
                                if isinstance(item, dict) and str(item.get("check_key") or "").strip()
                            ]
                        overall_score = explicit_evaluation.get("overall_score")
                        validation_score = explicit_evaluation.get("validation_score")
                        query_excerpt = str(explicit_evaluation.get("query_excerpt") or "").strip() or None
                        has_query_submission = bool(explicit_evaluation.get("has_query_submission"))
                    else:
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
                                    "stage_score": None,
                                    "evidence_items": evidence_items[:3],
                                }
                            )

                    _set_value(
                        data,
                        "sql_live_summary",
                        {
                            "module_title": (
                                explicit_evaluation.get("module_title")
                                if explicit_evaluation and explicit_evaluation.get("module_title")
                                else module_title
                            ),
                            "scenario_id": (
                                explicit_evaluation.get("scenario_id")
                                if explicit_evaluation and explicit_evaluation.get("scenario_id")
                                else module_session["scenario_id"] if module_session else None
                            ),
                            "scenario_title": (
                                explicit_evaluation.get("scenario_title")
                                if explicit_evaluation and explicit_evaluation.get("scenario_title")
                                else module_session["scenario_title"] if module_session else None
                            ),
                            "scenario_prompt": (
                                explicit_evaluation.get("scenario_prompt")
                                if explicit_evaluation and explicit_evaluation.get("scenario_prompt")
                                else module_session["scenario_prompt"] if module_session else None
                            ),
                            "stage_count": int(explicit_evaluation.get("stage_count") or len(stage_plan)) if explicit_evaluation else len(stage_plan),
                            "overall_score": overall_score,
                            "validation_score": validation_score,
                            "rubric_scores": rubric_scores,
                            "validation_checks": validation_checks,
                            "stages": stages,
                            "query_excerpt": query_excerpt,
                            "has_query_submission": has_query_submission,
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
        self.development_roadmap = _build_development_roadmap(self)
        return self


def _build_development_roadmap(report: AssessmentReportResponse) -> DevelopmentRoadmap | None:
    def _clean(items: list[str] | None) -> list[str]:
        if not items:
            return []
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            normalized = str(item or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
        return result

    strengths = _clean(report.strengths)
    weaknesses = _clean(report.weaknesses)
    recommendations = _clean(report.recommendations)
    if not strengths and not weaknesses and not recommendations:
        return None

    phases = [
        DevelopmentRoadmapPhase(
            phase_key="now",
            focus=weaknesses[0] if weaknesses else (recommendations[0] if recommendations else None),
            actions=[
                item
                for item in [*recommendations[:1], *(weaknesses[:1] if not recommendations else [])]
                if item
            ],
        ),
        DevelopmentRoadmapPhase(
            phase_key="next",
            focus=weaknesses[1] if len(weaknesses) > 1 else (strengths[0] if strengths else None),
            actions=[
                item
                for item in [*recommendations[1:2], *(strengths[:1] if len(recommendations) < 2 else [])]
                if item
            ],
        ),
        DevelopmentRoadmapPhase(
            phase_key="later",
            focus=strengths[0] if strengths else (recommendations[2] if len(recommendations) > 2 else None),
            actions=[
                item
                for item in [*recommendations[2:3], *(strengths[1:2] if len(strengths) > 1 else strengths[:1])]
                if item
            ],
        ),
    ]

    normalized_phases = [
        DevelopmentRoadmapPhase(
            phase_key=phase.phase_key,
            focus=phase.focus,
            actions=_clean(phase.actions)[:2],
        )
        for phase in phases
        if phase.focus or phase.actions
    ]
    if not normalized_phases:
        return None
    return DevelopmentRoadmap(phases=normalized_phases)
