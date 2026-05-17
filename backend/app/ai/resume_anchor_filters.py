from __future__ import annotations

import re

_WHITESPACE_RE = re.compile(r"\s+")

_NON_EXPERIENCE_LABEL_RE = re.compile(
    r"^\s*(?:"
    r"прожива(?:ет|ю)|место жительства|адрес|город|локац(?:ия|ии)|"
    r"location|city|address|based in|residence"
    r")\s*[:\-]",
    re.IGNORECASE,
)

_NON_EXPERIENCE_CONTENT_RE = re.compile(
    r"\b(?:"
    r"готов[а-я\s]{0,20}к\s+переез[дуае]*|"
    r"готов[а-я\s]{0,20}к\s+командировк|"
    r"релокац(?:ия|ии)|"
    r"willing to relocate|open to relocate|ready to relocate|"
    r"willing to travel|open to travel|available for travel"
    r")\b",
    re.IGNORECASE,
)

_PROFILE_FIELD_HEADER_RE = re.compile(
    r"^\s*(?:"
    r"желаем(?:ая|ая\s+должность|ая\s+позиция)|должность|позиция|зарплата|ожидаемая зарплата|"
    r"личные данные|контакты|о себе|цель|ключевые навыки|навыки|"
    r"desired position|position|role|salary|expected salary|objective|profile|about me|contact"
    r")\s*(?:[:\-]|$)",
    re.IGNORECASE,
)

_LIKELY_FULL_NAME_RE = re.compile(
    r"^\s*(?:[A-ZА-ЯЁ][a-zа-яё'-]{1,24}\s+){1,3}[A-ZА-ЯЁ][a-zа-яё'-]{1,24}\s*$"
)

_PROFILE_FIELD_PREFIXES = (
    "желаемая должность",
    "желаемая позиция",
    "ожидаемая зарплата",
    "зарплата",
    "должность",
    "позиция",
    "личные данные",
    "контакты",
    "о себе",
    "цель",
    "ключевые навыки",
    "навыки",
    "desired position",
    "expected salary",
    "salary",
    "objective",
    "profile",
    "about me",
    "contact",
)

_ROLE_TITLE_TOKENS = {
    "руководитель",
    "инженер",
    "менеджер",
    "аналитик",
    "архитектор",
    "тестировщик",
    "разработчик",
    "дизайнер",
    "qa",
    "devops",
    "data",
    "scientist",
    "developer",
    "engineer",
    "manager",
    "lead",
    "architect",
    "analyst",
    "tester",
    "designer",
}

_ACTION_VERB_EVIDENCE_RE = re.compile(
    r"\b("
    r"разработал|разрабатывал|внедрил|внедрял|оптимизировал|оптимизировал[аи]?|"
    r"тестировал|тестирова[лт]|автоматизировал|автоматизирова[лт]|"
    r"сопровождал|настроил|настраивал|построил|строил|"
    r"руководил|управлял|анализировал|улучшил|снизил|повысил|ускорил|запустил|мигрировал|"
    r"built|implemented|designed|optimized|tested|automated|maintained|"
    r"managed|improved|reduced|increased|launched|migrated|led"
    r")\b",
    re.IGNORECASE,
)
_TECH_CONTEXT_RE = re.compile(
    r"\b("
    r"project|production|api|service|system|platform|pipeline|dataset|model|ml|"
    r"проект|продакш|сервис|система|платформ|пайплайн|данн|модел|аналит|тест|мобильн|приложен"
    r")\b",
    re.IGNORECASE,
)

_ROLE_SPECIFIC_ANCHOR_CONTEXT: dict[str, tuple[str, ...]] = {
    "qa_engineer": (
        "qa",
        "quality",
        "тест",
        "дефект",
        "баг",
        "регресс",
        "smoke",
        "api",
        "релиз",
        "root cause",
        "inciden",
    ),
    "frontend_engineer": (
        "frontend",
        "ui",
        "ux",
        "browser",
        "react",
        "vue",
        "angular",
        "css",
        "layout",
        "web",
    ),
    "product_manager": (
        "product",
        "roadmap",
        "priorit",
        "metric",
        "hypothes",
        "user",
        "stakeholder",
        "discovery",
        "backlog",
        "a/b",
    ),
}

_BACKEND_INFRA_PRIMARY_TERMS: tuple[str, ...] = (
    "postgresql",
    "postgres",
    "sql",
    "database",
    "db ",
    " redis",
    "redis ",
    "kafka",
)

_ROLE_PRIMARY_TECH_BLOCKLIST: dict[str, tuple[str, ...]] = {
    "qa_engineer": _BACKEND_INFRA_PRIMARY_TERMS,
    "frontend_engineer": _BACKEND_INFRA_PRIMARY_TERMS + ("kubernetes", "docker", "grpc", "rabbitmq"),
    "product_manager": _BACKEND_INFRA_PRIMARY_TERMS + ("kubernetes", "docker", "grpc", "rabbitmq", "clickhouse"),
}

_ROLE_VERIFICATION_TARGET_BLOCKLIST: dict[str, set[str]] = {
    "qa_engineer": {"postgresql", "sql", "database", "redis", "kafka"},
    "frontend_engineer": {"postgresql", "sql", "database", "redis", "kafka", "kubernetes", "docker", "grpc"},
    "product_manager": {"postgresql", "sql", "database", "redis", "kafka", "kubernetes", "docker", "grpc"},
}


def normalize_resume_line(value: str | None) -> str:
    return _WHITESPACE_RE.sub(" ", str(value or "")).strip(" \t-•|")


def is_non_experience_resume_line(value: str | None) -> bool:
    line = normalize_resume_line(value)
    if not line:
        return True
    lower = line.lower()
    if _NON_EXPERIENCE_LABEL_RE.search(lower):
        return True
    if _NON_EXPERIENCE_CONTENT_RE.search(lower):
        return True
    if any(lower.startswith(prefix) for prefix in _PROFILE_FIELD_PREFIXES):
        return True
    if _PROFILE_FIELD_HEADER_RE.search(lower):
        return True
    if _LIKELY_FULL_NAME_RE.match(line):
        return True
    return False


def is_low_signal_resume_anchor(value: str | None) -> bool:
    """True for short role-title-only lines that should not drive interview questions."""
    line = normalize_resume_line(value)
    if not line:
        return True
    if is_non_experience_resume_line(line):
        return True

    lowered = line.lower().lstrip("—-• ").strip()
    tokens = re.findall(r"[a-zA-Zа-яА-ЯёЁ0-9+#._-]+", lowered)
    if not tokens:
        return True

    has_evidence = (
        bool(_ACTION_VERB_EVIDENCE_RE.search(lowered))
        or bool(_TECH_CONTEXT_RE.search(lowered))
        or bool(re.search(r"\d", lowered))
    )
    if has_evidence:
        return False

    has_title_token = any(token in _ROLE_TITLE_TOKENS for token in tokens)
    if has_title_token and len(tokens) <= 6:
        return True

    return False


def _contains_any_token(text: str, tokens: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in tokens)


def _has_role_context(role: str, line: str) -> bool:
    tokens = _ROLE_SPECIFIC_ANCHOR_CONTEXT.get(role, ())
    return _contains_any_token(line, tokens) if tokens else False


def _is_role_misaligned_anchor(role: str, line: str) -> bool:
    """True if line is likely to drag interview focus away from role competencies."""
    blocklist = _ROLE_PRIMARY_TECH_BLOCKLIST.get(role, ())
    if not blocklist:
        return False
    if not _contains_any_token(line, blocklist):
        return False

    # Keep anchors where candidate still describes role-relevant QA/Frontend/PM actions.
    if _has_role_context(role, line):
        return False

    # Keep only as personalization elsewhere, but do not allow as primary interview anchor.
    return True


def filter_resume_anchors_for_role(role: str, anchors: list[str] | tuple[str, ...] | None) -> list[str]:
    """Return role-safe experience anchors ordered as in resume.

    Role competency map is primary. Resume anchors are personalization only.
    """
    if not anchors:
        return []

    result: list[str] = []
    seen: set[str] = set()
    normalized_role = str(role or "").strip().lower()
    for raw_anchor in anchors:
        line = normalize_resume_line(raw_anchor)
        if not line:
            continue
        dedupe_key = line.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        if is_non_experience_resume_line(line):
            continue
        if is_low_signal_resume_anchor(line):
            continue
        if _is_role_misaligned_anchor(normalized_role, line):
            continue
        result.append(line)

    return result


def filter_verification_targets_for_role(role: str, targets: list[str] | tuple[str, ...] | None) -> list[str]:
    """Role-aware filter for resume-derived technologies used in verification prompts.

    These targets may personalize questions but must not replace role competency focus.
    """
    if not targets:
        return []

    normalized_role = str(role or "").strip().lower()
    blocked = _ROLE_VERIFICATION_TARGET_BLOCKLIST.get(normalized_role, set())
    filtered: list[str] = []
    seen: set[str] = set()
    for raw in targets:
        tech = normalize_resume_line(raw).lower()
        if not tech or tech in seen:
            continue
        seen.add(tech)
        if tech in blocked:
            continue
        filtered.append(tech)
    return filtered
