from app.ai.assessor import _aggregate_skills


def test_skill_tags_require_candidate_evidence_and_filter_generic_terms():
    per_question = [
        {
            "question_number": 1,
            "answer_quality": 8.2,
            "specificity": "high",
            "depth": "strong",
            "ai_likelihood": 0.1,
            "evidence": "Оптимизировал запросы PostgreSQL через EXPLAIN ANALYZE и индексы под production-нагрузкой.",
            "skills_mentioned": [
                {"skill": "postgresql", "proficiency": "advanced"},
                {"skill": "rest", "proficiency": "intermediate"},
                {"skill": "soap", "proficiency": "intermediate"},
            ],
        }
    ]
    message_history = [
        {"role": "assistant", "content": "Расскажите про API и базы данных."},
        {
            "role": "candidate",
            "content": (
                "В production я использовал PostgreSQL: смотрел EXPLAIN ANALYZE, "
                "тюнил индексы и убирал узкие места в запросах."
            ),
        },
    ]

    tags = _aggregate_skills(per_question, message_history=message_history)
    names = {item["skill"] for item in tags}

    assert "postgresql" in names
    assert "rest" not in names
    assert "soap" not in names


def test_skill_with_no_candidate_mention_is_dropped():
    per_question = [
        {
            "question_number": 1,
            "answer_quality": 8.0,
            "specificity": "high",
            "depth": "strong",
            "ai_likelihood": 0.05,
            "evidence": "Answer looked strong but candidate did not provide concrete Docker usage details.",
            "skills_mentioned": [{"skill": "docker", "proficiency": "advanced"}],
        }
    ]
    message_history = [
        {"role": "assistant", "content": "Расскажите про инфраструктуру."},
        {"role": "candidate", "content": "Я в основном оптимизировал SQL и разбирал query plans."},
    ]

    tags = _aggregate_skills(per_question, message_history=message_history)
    assert tags == []
