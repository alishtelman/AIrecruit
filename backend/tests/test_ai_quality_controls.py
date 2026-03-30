"""Unit tests for interview question and skill-tag quality controls."""

from app.ai.assessor import _aggregate_skills, _compute_confidence_metrics
from app.ai.interviewer import (
    InterviewContext,
    _normalize_question_output,
    _resume_anchored_first_question,
)


def test_normalize_question_output_keeps_single_concise_question():
    ctx = InterviewContext(target_role="backend_engineer", question_number=2, language="en")
    raw = (
        "I understand this can be complex and requires broad experience. "
        "How would you design a PostgreSQL schema for a high-load service with failover? "
        "What indexing strategy would you choose for mixed OLTP and analytics traffic?"
    )

    normalized = _normalize_question_output(raw, ctx)

    assert normalized.endswith("?")
    assert normalized.count("?") == 1
    assert len(normalized) <= 240
    assert "I understand" not in normalized


def test_normalize_question_output_fallback_without_question_mark():
    ctx = InterviewContext(target_role="backend_engineer", question_number=3, language="en")
    raw = "Great answer. Tell me more about your most recent production incident and your role"

    normalized = _normalize_question_output(raw, ctx)

    assert normalized == "Tell me more about your most recent production incident and your role?"


def test_resume_anchored_first_question_uses_resume_line_context():
    ctx = InterviewContext(
        target_role="backend_engineer",
        question_number=1,
        language="ru",
        resume_text=(
            "Backend Engineer, Acme Payments\n"
            "Python, FastAPI, PostgreSQL\n"
            "Снизил p95 API latency на 35%"
        ),
    )

    question = _resume_anchored_first_question(ctx)

    assert "Acme Payments" in question
    assert question.endswith("?")
    assert len(question) <= 240


def test_resume_anchored_first_question_has_safe_fallback_without_resume():
    ctx = InterviewContext(
        target_role="backend_engineer",
        question_number=1,
        language="en",
        resume_text=None,
    )

    question = _resume_anchored_first_question(ctx)

    assert question.startswith("Based on your resume")
    assert question.endswith("?")


def test_aggregate_skills_filters_low_evidence_noise():
    per_question = [
        {
            "answer_quality": 3.5,
            "specificity": "low",
            "depth": "surface",
            "ai_likelihood": 0.1,
            "evidence": "Generic answer without practical details.",
            "skills_mentioned": [
                {"skill": "postgresql", "proficiency": "advanced"},
                {"skill": "rest", "proficiency": "advanced"},
            ],
        }
    ]

    assert _aggregate_skills(per_question) == []


def test_aggregate_skills_keeps_high_signal_and_drops_generic_terms():
    per_question = [
        {
            "answer_quality": 8.4,
            "specificity": "high",
            "depth": "strong",
            "ai_likelihood": 0.1,
            "evidence": "I tuned PostgreSQL query plans and partitioning in production systems.",
            "skills_mentioned": [
                {"skill": "PostgreSQL", "proficiency": "advanced"},
                {"skill": "Python", "proficiency": "intermediate"},
                {"skill": "REST", "proficiency": "advanced"},
            ],
        },
        {
            "answer_quality": 7.2,
            "specificity": "medium",
            "depth": "adequate",
            "ai_likelihood": 0.2,
            "evidence": "Optimized PostgreSQL indexes and vacuum strategy to reduce p95 latency.",
            "skills_mentioned": [
                {"skill": "postgresql", "proficiency": "expert"},
            ],
        },
    ]

    result = _aggregate_skills(per_question)
    skills = {item["skill"] for item in result}
    by_skill = {item["skill"]: item for item in result}

    assert "postgresql" in skills
    assert by_skill["postgresql"]["proficiency"] == "expert"
    assert by_skill["postgresql"]["mentions_count"] == 2
    assert "python" in skills
    assert "rest" not in skills


def test_compute_confidence_metrics_scores_high_quality_interview():
    competency_scores = [
        {
            "competency": "System Design",
            "category": "technical_core",
            "score": 8.5,
            "weight": 0.35,
            "evidence": "Candidate explained sharding trade-offs and failover strategy in detail.",
            "reasoning": "Strong production examples.",
        },
        {
            "competency": "Communication",
            "category": "communication",
            "score": 7.8,
            "weight": 0.2,
            "evidence": "Answers were structured with concrete outcomes and metrics.",
            "reasoning": "Clear and concise communication.",
        },
    ]
    per_question = [
        {
            "question_number": 1,
            "targeted_competencies": ["System Design"],
            "answer_quality": 8.2,
            "evidence": "Explained replication lag mitigation and p95 impact.",
            "skills_mentioned": [],
            "red_flags": [],
            "specificity": "high",
            "depth": "strong",
            "ai_likelihood": 0.1,
        },
        {
            "question_number": 2,
            "targeted_competencies": ["Communication"],
            "answer_quality": 7.4,
            "evidence": "Described incident communication flow with clear ownership.",
            "skills_mentioned": [],
            "red_flags": [],
            "specificity": "medium",
            "depth": "adequate",
            "ai_likelihood": 0.15,
        },
    ]

    metrics = _compute_confidence_metrics(competency_scores, per_question)

    assert metrics["overall_confidence"] >= 0.65
    assert metrics["competency_confidence"]["System Design"] >= 0.7
    assert metrics["evidence_coverage"]["questions_analyzed"] == 2
    assert len(metrics["confidence_reasons"]) >= 1


def test_compute_confidence_metrics_handles_missing_evidence():
    metrics = _compute_confidence_metrics([], [])

    assert metrics["overall_confidence"] == 0.0
    assert metrics["competency_confidence"] == {}
    assert metrics["evidence_coverage"]["questions_analyzed"] == 0
    assert any("No per-question evidence" in reason for reason in metrics["confidence_reasons"])
