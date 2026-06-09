"""Validate role-specific interview intros and lightweight question generation.

Run from the backend container:
    python app/scripts/validate_interview_roles.py --questions 3

The script intentionally avoids full UI E2E. It builds role plans, generates an
intro plus the first 3-5 LLM questions per role, and writes a JSON matrix report.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import get_args

from app.ai.competencies import ROLE_COMPETENCIES, build_interview_plan
from app.ai.interviewer import InterviewContext
from app.ai.resume_profile import preprocess_resume
from app.core.config import settings
from app.schemas.interview import TargetRole
from app.services.interview_service import (
    _build_interview_intro_message,
    _get_next_question_with_dev_fallback,
    _role_label,
    _sanitize_chat_question_with_metadata,
    _topic_group_key,
    _topic_signature_key,
)


ROLE_SAMPLE_RESUMES: dict[str, str] = {
    "backend_engineer": "Backend engineer with Python/FastAPI, PostgreSQL, async APIs, queues, transactions, performance debugging, and service reliability experience.",
    "frontend_engineer": "Frontend engineer with React, Next.js, TypeScript, forms, API integration, accessibility, web performance, and design system experience.",
    "qa_engineer": "QA engineer with test plans, test cases, API/UI testing, regression, defect reporting, automation, CI integration, and edge case analysis.",
    "devops_engineer": "DevOps engineer with Docker, Kubernetes, CI/CD, monitoring, incident response, deployment rollback, cloud infrastructure, and security experience.",
    "data_scientist": "Data scientist with SQL, dashboards, model validation, A/B testing, data quality checks, metrics, experimentation, and business insights.",
    "product_manager": "Product manager with discovery, user research, prioritization, roadmap planning, product metrics, stakeholder alignment, and trade-off decisions.",
    "mobile_engineer": "Mobile engineer with Android/iOS releases, crash analysis, API integrations, offline behavior, app performance, and mobile UX edge cases.",
    "designer": "UX/UI designer with user research, user flows, prototypes, design systems, accessibility, usability testing, and handoff to engineering.",
}

ROLE_SAMPLE_ANSWERS: dict[str, str] = {
    "backend_engineer": "Я проектировал API, разбирал медленные запросы PostgreSQL, проверял транзакции и откатывал риск через feature flags.",
    "frontend_engineer": "Я вел React/Next.js экран, оптимизировал загрузку, исправлял состояние формы и проверял accessibility через keyboard flow.",
    "qa_engineer": "Я составлял test cases, воспроизводил дефекты, проверял API и UI, а затем добавлял regression checks в CI.",
    "devops_engineer": "Я настраивал CI/CD, Docker/Kubernetes deployment, мониторинг, алерты и rollback plan для production-релизов.",
    "data_scientist": "Я проверял SQL-выборки, data quality, строил dashboard, валидировал метрики модели и объяснял бизнесовый insight.",
    "product_manager": "Я собирал user needs, приоритизировал roadmap, связывал решения с метриками и согласовывал trade-offs со стейкхолдерами.",
    "mobile_engineer": "Я анализировал crash logs, воспроизводил проблему на версии Android/iOS, проверял API-интеграции и готовил staged rollout.",
    "designer": "Я проводил user research, собирал pain points, проектировал user flow, прототипировал решение и проверял usability.",
}

ROLE_REQUIRED_MARKERS: dict[str, tuple[str, ...]] = {
    "backend_engineer": ("api", "backend", "бэк", "database", "postgres", "transaction", "архитект", "performance", "security", "debug"),
    "frontend_engineer": ("frontend", "фронт", "react", "next", "ui", "state", "состоя", "performance", "accessibility", "доступ", "form", "api"),
    "qa_engineer": ("qa", "test", "тест", "bug", "баг", "defect", "дефект", "api", "ui", "regression", "регресс", "automation", "автомат", "ci", "edge", "качест"),
    "devops_engineer": ("devops", "ci", "cd", "docker", "kubernetes", "monitoring", "монитор", "incident", "инцидент", "deploy", "деплой", "rollback", "откат", "infra", "релиз"),
    "data_scientist": ("data", "данн", "sql", "metric", "метрик", "dashboard", "model", "модел", "hypothesis", "гипот", "a/b", "quality", "качест", "insight", "pipeline"),
    "product_manager": ("product", "продукт", "продакт", "discovery", "user", "пользоват", "priorit", "приорит", "roadmap", "метрик", "metric", "stakeholder", "стейкхол", "trade", "business", "бизнес"),
    "mobile_engineer": ("mobile", "мобиль", "android", "ios", "crash", "крэш", "release", "релиз", "api", "offline", "performance", "устройств", "верс"),
    "designer": ("design", "дизайн", "ux", "ui", "research", "исслед", "prototype", "прототип", "flow", "поток", "usability", "accessibility", "handoff", "figma"),
}

ROLE_FORBIDDEN_MARKERS: dict[str, tuple[str, ...]] = {
    "backend_engineer": ("roadmap", "discovery", "user research"),
    "frontend_engineer": ("roadmap", "discovery", "kubernetes rollout"),
    "qa_engineer": ("roadmap", "product discovery", "grafana dashboard as pm"),
    "devops_engineer": ("roadmap", "user research", "figma"),
    "data_scientist": ("hotfix", "grafana incident", "roadmap"),
    "mobile_engineer": ("roadmap", "product discovery"),
    "designer": ("hotfix", "kubernetes", "database transaction"),
}


def _is_role_thematic(role: str, question: str) -> bool:
    lowered = question.lower()
    markers = ROLE_REQUIRED_MARKERS.get(role, ())
    role_label = role.replace("_", " ").lower()
    return role_label in lowered or any(marker in lowered for marker in markers)


def _forbidden_hits(role: str, question: str) -> list[str]:
    lowered = question.lower()
    return [marker for marker in ROLE_FORBIDDEN_MARKERS.get(role, ()) if marker in lowered]


async def validate_role(role: str, *, language: str, question_count: int) -> dict:
    warnings: list[str] = []
    resume_text = ROLE_SAMPLE_RESUMES.get(role, ROLE_SAMPLE_RESUMES["backend_engineer"])
    resume_profile = preprocess_resume(resume_text, role)
    topic_plan = build_interview_plan(role, max(question_count + 2, 6), resume_profile, structured_flow=True)
    intro = _build_interview_intro_message(role=role, language=language, max_questions=max(question_count + 2, 6))
    role_name = _role_label(role, language)
    if role not in ROLE_COMPETENCIES:
        warnings.append("role_missing_competency_matrix")
    if role_name.lower() not in intro.lower() and role.replace("_", " ").lower() not in intro.lower():
        warnings.append("intro_does_not_mention_role")

    history: list[dict[str, str]] = []
    asked_questions: list[str] = []
    topic_groups: list[str] = []
    competencies: list[str] = []
    sanitizer_triggered = False
    loop_guard_triggered = False
    provider = "openai"
    model = settings.OPENAI_MODEL
    source = "openai"

    for idx in range(question_count):
        topic = topic_plan[min(idx, len(topic_plan) - 1)] if topic_plan else {}
        ctx = InterviewContext(
            target_role=role,
            seniority_level=None,
            difficulty_tier=3,
            question_number=idx + 1,
            max_questions=max(question_count + 2, 6),
            message_history=history[-8:],
            resume_text=resume_text,
            competency_targets=list(topic.get("competencies") or []),
            language=language,
            resume_anchor=topic.get("resume_anchor"),
            verification_target=topic.get("verification_target"),
            topic_phase=topic.get("phase"),
            question_block=topic.get("block"),
            question_tier=topic.get("tier"),
            lead_question=topic.get("lead_question"),
            allowed_probes=list(topic.get("allowed_probes") or []),
            scored_metrics=list(topic.get("scored_metrics") or []),
            current_topic=_topic_signature_key(topic),
            asked_topics=[_topic_signature_key(item) for item in topic_plan[:idx] if item],
            transcript_summary=[],
        )
        try:
            raw_question = await _get_next_question_with_dev_fallback(ctx)
        except Exception as exc:
            warnings.append(f"llm_generation_failed:{exc.__class__.__name__}")
            provider = "openai"
            source = "error"
            break
        question, sanitizer_meta = _sanitize_chat_question_with_metadata(raw_question, language=language)
        question = question or raw_question
        sanitizer_triggered = sanitizer_triggered or bool(sanitizer_meta.get("question_sanitized"))
        group = _topic_group_key(topic, role=role, question_text=question)
        if len(topic_groups) >= 2 and topic_groups[-1] == topic_groups[-2] == group:
            loop_guard_triggered = True
            warnings.append(f"topic_group_loop:{group}")
        if not _is_role_thematic(role, question):
            warnings.append(f"low_role_marker_signal:q{idx + 1}")
        forbidden = _forbidden_hits(role, question)
        if forbidden:
            warnings.append(f"forbidden_markers:q{idx + 1}:{','.join(forbidden)}")
        asked_questions.append(question)
        topic_groups.append(group)
        competencies.extend(str(item) for item in topic.get("competencies") or [])
        history.append({"role": "assistant", "content": question})
        history.append({"role": "candidate", "content": ROLE_SAMPLE_ANSWERS.get(role, "Готов разобрать конкретный пример по роли.")})

    return {
        "role_id": role,
        "role_name": role_name,
        "intro_present": bool(intro.strip()),
        "intro_mentions_role": role_name.lower() in intro.lower() or role.replace("_", " ").lower() in intro.lower(),
        "intro_preview": intro[:500],
        "question_count": len(asked_questions),
        "questions": asked_questions,
        "topic_groups": topic_groups,
        "competencies": sorted(set(competencies)),
        "provider": provider,
        "model": model,
        "source": source,
        "sanitizer_triggered": sanitizer_triggered,
        "loop_guard_triggered": loop_guard_triggered,
        "warnings": warnings,
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--language", choices=["ru", "en"], default="ru")
    parser.add_argument("--questions", type=int, default=3)
    parser.add_argument("--output", default="/tmp/interview_role_matrix_report.json")
    args = parser.parse_args()

    roles = list(get_args(TargetRole))
    results = []
    for role in roles:
        results.append(await validate_role(role, language=args.language, question_count=max(3, min(args.questions, 5))))

    report = {
        "provider": "openai",
        "model": settings.OPENAI_MODEL,
        "language": args.language,
        "roles": roles,
        "results": results,
        "warnings": {item["role_id"]: item["warnings"] for item in results if item["warnings"]},
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), "roles": len(results), "warnings": report["warnings"]}, ensure_ascii=False, indent=2))
    return 1 if report["warnings"] else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
