from __future__ import annotations

import re

from app.ai.interviewer import extract_mentioned_technologies
from app.ai.resume_anchor_filters import (
    filter_resume_anchors_for_role,
    filter_verification_targets_for_role,
    is_low_signal_resume_anchor,
    is_non_experience_resume_line,
)

_WHITESPACE_RE = re.compile(r"\s+")
_EXPERIENCE_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:years?|года?|лет)", re.IGNORECASE)

_SKIP_PREFIXES = (
    "email",
    "phone",
    "github",
    "linkedin",
    "telegram",
    "skills",
    "навыки",
    "summary",
    "education",
    "образование",
)
_PERSONAL_INFO_RE = re.compile(
    r"\b("
    r"мужчина|женщина|родил[а-я]*|дата рождения|возраст|гражданство|"
    r"age|years old|date of birth|citizenship|male|female"
    r")\b",
    re.IGNORECASE,
)
_EXPERIENCE_ACTION_RE = re.compile(
    r"\b("
    r"разработ|внедр|оптимиз|тестир|автоматиз|сопровожд|настро|постро|"
    r"руковод|анализ|улучш|сниз|повыс|ускор|запуст|мигрир|"
    r"built|implemented|designed|optimized|tested|automated|maintained|"
    r"led|managed|improved|reduced|increased|launched|migrated"
    r")",
    re.IGNORECASE,
)
_EXPERIENCE_CONTEXT_RE = re.compile(
    r"\b("
    r"project|production|api|service|system|platform|pipeline|dataset|model|ml|"
    r"проект|продакш|сервис|система|платформ|пайплайн|данн|модел|аналит|тест"
    r")\b",
    re.IGNORECASE,
)
_EXPERIENCE_SECTION_RE = re.compile(
    r"^(?:опыт(?:\s+работы)?|experience|work experience|professional experience|employment history|projects?|проекты?)\b",
    re.IGNORECASE,
)
_EDUCATION_SECTION_RE = re.compile(
    r"^(?:образование|education|academic background)\b",
    re.IGNORECASE,
)
_SKILLS_SECTION_RE = re.compile(
    r"^(?:навыки|skills?|tech stack|технологии|инструменты)\b",
    re.IGNORECASE,
)
_CONTACT_SECTION_RE = re.compile(
    r"^(?:контакты|contact|personal info|личные данные)\b",
    re.IGNORECASE,
)

_ROLE_TECH_PRIORITIES: dict[str, list[str]] = {
    "backend_engineer": ["postgresql", "redis", "kafka", "docker", "kubernetes", "microservices", "grpc"],
    "frontend_engineer": ["react", "graphql", "aws"],
    "qa_engineer": ["api_testing", "test_automation", "ci_cd", "monitoring", "graphql"],
    "devops_engineer": ["kubernetes", "docker", "aws", "nginx", "clickhouse", "airflow"],
    "data_scientist": ["spark", "airflow", "postgresql", "aws"],
    "product_manager": ["a_b_testing", "analytics", "experimentation", "product_metrics"],
    "designer": ["figma", "ux_research", "design_system", "usability"],
    "mobile_engineer": ["graphql", "aws"],
}


def _detect_resume_section(line: str) -> str | None:
    lowered = line.lower().strip()
    lowered = lowered.rstrip(":")
    if _EXPERIENCE_SECTION_RE.match(lowered):
        return "experience"
    if _EDUCATION_SECTION_RE.match(lowered):
        return "education"
    if _SKILLS_SECTION_RE.match(lowered):
        return "skills"
    if _CONTACT_SECTION_RE.match(lowered):
        return "contact"
    return None


def _extract_structured_resume_lines(raw_text: str | None) -> list[dict]:
    if not raw_text:
        return []

    normalized_lines: list[dict] = []
    active_section = "experience"
    for raw_line in raw_text.splitlines():
        line = _WHITESPACE_RE.sub(" ", raw_line).strip(" \t-•|")
        if len(line) < 3:
            continue
        lower = line.lower()
        section_header = _detect_resume_section(line)
        if section_header:
            active_section = section_header
            continue

        if "@" in line or any(lower.startswith(prefix) for prefix in _SKIP_PREFIXES):
            continue
        if _PERSONAL_INFO_RE.search(lower):
            continue
        if is_non_experience_resume_line(line):
            continue
        if not re.search(r"[a-zA-Zа-яА-Я0-9]", line):
            continue
        normalized_lines.append(
            {
                "line": line[:180],
                "section": active_section,
            }
        )

    return normalized_lines


def _line_signal_score(line: str, section: str) -> int:
    lowered = line.lower()
    has_action = bool(_EXPERIENCE_ACTION_RE.search(lowered))
    has_context = bool(_EXPERIENCE_CONTEXT_RE.search(lowered))
    has_number = bool(re.search(r"\d", line))
    has_tech = bool(extract_mentioned_technologies(line))

    score = 0
    if section == "experience":
        score += 2
    if has_action:
        score += 2
    if has_tech:
        score += 2
    if has_context:
        score += 1
    if has_number:
        score += 1
    return score


def _extract_project_highlights(structured_lines: list[dict], limit: int = 4) -> list[str]:
    if not structured_lines:
        return []

    scored_lines: list[tuple[int, int, str]] = []
    fallback_lines: list[tuple[int, int, str]] = []

    for idx, item in enumerate(structured_lines):
        line = str(item.get("line") or "").strip()
        section = str(item.get("section") or "experience")
        if len(line) < 24:
            continue
        if section in {"education", "skills", "contact"}:
            continue
        if is_low_signal_resume_anchor(line):
            continue

        score = _line_signal_score(line, section)
        payload = (score, -idx, line[:140])
        if score >= 4:
            scored_lines.append(payload)
        else:
            fallback_lines.append(payload)

    selected = sorted(scored_lines, reverse=True)[:limit]
    if not selected:
        selected = sorted(fallback_lines, reverse=True)[:limit]
    return [line for _, _, line in selected]


def _extract_education_highlights(structured_lines: list[dict], limit: int = 2) -> list[str]:
    highlights: list[str] = []
    for item in structured_lines:
        line = str(item.get("line") or "").strip()
        section = str(item.get("section") or "")
        if section != "education":
            continue
        if len(line) < 12:
            continue
        highlights.append(line[:140])
        if len(highlights) >= limit:
            break
    return highlights


def _build_interview_resume_context(
    *,
    project_highlights: list[str],
    education_highlights: list[str],
    technologies: list[str],
) -> str:
    parts: list[str] = []
    if project_highlights:
        parts.append("Relevant experience highlights:\n" + "\n".join(f"- {line}" for line in project_highlights[:4]))
    if education_highlights:
        parts.append("Education highlights:\n" + "\n".join(f"- {line}" for line in education_highlights[:2]))
    if technologies:
        parts.append("Core technologies:\n- " + ", ".join(technologies[:10]))
    return "\n\n".join(parts)[:2200]


def _extract_experience_years(raw_text: str | None) -> int | None:
    if not raw_text:
        return None
    matches = [int(match.group(1)) for match in _EXPERIENCE_RE.finditer(raw_text)]
    return max(matches) if matches else None


def _infer_seniority(raw_text: str | None, years: int | None) -> str | None:
    text = (raw_text or "").lower()
    if any(token in text for token in ("staff", "principal", "архитектор")):
        return "staff"
    if any(token in text for token in ("lead", "senior", "тимлид", "сеньор")) or (years is not None and years >= 5):
        return "senior"
    if any(token in text for token in ("middle", "mid", "мидл")) or (years is not None and years >= 2):
        return "middle"
    if any(token in text for token in ("junior", "джун")) or (years is not None and years < 2):
        return "junior"
    return None


def preprocess_resume(raw_text: str | None, target_role: str) -> dict:
    structured_lines = _extract_structured_resume_lines(raw_text)
    technologies = sorted(extract_mentioned_technologies(raw_text or ""))
    project_highlights = filter_resume_anchors_for_role(
        target_role,
        _extract_project_highlights(structured_lines),
    )
    education_highlights = _extract_education_highlights(structured_lines)
    years = _extract_experience_years(raw_text)
    seniority = _infer_seniority(raw_text, years)
    interview_resume_context = _build_interview_resume_context(
        project_highlights=project_highlights,
        education_highlights=education_highlights,
        technologies=technologies,
    )

    prioritized = _ROLE_TECH_PRIORITIES.get(target_role, [])
    verification_targets = [tech for tech in prioritized if tech in technologies]
    if len(verification_targets) < 3:
        for tech in technologies:
            if tech not in verification_targets:
                verification_targets.append(tech)
            if len(verification_targets) >= 3:
                break
    verification_targets = filter_verification_targets_for_role(target_role, verification_targets)

    return {
        "technologies": technologies,
        "project_highlights": project_highlights,
        "education_highlights": education_highlights,
        "verification_targets": verification_targets,
        "experience_years": years,
        "seniority_hint": seniority,
        "interview_resume_context": interview_resume_context,
        "structured_resume_lines": structured_lines[:40],
    }
