from app.ai.resume_profile import preprocess_resume


def test_preprocess_resume_skips_personal_info_lines_in_project_highlights():
    raw_resume = "\n".join(
        [
            "Мужчина, 25 лет, родился 25 мая 1998.",
            "Дата рождения: 25.05.1998",
            "UX/UI дизайнер с опытом запуска продукта для бронирования рабочих мест.",
            "Спроектировал новый сценарий онбординга, что снизило отказы на первом шаге.",
        ]
    )

    profile = preprocess_resume(raw_resume, target_role="designer")
    highlights = profile.get("project_highlights", [])

    assert highlights
    lowered = " ".join(item.lower() for item in highlights)
    assert "мужчина" not in lowered
    assert "родил" not in lowered
    assert "дата рождения" not in lowered


def test_preprocess_resume_skips_location_label_lines_in_project_highlights():
    raw_resume = "\n".join(
        [
            "Проживает: Алматы, м. Алатау",
            "Адрес: Алматы, ул. Абая 100",
            "Backend-инженер, сопровождал мобильное банковское приложение и API.",
            "Оптимизировал SQL-запросы и уменьшил среднее время ответа на критичных эндпоинтах.",
        ]
    )

    profile = preprocess_resume(raw_resume, target_role="backend_engineer")
    highlights = profile.get("project_highlights", [])

    assert highlights
    lowered = " ".join(item.lower() for item in highlights)
    assert "проживает:" not in lowered
    assert "адрес:" not in lowered


def test_preprocess_resume_skips_relocation_availability_lines_in_project_highlights():
    raw_resume = "\n".join(
        [
            "Готов к переезду, готов к командировкам",
            "Data Scientist в финтехе: строил пайплайны признаков и мониторинг качества моделей.",
            "Снизил время расчёта витрин за счёт оптимизации Spark job и оркестрации.",
        ]
    )

    profile = preprocess_resume(raw_resume, target_role="data_scientist")
    highlights = profile.get("project_highlights", [])

    assert highlights
    lowered = " ".join(item.lower() for item in highlights)
    assert "готов к переезду" not in lowered
    assert "командировк" not in lowered


def test_preprocess_resume_skips_profile_headers_and_name_lines_in_project_highlights():
    raw_resume = "\n".join(
        [
            "Тельман Алишер Нурланулы",
            "Желаемая должность и зарплата",
            "QA-инженер в банковском мобильном приложении: анализировал дефекты и сопровождал релизы.",
            "Автоматизировал smoke-регресс и сократил ручные проверки перед релизом.",
        ]
    )

    profile = preprocess_resume(raw_resume, target_role="qa_engineer")
    highlights = profile.get("project_highlights", [])

    assert highlights
    lowered = " ".join(item.lower() for item in highlights)
    assert "тельман алишер нурланулы" not in lowered
    assert "желаемая должность и зарплата" not in lowered


def test_preprocess_resume_skips_low_signal_role_title_lines_in_project_highlights():
    raw_resume = "\n".join(
        [
            "— Руководитель группы разработки",
            "Middle QA Engineer",
            "В банковском мобильном приложении автоматизировал регресс и сократил время проверки на 40%.",
            "Настроил CI pipeline для автотестов и стабилизировал nightly-прогон.",
        ]
    )

    profile = preprocess_resume(raw_resume, target_role="qa_engineer")
    highlights = profile.get("project_highlights", [])

    assert highlights
    lowered = " ".join(item.lower() for item in highlights)
    assert "руководитель группы разработки" not in lowered
    assert "middle qa engineer" not in lowered


def test_preprocess_resume_builds_clean_interview_context():
    raw_resume = "\n".join(
        [
            "Тельман Алишер Нурланулы",
            "Желаемая должность и зарплата",
            "Готов к переезду, готов к командировкам",
            "Опыт работы",
            "Руководил сопровождением мобильного банковского приложения, настроил мониторинг и снизил время реакции на инциденты.",
            "Построил дэшборды Grafana для бизнес- и тех-метрик, автоматизировал алерты.",
            "Образование",
            "Магистратура IT Project Management, Satbayev University",
            "Навыки",
            "PostgreSQL, Docker, Grafana, Kubernetes",
        ]
    )

    profile = preprocess_resume(raw_resume, target_role="qa_engineer")
    context = str(profile.get("interview_resume_context") or "")

    assert context
    lowered = context.lower()
    assert "желаемая должность" not in lowered
    assert "готов к переезду" not in lowered
    assert "тельман алишер нурланулы" not in lowered
    assert "monitoring" in lowered or "мониторинг" in lowered or "дэшборды" in lowered
    assert "postgresql" in lowered
    assert "магистратура" in lowered


def test_preprocess_resume_reserves_experience_anchor_as_first_highlight():
    raw_resume = "\n".join(
        [
            "Опыт работы",
            "Управлял релизами мобильного банка, сократил время стабилизации после релиза на 35%.",
            "Проектировал регрессионные наборы и сократил критические дефекты перед продом на 40%.",
            "Навыки",
            "Python, SQL, Jira, Confluence",
        ]
    )

    profile = preprocess_resume(raw_resume, target_role="qa_engineer")
    highlights = profile.get("project_highlights", [])

    assert highlights
    first = str(highlights[0]).lower()
    assert "сократил" in first or "управлял" in first
    assert "jira" not in first


def test_preprocess_resume_for_qa_does_not_use_db_stack_as_primary_verification_target():
    raw_resume = "\n".join(
        [
            "QA engineer in fintech mobile app.",
            "Проводил API-тестирование и регрессию релизов.",
            "Использовал PostgreSQL, Redis, Kafka и GraphQL для диагностики инцидентов.",
        ]
    )

    profile = preprocess_resume(raw_resume, target_role="qa_engineer")
    targets = [str(item).lower() for item in profile.get("verification_targets", [])]

    assert "postgresql" not in targets
    assert "redis" not in targets
    assert "kafka" not in targets
    assert "graphql" in targets or targets == []


def test_preprocess_resume_for_frontend_does_not_shift_to_backend_db_targets():
    raw_resume = "\n".join(
        [
            "Frontend engineer (React).",
            "Оптимизировал web performance и SSR.",
            "Работал с PostgreSQL и Kafka при кросс-командной отладке.",
        ]
    )

    profile = preprocess_resume(raw_resume, target_role="frontend_engineer")
    targets = [str(item).lower() for item in profile.get("verification_targets", [])]

    assert "postgresql" not in targets
    assert "kafka" not in targets
    assert "react" in targets or targets == []


def test_preprocess_resume_for_pm_does_not_use_sql_stack_as_primary_focus():
    raw_resume = "\n".join(
        [
            "Product Manager, ownership of roadmap and discovery.",
            "Проводил интервью пользователей, приоритизировал backlog.",
            "Команда использовала PostgreSQL и Redis для аналитических витрин.",
        ]
    )

    profile = preprocess_resume(raw_resume, target_role="product_manager")
    targets = [str(item).lower() for item in profile.get("verification_targets", [])]

    assert "postgresql" not in targets
    assert "redis" not in targets
    assert "sql" not in targets
