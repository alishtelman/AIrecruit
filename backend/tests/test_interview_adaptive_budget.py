from app.services.interview_service import (
    _adapt_question_budget,
    _append_candidate_memory,
    _estimate_dynamic_question_budget,
)


def test_adapt_question_budget_extends_for_strong_signal_near_limit():
    adapted, should_end, decision = _adapt_question_budget(
        current_max_questions=14,
        current_question_count=12,
        answer_count=5,
        strong_answers_count=3,
        weak_answers_count=1,
        low_relevance_answers_count=1,
        consecutive_weak_answers=0,
        min_questions_before_early_stop=10,
        role_max_cap=24,
    )

    assert adapted == 18
    assert should_end is False
    assert decision == "extended_for_strong_signal"


def test_adapt_question_budget_reduces_early_for_mixed_low_signal():
    adapted, should_end, decision = _adapt_question_budget(
        current_max_questions=24,
        current_question_count=7,
        answer_count=5,
        strong_answers_count=0,
        weak_answers_count=4,
        low_relevance_answers_count=2,
        consecutive_weak_answers=2,
        min_questions_before_early_stop=10,
        role_max_cap=40,
    )

    assert adapted == 10
    assert should_end is False
    assert decision == "reduced_for_mixed_low_signal"


def test_append_candidate_memory_keeps_honest_short_gap():
    memory = _append_candidate_memory(
        [],
        answer="Не делал интеграцию с Kubernetes и не настраивал её в production.",
        answer_class="no_experience_honest",
        answer_relevance="low",
        new_techs=set(),
    )

    assert len(memory) == 1
    assert memory[0].lower().startswith("honest gap noted:")


def test_append_candidate_memory_deduplicates_similar_facts():
    answer = (
        "Я использовал PostgreSQL в production, анализировал EXPLAIN ANALYZE, "
        "оптимизировал индексы и снизил latency на горячих запросах."
    )
    first = _append_candidate_memory(
        [],
        answer=answer,
        answer_class="strong",
        answer_relevance="high",
        new_techs={"postgresql"},
    )
    second = _append_candidate_memory(
        first,
        answer=answer,
        answer_class="strong",
        answer_relevance="high",
        new_techs={"postgresql"},
    )

    assert len(second) == 1
    assert "[tech: postgresql]" in second[0].lower()


def test_estimate_dynamic_question_budget_uses_role_floor_for_rich_resume():
    initial, cap, min_questions = _estimate_dynamic_question_budget(
        target_role="designer",
        resume_profile={
            "technologies": ["figma", "framer"],
            "project_highlights": ["product redesign"],
            "experience_years": 2,
            "seniority_hint": "middle",
        },
    )

    assert initial >= 8
    assert cap == 30
    assert min_questions == 8


def test_estimate_dynamic_question_budget_keeps_legacy_sparse_resume_behavior():
    initial, cap, min_questions = _estimate_dynamic_question_budget(
        target_role="backend_engineer",
        resume_profile={},
    )

    assert initial == 8
    assert cap == 8
    assert min_questions == 9
