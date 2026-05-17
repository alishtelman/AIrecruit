from __future__ import annotations

import re
from typing import Any

_PERSONAL_ACTION_RE = re.compile(
    r"\b(я|i)\b.{0,24}\b(сделал|делала|проверил|проверила|настроил|настроила|проанализировал|organized|implemented|checked|verified|triaged|investigated)\b",
    re.IGNORECASE,
)
_RESULT_RE = re.compile(
    r"\b(результат|снизил|снизили|улучшил|улучшили|метрик|подтвердил|подтвердили|fixed|reduced|improved|validated|resolved)\b",
    re.IGNORECASE,
)


def _role_concrete_example_question(role: str, language: str) -> str:
    role_key = str(role or "").strip().lower()
    is_en = str(language).lower().startswith("en")
    if role_key == "qa_engineer":
        return (
            "Давайте на примере: клиент говорит, что деньги списались, но перевод не прошёл. Что вы проверите первым?"
            if not is_en
            else "Let's use a concrete case: money was deducted but transfer failed. What would you check first?"
        )
    if role_key == "backend_engineer":
        return (
            "Давайте на примере: API начал отдавать 500 под нагрузкой. Какие 2 первых проверки сделаете?"
            if not is_en
            else "Let's use a concrete case: API starts returning 500 under load. What are your first 2 checks?"
        )
    if role_key == "frontend_engineer":
        return (
            "Давайте на примере: после релиза часть пользователей видит пустой экран. Что проверите первым?"
            if not is_en
            else "Let's use a concrete case: after release some users see a blank screen. What do you check first?"
        )
    if role_key == "devops_engineer":
        return (
            "Давайте на примере: pod ушёл в CrashLoopBackOff. Какие сигналы и логи проверите сначала?"
            if not is_en
            else "Let's use a concrete case: pod entered CrashLoopBackOff. Which signals and logs do you inspect first?"
        )
    if role_key == "product_manager":
        return (
            "Давайте на примере: после релиза просела ключевая метрика. Что проверите первым и почему?"
            if not is_en
            else "Let's use a concrete case: a key metric dropped after release. What do you check first and why?"
        )
    if role_key in {"designer", "ux_ui_designer"}:
        return (
            "Давайте на примере: пользователи не завершают onboarding. Какие 2 проверки сделаете в первую очередь?"
            if not is_en
            else "Let's use a concrete case: users do not complete onboarding. Which 2 checks would you do first?"
        )
    if role_key == "mobile_engineer":
        return (
            "Давайте на примере: crash только на части Android-устройств. С чего начнёте разбор?"
            if not is_en
            else "Let's use a concrete case: crash appears only on some Android devices. Where do you start?"
        )
    if role_key == "data_scientist":
        return (
            "Давайте на примере: модель просела на проде. Какие 2 гипотезы проверите первыми?"
            if not is_en
            else "Let's use a concrete case: model quality dropped in prod. Which 2 hypotheses do you test first?"
        )
    return (
        "Давайте на конкретном рабочем примере: что произошло и что вы проверили первым?"
        if not is_en
        else "Let's use one concrete work example: what happened and what did you check first?"
    )


def build_pressure_followup(
    role: str,
    current_question: str,
    candidate_answer: str,
    competency: str,
    scenario_context: str,
    language: str,
    answer_evaluation: dict[str, Any] | None = None,
    force_concrete_example: bool = False,
) -> str:
    role_key = str(role or "").strip().lower()
    answer = " ".join((candidate_answer or "").strip().lower().split())
    is_en = str(language).lower().startswith("en")
    evaluation = answer_evaluation or {}

    if force_concrete_example:
        return _role_concrete_example_question(role=role, language=language)

    has_example = bool(evaluation.get("has_concrete_example", evaluation.get("has_example", False)))
    has_personal_action = bool(evaluation.get("has_personal_action")) or bool(_PERSONAL_ACTION_RE.search(candidate_answer or ""))
    has_result = bool(evaluation.get("has_result")) or bool(_RESULT_RE.search(candidate_answer or ""))
    has_technical_detail = bool(evaluation.get("has_technical_detail"))

    if role_key == "qa_engineer":
        if "лог" in answer or "log" in answer:
            return (
                "Какие именно логи и по какому идентификатору будете искать событие: request id, transaction id или correlation id?"
                if not is_en
                else "Which exact logs will you check and by which identifier: request id, transaction id, or correlation id?"
            )
        if "api" in answer or "апи" in answer or "endpoint" in answer:
            return (
                "Какой endpoint проверите первым, какие 2 поля в response критичны и какой сигнал подтвердит вашу гипотезу?"
                if not is_en
                else "Which endpoint do you check first, which 2 response fields are critical, and what signal confirms your hypothesis?"
            )
        if "везде" in answer or "everywhere" in answer:
            return (
                "Назовите первые 2 места проверки и почему начинаете именно с них."
                if not is_en
                else "Name the first 2 places you would check and why you start with them."
            )
        if not has_example:
            return _role_concrete_example_question(role=role, language=language)
        if not has_personal_action:
            return (
                "Что именно сделали вы лично: назовите 2-3 шага по порядку?"
                if not is_en
                else "What exactly did you do personally: name 2-3 steps in order?"
            )
        if not has_result:
            return (
                "Как вы поняли, что проблема решена: какой результат или проверка это подтвердили?"
                if not is_en
                else "How did you confirm the issue was resolved: which result or check proved it?"
            )
        if not has_technical_detail:
            return (
                "Давайте конкретнее: какие шаги по порядку, какие данные проверяли и по какому идентификатору?"
                if not is_en
                else "Let's be specific: which steps in order, which data you checked, and by which identifier?"
            )
        return (
            "Давайте конкретнее: какой источник данных проверите первым, какой идентификатор возьмёте и какой критерий подтвердит/опровергнет гипотезу?"
            if not is_en
            else "Let's be concrete: which data source will you check first, which identifier will you use, and what criterion confirms/refutes your hypothesis?"
        )

    if not has_example:
        return _role_concrete_example_question(role=role, language=language)
    if not has_personal_action:
        return (
            "Что именно сделали вы лично: назовите 2-3 шага по порядку?"
            if not is_en
            else "What exactly did you do personally: name 2-3 steps in order?"
        )
    if not has_result:
        return (
            "Как вы поняли, что проблема решена: какой результат или проверка это подтвердили?"
            if not is_en
            else "How did you confirm the issue was resolved: which result or check proved it?"
        )
    if not has_technical_detail:
        return (
            "Давайте конкретнее: какие шаги по порядку, какие данные проверяли и по какому идентификатору?"
            if not is_en
            else "Let's be specific: which steps in order, which data you checked, and by which identifier?"
        )

    if role_key == "backend_engineer":
        return (
            "Уточните: какой компонент считаете bottleneck, какие метрики/логи/trace смотрите первыми и какой порог считаете критичным?"
            if not is_en
            else "Specify: which component is the bottleneck, which metrics/logs/traces you inspect first, and what threshold you treat as critical?"
        )

    if role_key == "frontend_engineer":
        return (
            "Уточните: какой user flow деградировал, на каком устройстве/браузере, и какие данные из network/console/performance вы проверите первыми?"
            if not is_en
            else "Specify: which user flow degraded, on which device/browser, and which network/console/performance signals you check first?"
        )

    if role_key == "devops_engineer":
        return (
            "Уточните: какой alert/signal сработал первым, в каком namespace/pod ищете первопричину и какой rollback/mitigation запускаете?"
            if not is_en
            else "Specify: which alert/signal fired first, in which namespace/pod you localize root cause, and which rollback/mitigation you trigger?"
        )

    if role_key == "product_manager":
        return (
            "Уточните: какую метрику и сегмент пользователей проверите первыми, и какой порог будет критерием решения?"
            if not is_en
            else "Specify: which metric and user segment you check first, and what threshold drives your decision?"
        )

    if role_key in {"designer", "ux_ui_designer"}:
        return (
            "Уточните: какой пользовательский сценарий проседает, какой usability-сигнал смотрите первым и как проверите гипотезу изменения?"
            if not is_en
            else "Specify: which user flow is failing, which usability signal you inspect first, and how you validate the design hypothesis?"
        )

    if role_key == "mobile_engineer":
        return (
            "Уточните: на каких устройствах/версиях воспроизводится проблема, какие crash/log/trace сигналы проверяете и как подтверждаете фикс?"
            if not is_en
            else "Specify: on which devices/versions the issue reproduces, which crash/log/trace signals you inspect, and how you validate the fix?"
        )

    if role_key == "data_scientist":
        return (
            "Уточните: какую метрику качества смотрите первой, какой источник данных проверяете и как отделяете data drift от bug в пайплайне?"
            if not is_en
            else "Specify: which quality metric you inspect first, which data source you verify, and how you separate data drift from pipeline bugs?"
        )

    return (
        "Давайте конкретнее: один источник данных, одно действие и критерий результата."
        if not is_en
        else "Let's get concrete: one data source, one action, and one success criterion."
    )


def build_interviewer_redirect(
    intent_result: dict[str, Any],
    state: dict[str, Any],
    role: str,
    language: str,
    resume_context: str | None,
    current_scenario: str | None,
    fallback_question: str,
) -> str:
    intent = str(intent_result.get("intent") or "")
    is_en = str(language).lower().startswith("en")
    normalized_fallback = " ".join((fallback_question or "").strip().split())
    if normalized_fallback and not normalized_fallback.endswith("?"):
        normalized_fallback = f"{normalized_fallback}?"

    lower_fallback = normalized_fallback.lower()
    generic_fallback = any(
        marker in lower_fallback
        for marker in (
            "разберите кейс",
            "расскажите подробнее",
            "уточните кейс",
            "какой кейс",
            "describe the case",
            "tell me more",
        )
    )

    if intent == "challenge_interviewer":
        prefix = (
            "Понимаю вопрос. Моя задача — оценить ваш реальный подход, поэтому важен именно ваш ход мысли. "
            if not is_en
            else "Fair question. My goal is to evaluate your real approach, so your reasoning matters most. "
        )
        if generic_fallback or not normalized_fallback:
            normalized_fallback = _role_concrete_example_question(role=role, language=language)
        return f"{prefix}{normalized_fallback}".strip()

    if intent == "meta_question":
        prefix = (
            "Коротко по формату: мы проверяем навык на рабочих ситуациях. "
            if not is_en
            else "Quick format note: we assess skills through practical situations. "
        )
        return f"{prefix}{normalized_fallback}".strip()

    if intent == "clarification_request":
        prefix = (
            "Переформулирую проще. "
            if not is_en
            else "Let me rephrase more simply. "
        )
        if generic_fallback or not normalized_fallback:
            normalized_fallback = _role_concrete_example_question(role=role, language=language)
        return f"{prefix}{normalized_fallback}".strip()

    if intent == "request_example":
        prefix = (
            "Ок, давайте на конкретном примере. "
            if not is_en
            else "Okay, let's use a concrete example. "
        )
        if not normalized_fallback:
            normalized_fallback = _role_concrete_example_question(role=role, language=language)
        elif generic_fallback or not any(
            marker in normalized_fallback.lower()
            for marker in ("кейс", "сценар", "пример", "платеж", "перевод", "инцидент", "api", "endpoint", "for example", "scenario")
        ):
            normalized_fallback = _role_concrete_example_question(role=role, language=language)
        return f"{prefix}{normalized_fallback}".strip()

    if intent == "request_resume_focus":
        context_hint = (resume_context or "").strip()
        if not context_hint:
            context_hint = (
                "вашего опыта в этой роли"
                if not is_en
                else "your role experience"
            )
        prefix = (
            f"Ок, вернёмся к вашему контексту ({context_hint}). "
            if not is_en
            else f"Okay, let's return to your context ({context_hint}). "
        )
        return f"{prefix}{normalized_fallback}".strip()

    return normalized_fallback
