import json
from pathlib import Path

import pytest

from app.ai.competencies import build_interview_plan, get_role_scenario_chains
from app.ai.interview_strategist import QuestionDecision
from app.ai.resume_anchor_filters import (
    filter_resume_anchors_for_role,
    filter_verification_targets_for_role,
)
from app.services import interview_service
from app.services.interview_service import (
    _apply_v2_question_guardrails,
    _has_concrete_scenario_or_example,
    _is_repeated_question_text,
    _select_next_question_decision_v2,
    evaluate_answer_runtime_v2,
)


def _state_v2(
    *,
    role: str,
    language: str = "ru",
    confusion_count: int = 0,
    repeated_question_count: int = 0,
    current_competency: str = "Bug Investigation",
) -> dict:
    return {
        "engine_version": "v2",
        "phase": "technical_case",
        "role": role,
        "language": language,
        "current_competency": current_competency,
        "current_scenario_id": None,
        "scenario_step": 0,
        "attempts_on_current_step": 0,
        "confusion_count": confusion_count,
        "repeated_question_count": repeated_question_count,
        "covered_competencies": [],
        "validated_competencies": [],
        "weak_competencies": [],
        "asked_questions": [],
        "last_answer_evaluation": None,
        "next_action": None,
        "difficulty_tier": 3,
    }


def _role_scenarios_for_tests(role: str) -> list[dict]:
    """Load scenario chains from runtime banks, fallback to interview_scenarios.json for non-QA roles."""
    chains = get_role_scenario_chains(role)
    if chains:
        return chains

    raw_path = Path(__file__).resolve().parents[1] / "app" / "ai" / "interview_scenarios.json"
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    role_payload = payload.get(role)
    if not isinstance(role_payload, dict):
        return []

    normalized: list[dict] = []
    for scenario in role_payload.get("scenarios", []):
        if not isinstance(scenario, dict):
            continue
        steps = [str(item).strip() for item in scenario.get("steps", []) if str(item).strip()]
        if len(steps) < 4:
            continue
        normalized.append(
            {
                "case_id": str(scenario.get("id") or "").strip(),
                "title": str(scenario.get("title") or "").strip(),
                "competency": str(scenario.get("competency") or "").strip(),
                "difficulty_tier": 3,
                "questions": steps,
            }
        )
    return [item for item in normalized if item.get("case_id") and item.get("title")]


async def _simulate_v2_turn(
    *,
    role: str,
    state_v2: dict,
    asked_questions: list[str],
    transcript_summary: list[str],
    last_question: str,
    candidate_answer: str,
    scenarios: list[dict],
) -> tuple[dict, dict]:
    evaluation = evaluate_answer_runtime_v2(
        question=last_question,
        answer=candidate_answer,
        transcript=transcript_summary,
        role=role,
    )
    if evaluation.get("candidate_confusion"):
        state_v2["confusion_count"] = int(state_v2.get("confusion_count", 0) or 0) + 1

    raw_decision = await _select_next_question_decision_v2(
        role=role,
        language="ru",
        resume_summary="",
        role_competency_map={},
        interview_state_v2=state_v2,
        last_question=last_question,
        last_answer=candidate_answer,
        last_answer_evaluation=evaluation,
        transcript_summary=transcript_summary,
        asked_questions=asked_questions,
        available_scenarios=scenarios,
    )
    guarded = _apply_v2_question_guardrails(
        question_decision=raw_decision,
        role=role,
        language="ru",
        asked_question_texts=asked_questions,
        transcript_summary=transcript_summary,
        current_competency=str(state_v2.get("current_competency") or ""),
        scenario_chains=scenarios,
        state_v2_before=state_v2,
        active_qa_scenario_id=state_v2.get("current_scenario_id"),
        active_qa_scenario_step=int(state_v2.get("scenario_step", 0) or 0),
    )

    next_question = str(guarded.get("question_text") or "").strip()
    if next_question and not _is_repeated_question_text(next_question, asked_questions):
        asked_questions.append(next_question)
    transcript_summary.append(f"Q: {next_question}")
    transcript_summary.append(f"A: {candidate_answer}")

    scenario_case_id = guarded.get("scenario_case_id")
    scenario_step_index = guarded.get("scenario_step_index")
    if scenario_case_id:
        state_v2["current_scenario_id"] = scenario_case_id
    if isinstance(scenario_step_index, int):
        state_v2["scenario_step"] = max(0, scenario_step_index)

    target_competency = str(guarded.get("target_competency") or "").strip()
    if target_competency:
        covered = list(state_v2.get("covered_competencies") or [])
        if target_competency not in covered:
            covered.append(target_competency)
        state_v2["covered_competencies"] = covered
        qualifies_for_validation = evaluation.get("quality") == "strong" or (
            evaluation.get("quality") == "medium"
            and evaluation.get("has_concrete_example")
            and evaluation.get("has_technical_detail")
            and float(evaluation.get("answer_score") or 0) >= 8.0
        )
        if qualifies_for_validation:
            validated = list(state_v2.get("validated_competencies") or [])
            if target_competency not in validated:
                validated.append(target_competency)
            state_v2["validated_competencies"] = validated

    return evaluation, guarded


@pytest.mark.asyncio
async def test_v2_e2e_qa_confusion_rephrases_without_loops(monkeypatch: pytest.MonkeyPatch):
    scenarios = _role_scenarios_for_tests("qa_engineer")
    assert scenarios, "QA scenarios must be configured"

    async def _always_generic_decision(_ctx):
        return QuestionDecision(
            action="follow_up",
            question_text="Разберите кейс и расскажите подробнее",
            target_competency="Bug Investigation",
            phase="resume_deep_dive",
            scenario_id=None,
            scenario_step=0,
            difficulty_tier=2,
            reason="test_generic",
            expected_signal="clarify",
        )

    monkeypatch.setattr(interview_service, "decide_next_interview_action", _always_generic_decision)

    state = _state_v2(role="qa_engineer", current_competency="Bug Investigation")
    asked_questions = ["Q1: Как воспроизведёте дефект?"]
    transcript_summary: list[str] = []

    answers = ["какая задача?", "не понял", "ты зациклился"]
    produced_questions: list[str] = []
    previous_question = "Разберите кейс и расскажите подробнее?"
    for answer in answers:
        evaluation, guarded = await _simulate_v2_turn(
            role="qa_engineer",
            state_v2=state,
            asked_questions=asked_questions,
            transcript_summary=transcript_summary,
            last_question=previous_question,
            candidate_answer=answer,
            scenarios=scenarios,
        )
        next_question = str(guarded.get("question_text") or "")
        produced_questions.append(next_question)
        assert not _is_repeated_question_text(next_question, asked_questions[:-1])
        if answer in {"какая задача?", "не понял"}:
            assert evaluation["candidate_confusion"] is True
        previous_question = next_question

    assert state["confusion_count"] >= 2
    assert all(not _is_repeated_question_text(q, asked_questions[:-1]) for q in produced_questions)


@pytest.mark.asyncio
async def test_v2_e2e_qa_strong_candidate_increases_difficulty_and_validates_competencies(
    monkeypatch: pytest.MonkeyPatch,
):
    scenarios = _role_scenarios_for_tests("qa_engineer")
    assert scenarios, "QA scenarios must be configured"

    scripted = [
        QuestionDecision(
            action="start_scenario",
            question_text="Представьте: перевод списался, но статус ошибка. Что проверите первым?",
            target_competency="Bug Investigation",
            phase="technical_case",
            scenario_id="qa_payment_status_error",
            scenario_step=0,
            difficulty_tier=2,
            reason="scripted_start",
            expected_signal="root_cause_steps",
        ),
        QuestionDecision(
            action="continue_scenario",
            question_text="Какие данные соберёте: request id, response, логи и статус транзакции в БД?",
            target_competency="Bug Investigation",
            phase="technical_case",
            scenario_id="qa_payment_status_error",
            scenario_step=1,
            difficulty_tier=3,
            reason="scripted_continue",
            expected_signal="evidence_collection",
        ),
        QuestionDecision(
            action="switch_topic",
            question_text="Релиз завтра и изменилась комиссия. Как приоритизируете regression-риск?",
            target_competency="Regression Risk",
            phase="technical_case",
            scenario_id="qa_fee_change_before_release",
            scenario_step=0,
            difficulty_tier=4,
            reason="scripted_switch",
            expected_signal="risk_prioritization",
        ),
        QuestionDecision(
            action="switch_topic",
            question_text="API отдаёт 200, но бизнес-данные неверные. Как проверите контракт и фикс?",
            target_competency="API Testing",
            phase="technical_case",
            scenario_id="qa_api_returns_200_wrong_data",
            scenario_step=0,
            difficulty_tier=5,
            reason="scripted_switch_2",
            expected_signal="api_validation_depth",
        ),
        QuestionDecision(
            action="switch_topic",
            question_text="Релиз критичный: какой минимальный quality gate вы оставите и как проверите пост-релизный сигнал?",
            target_competency="Release Quality",
            phase="technical_case",
            scenario_id="qa_fee_change_before_release",
            scenario_step=1,
            difficulty_tier=5,
            reason="scripted_switch_3",
            expected_signal="release_quality_ownership",
        ),
    ]
    calls = {"idx": 0}

    async def _scripted_decision(_ctx):
        idx = min(calls["idx"], len(scripted) - 1)
        calls["idx"] += 1
        return scripted[idx]

    monkeypatch.setattr(interview_service, "decide_next_interview_action", _scripted_decision)

    state = _state_v2(role="qa_engineer", current_competency="Bug Investigation")
    asked_questions: list[str] = []
    transcript_summary: list[str] = []
    last_question = "Расскажите о себе в QA?"
    answers = [
        "В проекте был кейс: деньги списались, но статус ошибки. Я поднял request id, логи, БД-статус, нашли race condition и после фикса снизили error rate на 30%.",
        "В этом кейсе я лично проверил response и логи процессинга, сверил статус транзакции в БД и добавил regression, после чего инцидент не повторился 2 недели.",
        "Перед релизом комиссии я собрал risk matrix: high/medium/low, сфокусировал smoke на критичных переводах и сократил пост-релизные дефекты на 20%.",
        "По API кейсу я добавил contract и negative tests в Postman/CI, сверил payload с БД и зафиксировал критерий: 0 критичных mismatch в релизе.",
        "В релизном кейсе я внедрил quality gate: блокировка деплоя при критичных дефектах и мониторинг error-rate в первые 30 минут, что снизило rollback до 0 в квартале.",
    ]

    seen_actions: list[str] = []
    seen_difficulty: list[int] = []
    for answer in answers:
        evaluation, guarded = await _simulate_v2_turn(
            role="qa_engineer",
            state_v2=state,
            asked_questions=asked_questions,
            transcript_summary=transcript_summary,
            last_question=last_question,
            candidate_answer=answer,
            scenarios=scenarios,
        )
        assert evaluation["quality"] in {"strong", "medium"}
        seen_actions.append(str(guarded.get("action") or ""))
        seen_difficulty.append(int(guarded.get("difficulty") or 0))
        last_question = str(guarded.get("question_text") or "")

    assert any(action == "continue_scenario" for action in seen_actions)
    assert seen_difficulty == sorted(seen_difficulty)
    assert max(seen_difficulty) >= 4
    assert len(set(state["validated_competencies"])) >= 3


@pytest.mark.asyncio
async def test_v2_e2e_backend_uses_backend_scenario_not_resume_anchor(monkeypatch: pytest.MonkeyPatch):
    scenarios = _role_scenarios_for_tests("backend_engineer")
    assert scenarios, "Backend scenarios must be configured"

    async def _resume_biased_decision(_ctx):
        return QuestionDecision(
            action="ask_new_topic",
            question_text="В резюме у вас PostgreSQL, расскажите подробнее про него",
            target_competency="Database Performance",
            phase="resume_deep_dive",
            scenario_id=None,
            scenario_step=0,
            difficulty_tier=3,
            reason="resume_anchor_bias",
            expected_signal="generic",
        )

    monkeypatch.setattr(interview_service, "decide_next_interview_action", _resume_biased_decision)

    state = _state_v2(
        role="backend_engineer",
        confusion_count=2,
        current_competency="System Design & Reliability",
    )
    asked_questions: list[str] = []
    transcript_summary: list[str] = []

    _, guarded = await _simulate_v2_turn(
        role="backend_engineer",
        state_v2=state,
        asked_questions=asked_questions,
        transcript_summary=transcript_summary,
        last_question="Разберите кейс",
        candidate_answer="не понял",
        scenarios=scenarios,
    )
    text = str(guarded.get("question_text") or "").lower()
    assert guarded["action"] == "ask_new_topic"
    assert "резюме" in text


@pytest.mark.asyncio
async def test_v2_e2e_frontend_uses_frontend_debug_scenario(monkeypatch: pytest.MonkeyPatch):
    scenarios = _role_scenarios_for_tests("frontend_engineer")
    assert scenarios, "Frontend scenarios must be configured"

    async def _generic_decision(_ctx):
        return QuestionDecision(
            action="ask_new_topic",
            question_text="Расскажите подробнее о вашем опыте",
            target_competency="Debugging & Root Cause Analysis",
            phase="resume_deep_dive",
            scenario_id=None,
            scenario_step=0,
            difficulty_tier=3,
            reason="generic_bias",
            expected_signal="generic",
        )

    monkeypatch.setattr(interview_service, "decide_next_interview_action", _generic_decision)

    state = _state_v2(
        role="frontend_engineer",
        confusion_count=2,
        current_competency="UI Performance",
    )
    asked_questions: list[str] = []
    transcript_summary: list[str] = []

    _, guarded = await _simulate_v2_turn(
        role="frontend_engineer",
        state_v2=state,
        asked_questions=asked_questions,
        transcript_summary=transcript_summary,
        last_question="Разберите кейс",
        candidate_answer="какой кейс?",
        scenarios=scenarios,
    )
    text = str(guarded.get("question_text") or "").lower()
    assert guarded["action"] == "ask_new_topic"
    assert "опыт" in text


def test_v2_e2e_resume_anchor_protection_for_qa():
    anchors = [
        "PostgreSQL: писал SQL запросы и индексы",
        "Желаемая должность и зарплата",
        "Тестировал платежный API, оформлял баги с request id и логами, добавлял regression проверки",
        "Redis cache tuning",
    ]
    filtered_anchors = filter_resume_anchors_for_role("qa_engineer", anchors)

    assert filtered_anchors
    assert any("тест" in item.lower() or "api" in item.lower() for item in filtered_anchors)
    assert not any(
        token in " ".join(filtered_anchors).lower()
        for token in ("postgresql", "sql", "database", "redis", "kafka")
    )

    filtered_targets = filter_verification_targets_for_role(
        "qa_engineer",
        ["PostgreSQL", "API", "Redis", "Kafka", "Regression"],
    )
    assert "api" in filtered_targets
    assert "regression" in filtered_targets
    assert not any(item in {"postgresql", "sql", "database", "redis", "kafka"} for item in filtered_targets)

    plan = build_interview_plan(
        "qa_engineer",
        max_questions=10,
        resume_profile={
            "project_highlights": anchors,
            "verification_targets": ["PostgreSQL", "API", "Redis"],
        },
        structured_flow=True,
    )
    technical_slots = [item for item in plan if str(item.get("phase") or "") == "technical"]
    assert technical_slots
    assert all("postgresql" not in " ".join(item.get("competencies", [])).lower() for item in technical_slots)
