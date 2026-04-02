"""Unit tests for interview question and skill-tag quality controls."""

from app.ai.assessor import (
    _aggregate_skills,
    _apply_recommendation_gates,
    _apply_summary_penalties,
    _build_outcome_feedback,
    _build_mock_competency_scores,
    _build_mock_question_analysis,
    _build_summary_model,
    _compute_confidence_metrics,
    _prefer_outcome_feedback,
)
from app.ai.interviewer import (
    InterviewContext,
    _competency_anchored_main_question,
    _normalize_question_output,
    _resume_anchored_first_question,
)
from app.services.interview_service import _build_diversification_hint, _is_topic_saturated


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
    assert len(normalized) <= 170
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
    assert len(question) <= 170


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


def test_apply_summary_penalties_keeps_broad_relevant_partial_signal_above_hard_floor():
    aggregates = {
        "overall_score": 7.6,
        "hard_skills_score": 7.8,
        "soft_skills_score": 7.1,
        "communication_score": 7.0,
        "problem_solving_score": 7.4,
    }
    summary_model = {
        "core_topics": 8,
        "validated_topics": 0,
        "partial_topics": 6,
        "unverified_claim_topics": 1,
        "honest_gaps": 0,
        "signal_quality": "limited",
        "strong_topics": 1,
        "generic_or_evasive_topics": 1,
    }
    adjusted, penalties = _apply_summary_penalties(
        aggregates,
        summary_model,
        {"overall_confidence": 0.62},
    )

    assert adjusted["overall_score"] >= 6.8
    assert any("broad_relevant_partial_signal" in item or "relevant_partial_depth" in item for item in penalties)


def test_prefer_outcome_feedback_replaces_generic_fillers_with_specific_points():
    current = [
        "Завершил полное структурированное собеседование",
        "Ответы могут включать более конкретные метрики",
    ]
    generated = [
        "Есть содержательная база по темам: PostgreSQL, Kafka.",
        "По 1 заявленной технологии не удалось подтвердить hands-on опыт (Docker).",
    ]

    result = _prefer_outcome_feedback(current, generated)

    assert result[0].startswith("Есть содержательная база")
    assert all("Завершил полное структурированное собеседование" not in item for item in result)


def test_topic_saturation_marks_relevant_partial_after_probe_as_enough_signal():
    saturated, reason = _is_topic_saturated(
        current_signal="partial",
        answer_class="partial",
        answer_relevance="high",
        topic_turns=1,
        last_question_type="verification",
    )

    assert saturated is True
    assert reason in {"topic_saturated", "enough_partial_signal"}


def test_competency_anchored_main_question_uses_different_angle_hint():
    ctx = InterviewContext(
        target_role="backend_engineer",
        question_number=6,
        language="ru",
        competency_targets=["Security & Error Handling"],
        diversification_hint="Смени угол и сфокусируйся на теме «Security & Error Handling». Не продолжай спрашивать про kafka.",
    )

    question = _competency_anchored_main_question(ctx)

    assert "безопас" in question.lower() or "auth" in question.lower()


def test_mock_question_analysis_promotes_concrete_partial_answer_to_high_signal():
    per_q = _build_mock_question_analysis(
        message_history=[
            {"role": "assistant", "content": "Как вы оптимизировали PostgreSQL под высокой нагрузкой?"},
            {
                "role": "candidate",
                "content": (
                    "Я анализировал query plan через EXPLAIN ANALYZE, убирал лишние seq scan, "
                    "подбирал составные индексы и после этого снижал latency на горячих запросах."
                ),
            },
        ],
        target_role="backend_engineer",
        interview_meta={
            "topic_plan": [
                {
                    "competencies": ["Database Design & Optimization"],
                    "verification_target": "postgresql",
                }
            ]
        },
        report_language="ru",
    )

    assert per_q[0]["answer_quality"] >= 7.2
    assert per_q[0]["depth"] in {"strong", "expert", "adequate"}
    assert per_q[0]["specificity"] in {"medium", "high"}


def test_summary_model_marks_validated_topic_for_concrete_mechanistic_answer():
    per_q = [
        {
            "question_number": 1,
            "targeted_competencies": ["Database Design & Optimization"],
            "answer_quality": 7.3,
            "evidence": "Использовал EXPLAIN ANALYZE, проверял query plan и пересобирал индексы под горячие запросы.",
            "skills_mentioned": [{"skill": "postgresql", "proficiency": "advanced"}],
            "red_flags": [],
            "specificity": "medium",
            "depth": "adequate",
            "ai_likelihood": 0.1,
        }
    ]

    summary = _build_summary_model(
        "backend_engineer",
        "ru",
        {
            "question_count": 1,
            "turn_count": 1,
            "topic_plan": [
                {
                    "competencies": ["Database Design & Optimization"],
                    "verification_target": "postgresql",
                }
            ],
            "topic_signals": ["partial"],
            "verified_skills": ["postgresql"],
        },
        per_q,
    )

    assert summary["validated_topics"] == 1
    assert summary["topic_outcomes"][0]["outcome"] == "validated"


def test_mock_competency_scores_raise_validated_topic_into_seven_plus_range():
    per_q = [
        {
            "question_number": 1,
            "targeted_competencies": ["Database Design & Optimization"],
            "answer_quality": 8.1,
            "evidence": "Использовал EXPLAIN ANALYZE и составные индексы для горячих запросов.",
            "skills_mentioned": [{"skill": "postgresql", "proficiency": "expert"}],
            "red_flags": [],
            "specificity": "high",
            "depth": "strong",
            "ai_likelihood": 0.05,
        }
    ]
    summary = {
        "topic_outcomes": [
            {
                "slot": 1,
                "label": "PostgreSQL",
                "signal": "strong",
                "outcome": "validated",
            }
        ]
    }

    comp_scores = _build_mock_competency_scores(
        target_role="backend_engineer",
        summary_model=summary,
        interview_meta={
            "topic_plan": [
                {
                    "competencies": ["Database Design & Optimization"],
                    "verification_target": "postgresql",
                }
            ]
        },
        report_language="ru",
        per_question_analysis=per_q,
    )

    target = next(item for item in comp_scores if item["competency"] == "Database Design & Optimization")
    assert target["score"] >= 8.0


def test_summary_model_does_not_inflate_generic_count_when_topics_are_partial():
    summary = _build_summary_model(
        "backend_engineer",
        "ru",
        {
            "question_count": 4,
            "turn_count": 4,
            "topic_plan": [
                {"competencies": ["Database Design & Optimization"], "verification_target": "postgresql"},
                {"competencies": ["API Design & Protocols"]},
                {"competencies": ["Technical Communication"]},
                {"competencies": ["DevOps & Infrastructure"], "verification_target": "docker"},
            ],
            "topic_signals": ["generic", "partial", "generic", "strong"],
            "verified_skills": ["postgresql", "docker"],
            "probed_claim_targets": ["postgresql", "docker"],
        },
        [
            {
                "question_number": 1,
                "targeted_competencies": ["Database Design & Optimization"],
                "answer_quality": 7.4,
                "evidence": "Использовал EXPLAIN ANALYZE и составные индексы.",
                "skills_mentioned": [{"skill": "postgresql", "proficiency": "advanced"}],
                "red_flags": [],
                "specificity": "medium",
                "depth": "adequate",
                "ai_likelihood": 0.1,
            },
            {
                "question_number": 4,
                "targeted_competencies": ["DevOps & Infrastructure"],
                "answer_quality": 8.1,
                "evidence": "Собирал multi-stage Docker image и проверял healthcheck.",
                "skills_mentioned": [{"skill": "docker", "proficiency": "advanced"}],
                "red_flags": [],
                "specificity": "high",
                "depth": "strong",
                "ai_likelihood": 0.05,
            },
        ],
    )

    assert summary["validated_topics"] >= 2
    assert summary["generic_or_evasive_topics"] <= 1


def test_summary_model_marks_broad_partial_signal_as_medium_when_noise_is_limited():
    summary = _build_summary_model(
        "backend_engineer",
        "ru",
        {
            "question_count": 8,
            "turn_count": 8,
            "topic_plan": [{"competencies": ["Database Design & Optimization"]}] * 8,
            "topic_signals": ["partial", "partial", "partial", "partial", "partial", "partial", "generic", "generic"],
            "verified_skills": [],
            "probed_claim_targets": ["kafka", "docker"],
        },
        [],
    )

    assert summary["signal_quality"] == "medium"


def test_summary_penalties_stay_softer_with_multiple_validated_topics():
    adjusted, penalties = _apply_summary_penalties(
        {
            "overall_score": 8.2,
            "hard_skills_score": 8.3,
            "soft_skills_score": 7.1,
            "communication_score": 7.4,
            "problem_solving_score": 7.8,
        },
        {
            "core_topics": 8,
            "validated_topics": 4,
            "partial_topics": 4,
            "unverified_claim_topics": 0,
            "honest_gaps": 0,
            "signal_quality": "medium",
            "strong_topics": 2,
            "generic_or_evasive_topics": 1,
        },
        {"overall_confidence": 0.68},
    )

    assert adjusted["overall_score"] >= 7.5
    assert any("multiple_validated_topics" in item or "medium_signal_with_multiple_validated_topics" in item for item in penalties)


def test_summary_penalties_allow_high_signal_many_validated_topics_to_stay_above_seven():
    adjusted, penalties = _apply_summary_penalties(
        {
            "overall_score": 8.4,
            "hard_skills_score": 8.6,
            "soft_skills_score": 7.2,
            "communication_score": 7.3,
            "problem_solving_score": 8.0,
        },
        {
            "core_topics": 8,
            "validated_topics": 4,
            "partial_topics": 4,
            "unverified_claim_topics": 0,
            "honest_gaps": 0,
            "signal_quality": "high",
            "strong_topics": 3,
            "generic_or_evasive_topics": 0,
        },
        {"overall_confidence": 0.74},
    )

    assert adjusted["overall_score"] >= 8.0
    assert any("high_signal_with_many_validated_topics" in item for item in penalties)


def test_outcome_feedback_for_partial_topics_is_specific_not_template():
    strengths, weaknesses, recommendations = _build_outcome_feedback(
        {
            "validated_topics": 3,
            "partial_topics": 2,
            "unverified_claim_topics": 0,
            "honest_gaps": 0,
            "evasive_topics": 0,
            "strong_topics": 2,
            "topic_outcomes": [
                {"label": "PostgreSQL", "outcome": "validated", "signal": "strong"},
                {"label": "Redis", "outcome": "validated", "signal": "strong"},
                {"label": "Kafka", "outcome": "validated", "signal": "partial"},
                {"label": "API Design", "outcome": "partial", "signal": "partial"},
                {"label": "Docker", "outcome": "partial", "signal": "partial"},
            ],
        },
        "ru",
    )

    assert strengths
    assert weaknesses
    assert all("Завершил полное структурированное собеседование" not in item for item in strengths + weaknesses)
    assert any("API Design" in item or "Docker" in item for item in weaknesses)


def test_outcome_feedback_softens_strength_for_weak_candidate():
    strengths, weaknesses, _ = _build_outcome_feedback(
        {
            "validated_topics": 0,
            "partial_topics": 1,
            "unverified_claim_topics": 0,
            "honest_gaps": 7,
            "evasive_topics": 0,
            "strong_topics": 0,
            "topic_outcomes": [
                {"label": "Сотрудничество и код-ревью", "outcome": "partial", "signal": "partial", "evidence_hint": "Дал очень общий ответ про код-ревью"},
                {"label": "PostgreSQL", "outcome": "honest_gap", "signal": "no_experience_honest"},
            ],
        },
        "ru",
    )

    assert strengths
    assert strengths[0].startswith("Есть только базовый сигнал")
    assert any("Постгре" not in item for item in weaknesses) or weaknesses


def test_recommendation_gate_allows_yes_for_high_signal_validated_interview():
    recommendation, reasons = _apply_recommendation_gates(
        llm_rec="yes",
        overall_score=6.9,
        summary_model={
            "core_topics": 8,
            "signal_quality": "high",
            "strong_topics": 3,
            "validated_topics": 4,
            "honest_gaps": 0,
            "generic_or_evasive_topics": 0,
        },
        answer_metrics={"short_answer_ratio": 0.0, "avg_answer_quality": 7.1},
        confidence_metrics={"overall_confidence": 0.66},
        competency_scores=[
            {"score": 8.2},
            {"score": 7.9},
            {"score": 7.1},
        ],
    )

    assert recommendation == "yes"
    assert all("yes requires stable medium-or-better evidence" not in item for item in reasons)


def test_build_diversification_hint_mentions_new_focus_and_old_topic():
    hint = _build_diversification_hint(
        next_target={"competencies": ["Security & Error Handling"], "verification_target": "docker"},
        current_target={"competencies": ["Database Design & Optimization"], "verification_target": "postgresql"},
        closed_reason="topic_saturated",
        language="ru",
    )

    assert hint
    assert "не продолжай спрашивать про postgresql" in hint.lower()
    assert "docker" in hint.lower()
