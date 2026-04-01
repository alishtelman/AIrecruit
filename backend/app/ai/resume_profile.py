from __future__ import annotations

import re

from app.ai.interviewer import extract_mentioned_technologies

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

_ROLE_TECH_PRIORITIES: dict[str, list[str]] = {
    "backend_engineer": ["postgresql", "redis", "kafka", "docker", "kubernetes", "microservices", "grpc"],
    "frontend_engineer": ["react", "graphql", "aws"],
    "qa_engineer": ["postgresql", "docker", "kubernetes", "graphql"],
    "devops_engineer": ["kubernetes", "docker", "aws", "nginx", "clickhouse", "airflow"],
    "data_scientist": ["spark", "airflow", "postgresql", "aws"],
    "mobile_engineer": ["graphql", "aws"],
}


def _extract_project_highlights(raw_text: str | None, limit: int = 4) -> list[str]:
    if not raw_text:
        return []

    highlights: list[str] = []
    for raw_line in raw_text.splitlines():
        line = _WHITESPACE_RE.sub(" ", raw_line).strip(" \t-•|")
        if len(line) < 24:
            continue
        lower = line.lower()
        if "@" in line or any(lower.startswith(prefix) for prefix in _SKIP_PREFIXES):
            continue
        if not re.search(r"[a-zA-Zа-яА-Я0-9]", line):
            continue
        highlights.append(line[:140])
        if len(highlights) >= limit:
            break
    return highlights


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
    technologies = sorted(extract_mentioned_technologies(raw_text or ""))
    project_highlights = _extract_project_highlights(raw_text)
    years = _extract_experience_years(raw_text)
    seniority = _infer_seniority(raw_text, years)

    prioritized = _ROLE_TECH_PRIORITIES.get(target_role, [])
    verification_targets = [tech for tech in prioritized if tech in technologies]
    if len(verification_targets) < 3:
        for tech in technologies:
            if tech not in verification_targets:
                verification_targets.append(tech)
            if len(verification_targets) >= 3:
                break

    return {
        "technologies": technologies,
        "project_highlights": project_highlights,
        "verification_targets": verification_targets,
        "experience_years": years,
        "seniority_hint": seniority,
    }
