import pytest

from app.ai.interview_strategist import (
    InterviewStrategistContext,
    LLMInterviewStrategist,
    QuestionDecision,
    _conversation_guardrail_decision,
    _fallback_decision,
    _validate_question_decision_payload,
    parse_or_repair_strategist_response,
    decide_next_interview_action,
)


@pytest.mark.asyncio
async def test_decide_next_interview_action_returns_valid_decision_with_non_empty_question(monkeypatch: pytest.MonkeyPatch):
    ctx = InterviewStrategistContext(
        role="qa_engineer",
        language="ru",
        asked_questions=[],
        available_scenarios=[
            {
                "case_id": "qa_payment_failed_money_deducted",
                "competency": "Root Cause Analysis",
                "questions": [
                    "Кейс: деньги списались, но статус ошибки. Что проверите первым?",
                ],
            }
        ],
    )

    class _FakeStrategist:
        async def decide_next_interview_action(self, ctx, model_override=None):
            return QuestionDecision(
                action="start_scenario",
                question_text="Кейс: деньги списались, но статус ошибки. Что проверите первым?",
                target_competency="Root Cause Analysis",
                phase="technical_case",
                scenario_id="qa_payment_failed_money_deducted",
                scenario_step=0,
                difficulty_tier=3,
                reason="start scenario",
                expected_signal="concrete_steps",
                ai_provider="gemini",
                requested_model="gemini-2.5-flash",
                actual_model_used="gemini-2.5-flash",
                provider_attempts=[],
                provider_errors=[],
                provider_fallback_used=False,
            )
    monkeypatch.setattr("app.ai.interview_strategist.strategist", _FakeStrategist())

    decision = await decide_next_interview_action(ctx)

    assert isinstance(decision, QuestionDecision)
    assert decision.question_text.strip()
    assert decision.action in {
        "ask_resume_followup",
        "pressure_followup",
        "clarify",
        "answer_meta_then_redirect",
        "switch_topic",
        "start_scenario",
        "continue_scenario",
        "close_interview",
    }


def test_validation_rejects_repeated_question():
    ctx = InterviewStrategistContext(
        role="qa_engineer",
        language="ru",
        asked_questions=["Кейс: деньги списались, но статус ошибки. Что проверите первым?"],
    )
    payload = {
        "action": "switch_topic",
        "question_text": "Кейс: деньги списались, но статус ошибки. Что проверите первым?",
        "target_competency": "Root Cause Analysis",
        "phase": "technical_case",
        "scenario_id": None,
        "scenario_step": 0,
        "difficulty_tier": 3,
        "reason": "test",
        "expected_signal": "concrete_work_example",
    }

    assert _validate_question_decision_payload(payload, ctx) is None


def test_fallback_skips_repeated_scenario_question_and_selects_next():
    ctx = InterviewStrategistContext(
        role="qa_engineer",
        language="ru",
        asked_questions=["Q1: Как воспроизведете дефект?"],
        available_scenarios=[
            {
                "case_id": "qa_case",
                "competency": "Root Cause Analysis",
                "questions": [
                    "Q1: Как воспроизведете дефект?",
                    "Q2: Какие данные соберете в первую очередь?",
                ],
            }
        ],
        interview_state_v2={"fallback_counter": 2},
    )

    decision = _fallback_decision(ctx, reason="test_fallback")

    assert decision.question_text == "Q2: Какие данные соберете в первую очередь?"
    assert decision.scenario_id == "qa_case"
    assert decision.scenario_step == 1


def test_conversational_mode_confusion_forces_simplify_with_concrete_example():
    ctx = InterviewStrategistContext(
        role="qa_engineer",
        language="ru",
        last_answer="Не понял, какой кейс?",
        available_scenarios=[
            {
                "case_id": "qa_case",
                "competency": "Root Cause Analysis",
                "questions": [
                    "Кейс: деньги списались, но статус ошибки. Что проверите первым?",
                ],
            }
        ],
        conversational_interviewer_mode=True,
    )

    decision = _conversation_guardrail_decision(ctx)

    assert decision is not None
    assert decision.action == "clarify"
    assert "Окей, объясню проще" in decision.question_text
    assert "деньги списались" in decision.question_text.lower()


def test_conversational_mode_aggression_soft_resets_dialogue():
    ctx = InterviewStrategistContext(
        role="qa_engineer",
        language="ru",
        last_answer="Ты зациклился, что за бред",
        available_scenarios=[
            {
                "case_id": "qa_case",
                "competency": "Root Cause Analysis",
                "questions": [
                    "Кейс: деньги списались, но статус ошибки. Что проверите первым?",
                ],
            }
        ],
        conversational_interviewer_mode=True,
    )

    decision = _conversation_guardrail_decision(ctx)

    assert decision is not None
    assert decision.action == "clarify"
    assert "Давай проще объясню, ок" in decision.question_text


def test_conversational_mode_counter_question_answers_briefly_and_returns_question():
    ctx = InterviewStrategistContext(
        role="qa_engineer",
        language="ru",
        last_answer="А какая задача, что именно ты хочешь?",
        available_scenarios=[
            {
                "case_id": "qa_case",
                "competency": "Root Cause Analysis",
                "questions": [
                    "Кейс: деньги списались, но статус ошибки. Что проверите первым?",
                ],
            }
        ],
        conversational_interviewer_mode=True,
    )

    decision = _conversation_guardrail_decision(ctx)

    assert decision is not None
    assert decision.action == "answer_meta_then_redirect"
    assert decision.question_text.startswith("Коротко:")
    assert "деньги списались" in decision.question_text.lower()


def test_conversational_mode_meta_question_gets_brief_reply_then_question():
    ctx = InterviewStrategistContext(
        role="qa_engineer",
        language="ru",
        last_answer="а ты сам ответить можешь?",
        available_scenarios=[
            {
                "case_id": "qa_case",
                "competency": "Root Cause Analysis",
                "questions": [
                    "Кейс: деньги списались, но статус ошибки. Что проверите первым?",
                ],
            }
        ],
        conversational_interviewer_mode=True,
    )

    decision = _conversation_guardrail_decision(ctx)

    assert decision is not None
    assert decision.action == "answer_meta_then_redirect"
    assert "важно понять ваш ход мысли" in decision.question_text.lower()
    assert "деньги списались" in decision.question_text.lower()


def test_conversational_mode_resume_personalization_request_changes_framing():
    ctx = InterviewStrategistContext(
        role="qa_engineer",
        language="ru",
        last_answer="давай по моему опыту, по моей работе еще вопросы будут?",
        available_scenarios=[
            {
                "case_id": "qa_case",
                "competency": "Root Cause Analysis",
                "questions": [
                    "Кейс: деньги списались, но статус ошибки. Что проверите первым?",
                ],
            }
        ],
        conversational_interviewer_mode=True,
    )

    decision = _conversation_guardrail_decision(ctx)

    assert decision is not None
    assert decision.action == "ask_resume_followup"
    assert "привяжем к вашему опыту" in decision.question_text.lower()
    assert "деньги списались" in decision.question_text.lower()


def _ctx_for_repair() -> InterviewStrategistContext:
    return InterviewStrategistContext(
        role="qa_engineer",
        language="ru",
        asked_questions=["Кейс: деньги списались, но статус ошибки. Что проверите первым?"],
        available_scenarios=[
            {
                "case_id": "qa_case",
                "competency": "Root Cause Analysis",
                "questions": [
                    "Кейс: деньги списались, но статус ошибки. Что проверите первым?",
                    "Какие данные соберете в первую очередь?",
                ],
            }
        ],
    )


def test_parse_or_repair_accepts_raw_json():
    ctx = _ctx_for_repair()
    raw = """{"action":"switch_topic","question_text":"Какие 2 источника данных проверите первыми?","target_competency":"Bug Investigation","phase":"technical_case","scenario_id":null,"scenario_step":0,"difficulty_tier":3,"reason":"ok","expected_signal":"data_sources"}"""
    decision, diagnostics = parse_or_repair_strategist_response(raw, {"policy_action": "switch_topic"}, ctx=ctx)
    assert decision is not None
    assert diagnostics["strategist_json_valid"] is True
    assert decision.action == "switch_topic"


def test_parse_or_repair_handles_markdown_wrapped_json():
    ctx = _ctx_for_repair()
    raw = """```json\n{"action":"clarify","question_text":"Уточню: какой именно шаг проверите первым?","target_competency":"Bug Investigation","phase":"resume_deep_dive","scenario_id":null,"scenario_step":0,"difficulty_tier":2,"reason":"clarify","expected_signal":"clarification"}\n```"""
    decision, diagnostics = parse_or_repair_strategist_response(raw, {"policy_action": "clarify"}, ctx=ctx)
    assert decision is not None
    assert diagnostics["strategist_json_valid"] is True


def test_parse_or_repair_handles_extra_text():
    ctx = _ctx_for_repair()
    raw = """Here is the result:\n{"action":"pressure_followup","question_text":"Назовите 2 шага и какой id возьмете для поиска?","target_competency":"Bug Investigation","phase":"technical_case","scenario_id":null,"scenario_step":0,"difficulty_tier":3,"reason":"followup","expected_signal":"step_sequence"}\nThanks"""
    decision, diagnostics = parse_or_repair_strategist_response(raw, {"policy_action": "pressure_followup"}, ctx=ctx)
    assert decision is not None
    assert diagnostics["strategist_json_valid"] is True


def test_parse_or_repair_fills_missing_fields():
    ctx = _ctx_for_repair()
    raw = """{"action":"switch_topic","question_text":"Какие логи и какой id проверите?"}"""
    decision, diagnostics = parse_or_repair_strategist_response(raw, {"policy_action": "switch_topic"}, ctx=ctx)
    assert decision is not None
    assert diagnostics["strategist_repair_applied"] is True
    assert decision.target_competency
    assert decision.expected_signal


def test_parse_or_repair_maps_unknown_action_to_policy_action():
    ctx = _ctx_for_repair()
    raw = """{"action":"ask_new_topic","question_text":"Какие логи и какой id проверите?","target_competency":"Bug Investigation","phase":"technical_case","scenario_id":null,"scenario_step":0,"difficulty_tier":3,"reason":"legacy","expected_signal":"detail"}"""
    decision, _ = parse_or_repair_strategist_response(raw, {"policy_action": "clarify"}, ctx=ctx)
    assert decision is not None
    assert decision.action in {"switch_topic", "clarify"}


def test_parse_or_repair_returns_none_for_completely_invalid_text():
    ctx = _ctx_for_repair()
    decision, diagnostics = parse_or_repair_strategist_response("not a json at all", {"policy_action": "clarify"}, ctx=ctx)
    assert decision is None
    assert diagnostics["strategist_json_valid"] is False


@pytest.mark.asyncio
async def test_llm_strategist_retries_invalid_json_then_returns_valid_decision(monkeypatch: pytest.MonkeyPatch):
    strategist = LLMInterviewStrategist(provider=object())  # type: ignore[arg-type]
    ctx = InterviewStrategistContext(
        role="qa_engineer",
        language="ru",
        asked_questions=[],
        interview_state_v2={"phase": "resume_deep_dive"},
        available_scenarios=[
            {
                "case_id": "qa_case",
                "competency": "Bug Investigation",
                "questions": ["Кейс: деньги списались, но статус ошибки. Что проверите первым?"],
            }
        ],
    )
    responses = iter(
        [
            "broken text",
            """{"candidate_understanding":"low","candidate_cooperation_level":"high","conversation_problem":"clarification","missing_signal":"Bug Investigation","resume_evidence_status":"partial","best_next_move":"clarify","question_goal":"получить первый конкретный шаг","question_style":"simplified","why_this_move":"кандидату нужна переформулировка"}""",
            """{"question_text":"Окей, объясню проще: в кейсе перевода что проверите первым?"}""",
        ]
    )

    async def _fake_invoke(**_kwargs):
        return next(responses), {}

    monkeypatch.setattr(strategist, "_invoke_strategist", _fake_invoke)

    decision = await strategist.decide_next_interview_action(ctx, model_override="llama-3.3-70b-versatile")
    assert decision.action == "clarify"
    assert decision.strategist_retry_used is True
    assert decision.strategist_json_valid is True
    assert decision.strategist_error_reason in {"", None}


@pytest.mark.asyncio
async def test_llm_strategist_smoke_json_stability_and_low_fallback(monkeypatch: pytest.MonkeyPatch):
    strategist = LLMInterviewStrategist(provider=object())  # type: ignore[arg-type]
    state_v2 = {"phase": "resume_deep_dive", "fallback_counter": 0}
    asked_questions: list[str] = []
    ctx = InterviewStrategistContext(
        role="qa_engineer",
        language="ru",
        asked_questions=asked_questions,
        interview_state_v2=state_v2,
        available_scenarios=[
            {
                "case_id": "qa_payment_status_error",
                "competency": "Bug Investigation",
                "questions": [
                    "Кейс: перевод не прошёл, но деньги списались. Что проверите первым?",
                    "Какие данные соберёте в первую очередь?",
                ],
            }
        ],
    )

    scripted_responses = iter(
        [
            # turn1: reasoning + phrase
            """{"candidate_understanding":"medium","candidate_cooperation_level":"high","conversation_problem":"none","missing_signal":"Bug Investigation","resume_evidence_status":"partial","best_next_move":"ask_resume_followup","question_goal":"получить конкретный кейс","question_style":"conversational","why_this_move":"start"}""",
            """{"question_text":"Давайте на примере из вашего опыта: какая была задача, что сделали лично и какой получили результат?"}""",
            # turn2: reasoning invalid -> retry valid + phrase
            "not_json",
            """{"candidate_understanding":"medium","candidate_cooperation_level":"high","conversation_problem":"need_case","missing_signal":"Bug Investigation","resume_evidence_status":"partial","best_next_move":"start_scenario","question_goal":"первый шаг в инциденте","question_style":"conversational","why_this_move":"switch to concrete scenario"}""",
            """{"question_text":"Представьте: деньги списались, но статус ошибки. Что проверите первым?"}""",
            # turn3: reasoning + phrase
            """{"candidate_understanding":"medium","candidate_cooperation_level":"high","conversation_problem":"needs_detail","missing_signal":"Bug Investigation","resume_evidence_status":"partial","best_next_move":"continue_scenario","question_goal":"источники данных","question_style":"probing","why_this_move":"go deeper"}""",
            """{"question_text":"Какие 2 источника данных проверите первыми и по какому id?"}""",
            # turn4: reasoning invalid -> retry invalid => fallback
            "bad",
            "still bad",
            # turn5: reasoning + phrase
            """{"candidate_understanding":"medium","candidate_cooperation_level":"high","conversation_problem":"weak_detail","missing_signal":"Bug Investigation","resume_evidence_status":"partial","best_next_move":"pressure_followup","question_goal":"личное действие","question_style":"probing","why_this_move":"force detail"}""",
            """{"question_text":"Окей, конкретнее: что именно сделали вы первым и какой сигнал искали в логах?"}""",
            # turn6: reasoning + phrase
            """{"candidate_understanding":"strong","candidate_cooperation_level":"high","conversation_problem":"none","missing_signal":"Regression Risk","resume_evidence_status":"enough","best_next_move":"continue_scenario","question_goal":"валидация фикса","question_style":"edge_case","why_this_move":"increase depth"}""",
            """{"question_text":"Как подтвердите, что фикс сработал и не ломает соседние платежные сценарии?"}""",
            # turn7: reasoning invalid -> retry valid + phrase
            "garbage",
            """{"candidate_understanding":"strong","candidate_cooperation_level":"high","conversation_problem":"none","missing_signal":"Release Quality","resume_evidence_status":"enough","best_next_move":"switch_topic","question_goal":"go/no-go критерии","question_style":"edge_case","why_this_move":"new competency"}""",
            """{"question_text":"Окей, а если релиз завтра: какие критерии go/no-go выберете для платежной фичи?"}""",
            # turn8: reasoning + phrase
            """{"candidate_understanding":"medium","candidate_cooperation_level":"high","conversation_problem":"none","missing_signal":"Release Quality","resume_evidence_status":"enough","best_next_move":"ask_resume_followup","question_goal":"личный вклад в риск","question_style":"conversational","why_this_move":"personalize"}""",
            """{"question_text":"В вашем опыте сопровождения: какой риск вы сняли лично перед релизом?"}""",
            # turn9: reasoning invalid -> retry invalid => fallback
            "not valid",
            "still not valid",
            # turn10: reasoning + phrase
            """{"candidate_understanding":"medium","candidate_cooperation_level":"high","conversation_problem":"short_answer","missing_signal":"Release Quality","resume_evidence_status":"enough","best_next_move":"pressure_followup","question_goal":"метрики после релиза","question_style":"probing","why_this_move":"close missing evidence"}""",
            """{"question_text":"Что именно сделали вы лично и каким метрикам доверяли после релиза?"}""",
        ]
    )

    async def _fake_invoke(**_kwargs):
        return next(scripted_responses), {}

    monkeypatch.setattr(strategist, "_invoke_strategist", _fake_invoke)

    decisions: list[QuestionDecision] = []
    for _ in range(10):
        decision = await strategist.decide_next_interview_action(ctx, model_override="llama-3.3-70b-versatile")
        decisions.append(decision)
        asked_questions.append(decision.question_text)
        if decision.strategist_json_valid:
            state_v2["fallback_counter"] = 0
        else:
            state_v2["fallback_counter"] = int(state_v2.get("fallback_counter", 0)) + 1

    strategist_valid_count = sum(1 for d in decisions if d.strategist_json_valid)
    fallback_count = sum(1 for d in decisions if not d.strategist_json_valid)
    repeated_question_count = len(asked_questions) - len(set(asked_questions))

    assert strategist_valid_count >= 8
    assert fallback_count <= 2
    assert repeated_question_count == 0
