"""
AI Assessor module — two-pass scientific assessment pipeline.

Pass 1: Per-question evidence extraction (answer quality, skills, red flags).
Pass 2: Competency scoring with evidence aggregation.

Singleton `assessor` is an LLMAssessor when Gemini is configured,
otherwise it is disabled.
"""
import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
import httpx
import tempfile
import textwrap
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.ai.calibration import build_calibration_prompt
from app.ai.competencies import get_competencies, get_category_weights
from app.ai.interviewer import classify_answer, extract_mentioned_technologies
from app.ai.model_preferences import (
    is_allowed_llm_model_preference,
    resolve_llm_runtime_model,
)
from app.ai.providers import LLMProvider, get_llm_provider
from app.ai.runtime_status import record_ai_error, record_ai_success
from app.core.config import settings

logger = logging.getLogger(__name__)
_DECISION_POLICY_VERSION = "v2-strict"

_ROLE_LABELS: dict[str, str] = {
    "backend_engineer": "Backend-разработчик",
    "frontend_engineer": "Frontend-разработчик",
    "qa_engineer": "QA-инженер",
    "devops_engineer": "DevOps-инженер",
    "data_scientist": "Data Scientist",
    "product_manager": "Продакт-менеджер",
    "mobile_engineer": "Mobile-разработчик",
    "designer": "UX/UI Дизайнер",
}

_ROLE_LABELS_EN: dict[str, str] = {
    "backend_engineer": "Backend Engineer",
    "frontend_engineer": "Frontend Engineer",
    "qa_engineer": "QA Engineer",
    "devops_engineer": "DevOps Engineer",
    "data_scientist": "Data Scientist",
    "product_manager": "Product Manager",
    "mobile_engineer": "Mobile Engineer",
    "designer": "UX/UI Designer",
}

_TECH_LABELS_RU: dict[str, str] = {
    "postgresql": "PostgreSQL",
    "redis": "Redis",
    "kafka": "Kafka",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "grpc": "gRPC",
    "microservices": "микросервисы",
}

_TECH_LABELS_EN: dict[str, str] = {
    "postgresql": "PostgreSQL",
    "redis": "Redis",
    "kafka": "Kafka",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "grpc": "gRPC",
    "microservices": "Microservices",
}

_COMPETENCY_LABELS_RU: dict[str, str] = {
    "System Design & Architecture": "Системный дизайн и архитектура",
    "Database Design & Optimization": "Проектирование и оптимизация БД",
    "API Design & Protocols": "Проектирование API и протоколы",
    "Programming Fundamentals": "Базовые знания программирования",
    "DevOps & Infrastructure": "DevOps и инфраструктура",
    "Security & Error Handling": "Безопасность и обработка ошибок",
    "Debugging & Problem Decomposition": "Отладка и декомпозиция проблем",
    "Technical Communication": "Техническая коммуникация",
    "Collaboration & Code Review": "Сотрудничество и код-ревью",
    "Ownership & Growth Mindset": "Ответственность и развитие",
}

_SUPPORT_INCIDENT_RE = re.compile(
    r"\b(support|incident|incidents|monitoring|grafana|logs?|helpdesk|operations?|production support)\b"
    r"|сопровожд|инцидент|эксплуатац|мониторинг|графан|логи|поддержк|руководител[ья] сопровождения",
    re.IGNORECASE,
)
_FRONTEND_CORE_EVIDENCE_RE = re.compile(
    r"react|next|vue|angular|javascript|typescript|css|html|dom|browser|component|hook|usestate|"
    r"setstate|usememo|usecallback|redux|zustand|webpack|vite|devtools|"
    r"реакт|ангуляр|компонент|хук|верстк|браузер|состояни|стейт",
    re.IGNORECASE,
)
_FRONTEND_CORE_COMPETENCY_RE = re.compile(
    r"ui framework|react|frontend|web performance|css|responsive|javascript|typescript|accessibility|testing|quality",
    re.IGNORECASE,
)


def _normalized_report_language(language: str | None) -> str:
    return "en" if (language or "").lower().startswith("en") else "ru"


def _role_label(target_role: str, language: str | None) -> str:
    normalized = _normalized_report_language(language)
    if normalized == "en":
        return _ROLE_LABELS_EN.get(target_role, target_role.replace("_", " ").title())
    return _ROLE_LABELS.get(target_role, target_role.replace("_", " "))


def _topic_label_text(label: str | None, language: str) -> str:
    if not label:
        return "Тема" if language == "ru" else "Topic"
    normalized = label.strip()
    if language == "ru":
        return _COMPETENCY_LABELS_RU.get(normalized, _TECH_LABELS_RU.get(normalized.lower(), normalized))
    return _TECH_LABELS_EN.get(normalized.lower(), normalized)

# ---------------------------------------------------------------------------
# Tool schemas for structured LLM output
# ---------------------------------------------------------------------------

_QUESTION_ANALYSIS_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_question_analysis",
        "description": "Submit per-question analysis for the interview transcript.",
        "parameters": {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "question_number": {"type": "integer"},
                            "targeted_competencies": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Competency names this Q&A evaluates",
                            },
                            "answer_quality": {
                                "type": "number",
                                "description": "Score 1-10 for answer quality",
                            },
                            "evidence": {
                                "type": "string",
                                "description": "Concrete evidence from the answer (quotes, examples)",
                            },
                            "skills_mentioned": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "skill": {"type": "string"},
                                        "proficiency": {
                                            "type": "string",
                                            "enum": ["beginner", "intermediate", "advanced", "expert"],
                                        },
                                    },
                                    "required": ["skill", "proficiency"],
                                },
                                "description": (
                                    "ONLY explicit, demonstrated skills from the answer. "
                                    "Do not include broad terms like api/rest/soap/backend/sql "
                                    "without concrete personal usage."
                                ),
                            },
                            "red_flags": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Any red flags detected (contradictions, fabrication, etc.)",
                            },
                            "specificity": {
                                "type": "string",
                                "enum": ["high", "medium", "low"],
                                "description": "Did the candidate give concrete examples?",
                            },
                            "depth": {
                                "type": "string",
                                "enum": ["expert", "strong", "adequate", "surface", "none"],
                            },
                            "ai_likelihood": {
                                "type": "number",
                                "description": (
                                    "Probability 0.0-1.0 that this answer was AI-generated. "
                                    "Look for: unnatural structure (bullet points without being asked), "
                                    "marker phrases ('Certainly', 'Great question', 'In conclusion', "
                                    "'As a professional'), no personal examples, "
                                    "covers every angle of a question perfectly, "
                                    "academic tone in a casual conversation, "
                                    "answers things that were NOT asked. "
                                    "0.0 = clearly human, 1.0 = almost certainly AI."
                                ),
                            },
                            "communication_star_structured": {
                                "type": "boolean",
                                "description": "True if candidate structured their response using STAR or another logical framework, False otherwise."
                            },
                            "communication_style": {
                                "type": "string",
                                "description": "Detailed description of communication clarity, brevity, structurization, or issues like rambling."
                            },
                            "problem_solving_approach": {
                                "type": "string",
                                "enum": ["first_principles", "structured_decomposition", "trial_and_error", "superficial_heuristics", "none"],
                                "description": "Problem-solving methodology demonstrated in the response."
                            },
                            "problem_solving_evidence": {
                                "type": "string",
                                "description": "Explicit evidence of hypothesis testing, root cause identification, or trade-off consideration."
                            },
                            "leadership_ownership": {
                                "type": "string",
                                "enum": ["strong_ownership", "collaborative", "passive_execution", "blame_shifting", "none"],
                                "description": "Degree of personal ownership and/or collaboration shown."
                            },
                        },
                        "required": [
                            "question_number", "targeted_competencies",
                            "answer_quality", "evidence", "skills_mentioned",
                            "red_flags", "specificity", "depth", "ai_likelihood",
                            "communication_star_structured", "communication_style",
                            "problem_solving_approach", "problem_solving_evidence",
                            "leadership_ownership"
                        ],
                    },
                },
            },
            "required": ["questions"],
        },
    },
}

_COMPETENCY_ASSESSMENT_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_competency_assessment",
        "description": "Submit competency-based assessment using evidence from question analysis.",
        "parameters": {
            "type": "object",
            "properties": {
                "competency_scores": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "competency": {"type": "string"},
                            "category": {"type": "string"},
                            "score": {"type": "number", "description": "1-10"},
                            "weight": {"type": "number"},
                            "evidence": {"type": "string"},
                            "reasoning": {"type": "string"},
                        },
                        "required": ["competency", "category", "score", "weight", "evidence", "reasoning"],
                    },
                },
                "strengths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "3-5 key strengths with evidence",
                },
                "weaknesses": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "2-4 areas for improvement with evidence",
                },
                "recommendations": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "2-4 specific development recommendations",
                },
                "hiring_recommendation": {
                    "type": "string",
                    "enum": ["strong_yes", "yes", "maybe", "no"],
                },
                "interview_summary": {
                    "type": "string",
                    "description": "2-3 sentence summary of the interview",
                },
                "response_consistency": {
                    "type": "number",
                    "description": "0-10 score for cross-answer coherence",
                },
                "red_flags": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "flag": {"type": "string"},
                            "evidence": {"type": "string"},
                            "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                        },
                        "required": ["flag", "evidence", "severity"],
                    },
                },
            },
            "required": [
                "competency_scores", "strengths", "weaknesses",
                "recommendations", "hiring_recommendation",
                "interview_summary", "response_consistency", "red_flags",
            ],
        },
    },
}

# Legacy single-pass tool (kept for fallback)
_ASSESSMENT_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_assessment",
        "description": "Отправить структурированную оценку кандидата по итогам собеседования.",
        "parameters": {
            "type": "object",
            "properties": {
                "overall_score": {"type": "number", "description": "Общий балл от 0 до 10"},
                "hard_skills_score": {"type": "number", "description": "Оценка технических навыков от 0 до 10"},
                "soft_skills_score": {"type": "number", "description": "Оценка soft skills от 0 до 10"},
                "communication_score": {"type": "number", "description": "Оценка коммуникативных навыков от 0 до 10"},
                "strengths": {"type": "array", "items": {"type": "string"}, "description": "3–5 сильных сторон"},
                "weaknesses": {"type": "array", "items": {"type": "string"}, "description": "2–4 зоны роста"},
                "recommendations": {"type": "array", "items": {"type": "string"}, "description": "2–4 рекомендации"},
                "hiring_recommendation": {"type": "string", "enum": ["strong_yes", "yes", "maybe", "no"]},
                "interview_summary": {"type": "string", "description": "Краткое резюме собеседования"},
            },
            "required": [
                "overall_score", "hard_skills_score", "soft_skills_score",
                "communication_score", "strengths", "weaknesses",
                "recommendations", "hiring_recommendation", "interview_summary",
            ],
        },
    },
}


@dataclass
class AssessmentResult:
    overall_score: float
    hard_skills_score: float
    soft_skills_score: float
    communication_score: float
    strengths: list[str]
    weaknesses: list[str]
    recommendations: list[str]
    hiring_recommendation: str  # strong_yes | yes | maybe | no
    interview_summary: str | None
    model_version: str
    full_report_json: dict
    # New scientific fields
    competency_scores: list[dict] = field(default_factory=list)
    per_question_analysis: list[dict] = field(default_factory=list)
    skill_tags: list[dict] = field(default_factory=list)
    red_flags: list[dict] = field(default_factory=list)
    response_consistency: float | None = None
    problem_solving_score: float | None = None
    cheat_risk_score: float | None = None
    cheat_flags: list[str] = field(default_factory=list)
    overall_confidence: float | None = None
    competency_confidence: dict[str, float] | None = None
    confidence_reasons: list[str] = field(default_factory=list)
    evidence_coverage: dict | None = None
    decision_policy_version: str | None = None
    # Strict scoring fields (v2)
    answer_quality_score: float | None = None
    depth_score: float | None = None
    consistency_score: float | None = None
    score_penalties: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helper: compute aggregate scores from competency scores
# ---------------------------------------------------------------------------

def _compute_aggregates(
    competency_scores: list[dict],
    target_role: str,
) -> dict[str, float]:
    """Compute weighted aggregate scores from per-competency scores."""
    category_scores: dict[str, list[tuple[float, float]]] = {}
    total_weighted = 0.0
    total_weight = 0.0

    for cs in competency_scores:
        cat = cs.get("category", "")
        score = float(cs.get("score", 0))
        weight = float(cs.get("weight", 0))
        if cat not in category_scores:
            category_scores[cat] = []
        category_scores[cat].append((score, weight))
        total_weighted += score * weight
        total_weight += weight

    def _weighted_avg(pairs: list[tuple[float, float]]) -> float:
        tw = sum(w for _, w in pairs)
        if tw == 0:
            return 0.0
        return sum(s * w for s, w in pairs) / tw

    tech_core = category_scores.get("technical_core", [])
    tech_breadth = category_scores.get("technical_breadth", [])
    hard = _weighted_avg(tech_core + tech_breadth)

    soft = _weighted_avg(category_scores.get("behavioral", []))
    comm = _weighted_avg(category_scores.get("communication", []))
    ps = _weighted_avg(category_scores.get("problem_solving", []))
    overall = total_weighted / total_weight if total_weight else 0.0

    return {
        "overall_score": round(overall, 1),
        "hard_skills_score": round(hard, 1),
        "soft_skills_score": round(soft, 1),
        "communication_score": round(comm, 1),
        "problem_solving_score": round(ps, 1),
    }


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            result.append(text)
    return result


def _scored_metric_labels(metrics: list[str], report_language: str) -> list[str]:
    label_map_ru = {
        "technical_depth": "техническая глубина",
        "practical_experience": "практический опыт",
        "problem_solving": "решение задач",
        "communication": "коммуникация",
        "ownership": "ownership",
        "role_fit": "role fit",
        "growth_potential": "потенциал роста",
    }
    label_map_en = {
        "technical_depth": "technical depth",
        "practical_experience": "practical experience",
        "problem_solving": "problem solving",
        "communication": "communication",
        "ownership": "ownership",
        "role_fit": "role fit",
        "growth_potential": "growth potential",
    }
    normalized = [item.strip() for item in metrics if item.strip()]
    if report_language == "ru":
        return [label_map_ru.get(item, item.replace("_", " ")) for item in normalized]
    return [label_map_en.get(item, item.replace("_", " ")) for item in normalized]


def _topic_why_asked(block: str | None, report_language: str) -> str:
    key = str(block or "").strip().lower()
    why_ru = {
        "intro": "Вопрос задан для стартовой калибровки релевантности опыта и качества коммуникации.",
        "resume_followup": "Вопрос задан, чтобы проверить заявленный опыт из резюме на конкретных кейсах.",
        "technical_foundation": "Вопрос задан для проверки базовой технической практики по целевой роли.",
        "technical_depth": "Вопрос задан для углубленной проверки trade-offs, диагностики и решений в сложных условиях.",
        "behavioral_closing": "Вопрос задан для оценки поведения в командной и стрессовой ситуации перед финальной рекомендацией.",
    }
    why_en = {
        "intro": "This question is used to calibrate initial role fit and communication quality.",
        "resume_followup": "This question validates claimed resume experience through concrete real-world cases.",
        "technical_foundation": "This question checks baseline technical practice for the target role.",
        "technical_depth": "This question probes deeper trade-offs, diagnostics, and decision-making under constraints.",
        "behavioral_closing": "This question assesses teamwork and behavior under pressure before final recommendation.",
    }
    fallback = (
        "Вопрос задан в рамках структурированного плана интервью."
        if report_language == "ru"
        else "This question is part of the structured interview plan."
    )
    if report_language == "ru":
        return why_ru.get(key, fallback)
    return why_en.get(key, fallback)


def _topic_scoring_focus(scored_metrics: list[str], report_language: str) -> str:
    labels = _scored_metric_labels(scored_metrics, report_language)
    if not labels:
        return (
            "Оценивались релевантность, конкретика и глубина ответа."
            if report_language == "ru"
            else "Scoring focused on relevance, specificity, and depth of the answer."
        )
    joined = ", ".join(labels)
    if report_language == "ru":
        return f"Оценивались метрики: {joined}."
    return f"Scored metrics: {joined}."


def _enrich_per_question_analysis_with_topic_plan(
    per_question_analysis: list[dict],
    topic_plan: list[dict],
    report_language: str = "ru",
) -> list[dict]:
    if not per_question_analysis:
        return per_question_analysis

    enriched_items: list[dict] = []
    for item in per_question_analysis:
        if not isinstance(item, dict):
            enriched_items.append(item)
            continue

        q_num = _to_int(item.get("question_number"), 0)
        target = topic_plan[q_num - 1] if 0 < q_num <= len(topic_plan) else {}
        block = str(target.get("block") or "").strip() or None
        tier = str(target.get("tier") or "").strip() or None
        lead_question = str(target.get("lead_question") or "").strip() or None
        allowed_probes = _to_str_list(target.get("allowed_probes"))
        scored_metrics = _to_str_list(target.get("scored_metrics"))
        why_asked = _topic_why_asked(block, report_language)
        what_was_scored = _topic_scoring_focus(scored_metrics, report_language)

        enriched = dict(item)
        enriched["block"] = block
        enriched["tier"] = tier
        enriched["lead_question"] = lead_question
        enriched["allowed_probes"] = allowed_probes
        enriched["scored_metrics"] = scored_metrics
        enriched["why_asked"] = why_asked
        enriched["what_was_scored"] = what_was_scored
        enriched_items.append(enriched)

    return enriched_items


def _build_summary_model(
    target_role: str,
    report_language: str,
    interview_meta: dict | None,
    per_question_analysis: list[dict],
) -> dict:
    interview_meta = interview_meta or {}
    core_topics = int(interview_meta.get("question_count", 0) or 0)
    total_turns = int(interview_meta.get("turn_count", core_topics) or 0)
    extra_turns = max(total_turns - core_topics, 0)

    topic_signals: list[str] = list(interview_meta.get("topic_signals", []))
    topic_plan: list[dict] = list(interview_meta.get("topic_plan", []))
    verified_skills = {
        str(skill).lower()
        for skill in interview_meta.get("verified_skills", []) or []
        if skill
    }
    probed_claim_targets = {
        str(skill).lower()
        for skill in interview_meta.get("probed_claim_targets", []) or []
        if skill
    }

    def _topic_label(topic: dict, slot: int) -> str:
        verification_target = topic.get("verification_target")
        if verification_target:
            return _topic_label_text(str(verification_target), report_language)
        competencies = [str(item) for item in topic.get("competencies", []) if item]
        if competencies:
            return _topic_label_text(competencies[0], report_language)
        return f"Topic {slot}"

    def _slot_evidence_hint(items: list[dict]) -> str | None:
        for qa in items:
            evidence = str(qa.get("evidence", "")).strip()
            if not evidence:
                continue
            snippet = evidence[:120].strip()
            return snippet.rstrip(".") + ("..." if len(evidence) > 120 else "")
        return None

    per_question_by_slot: dict[int, list[dict]] = {}
    for qa in per_question_analysis:
        qn = int(qa.get("question_number", 0) or 0)
        if qn <= 0:
            continue
        per_question_by_slot.setdefault(qn, []).append(qa)

    def _slot_has_validated_evidence(items: list[dict]) -> bool:
        for qa in items:
            answer_quality = _to_float(qa.get("answer_quality"), 0.0)
            specificity = str(qa.get("specificity", "low")).lower()
            depth = str(qa.get("depth", "surface")).lower()
            ai_likelihood = _to_float(qa.get("ai_likelihood"), 0.0)
            evidence_text = str(qa.get("evidence", "")).lower()
            has_concrete_mechanism = any(
                token in evidence_text
                for token in (
                    "index",
                    "индекс",
                    "query plan",
                    "explain",
                    "retry",
                    "cache",
                    "outbox",
                    "consumer",
                    "partition",
                    "replication",
                    "latency",
                    "docker",
                    "ci/cd",
                )
            )
            if (
                answer_quality >= 7.0
                and specificity in {"medium", "high"}
                and depth in {"strong", "expert"}
                and ai_likelihood < 0.5
            ):
                return True
            if (
                answer_quality >= 7.8
                and specificity == "high"
                and depth == "adequate"
                and ai_likelihood < 0.4
            ):
                return True
            if (
                answer_quality >= 7.2
                and specificity in {"medium", "high"}
                and depth == "adequate"
                and has_concrete_mechanism
                and ai_likelihood < 0.35
            ):
                return True
        return False

    topic_outcomes: list[dict] = []
    max_topics = max(core_topics, len(topic_plan), len(topic_signals))
    for idx in range(max_topics):
        topic = topic_plan[idx] if idx < len(topic_plan) else {}
        signal = topic_signals[idx] if idx < len(topic_signals) else ""
        slot_questions = per_question_by_slot.get(idx + 1, [])
        verification_target = str(topic.get("verification_target") or "").lower()
        was_probed = bool(verification_target and verification_target in probed_claim_targets)
        was_verified = bool(verification_target and verification_target in verified_skills)
        has_validated_evidence = _slot_has_validated_evidence(slot_questions)

        if signal == "strong" or has_validated_evidence:
            outcome = "validated"
        elif signal == "partial":
            outcome = "partial"
        elif signal == "no_experience_honest":
            outcome = "honest_gap"
        elif signal == "evasive":
            outcome = "evasive"
        elif signal == "generic" and was_probed and not was_verified:
            outcome = "unverified_claim"
        elif signal == "generic":
            outcome = "partial"
        elif was_verified:
            outcome = "validated"
        else:
            outcome = "partial"

        scored_metrics = _to_str_list(topic.get("scored_metrics"))
        topic_outcomes.append(
            {
                "slot": idx + 1,
                "label": _topic_label(topic, idx + 1),
                "signal": signal or "unknown",
                "outcome": outcome,
                "verification_target": topic.get("verification_target"),
                "resume_anchor": topic.get("resume_anchor"),
                "evidence_hint": _slot_evidence_hint(slot_questions),
                "phase": topic.get("phase"),
                "block": topic.get("block"),
                "tier": topic.get("tier"),
                "lead_question": topic.get("lead_question"),
                "allowed_probes": _to_str_list(topic.get("allowed_probes")),
                "scored_metrics": scored_metrics,
                "why_asked": _topic_why_asked(topic.get("block"), report_language),
                "what_was_scored": _topic_scoring_focus(scored_metrics, report_language),
            }
        )

    honest_gaps = sum(1 for item in topic_outcomes if item["outcome"] == "honest_gap")
    evasive_topics = sum(1 for item in topic_outcomes if item["outcome"] == "evasive")
    unverified_claim_topics = sum(1 for item in topic_outcomes if item["outcome"] == "unverified_claim")
    partial_topics = sum(1 for item in topic_outcomes if item["outcome"] == "partial")
    validated_topics = sum(1 for item in topic_outcomes if item["outcome"] == "validated")
    strong_topics = sum(1 for item in topic_outcomes if item["signal"] == "strong")
    generic_topics = unverified_claim_topics
    evasive_or_generic = unverified_claim_topics + evasive_topics

    covered_competencies = {
        comp
        for qa in per_question_analysis
        for comp in qa.get("targeted_competencies", [])
    }

    if (
        (strong_topics >= max(2, core_topics // 2) or validated_topics >= max(3, core_topics // 2 or 1))
        and honest_gaps == 0
        and evasive_or_generic <= 1
    ):
        signal_quality = "high"
    elif (
        validated_topics >= max(2, core_topics // 3 or 1)
        and unverified_claim_topics < max(2, core_topics // 2 or 1)
    ) or (
        strong_topics >= 1
        and partial_topics >= max(3, core_topics // 2)
        and honest_gaps == 0
    ) or (
        validated_topics == 0
        and partial_topics >= max(5, core_topics - 2)
        and honest_gaps == 0
        and unverified_claim_topics <= 2
        and evasive_or_generic <= 2
    ):
        signal_quality = "medium"
    else:
        signal_quality = "limited"
    coverage_label = (
        f"{len(covered_competencies)} компетенций"
        if report_language == "ru"
        else f"{len(covered_competencies)} competencies"
    )

    return {
        "role": _role_label(target_role, report_language),
        "core_topics": core_topics,
        "total_turns": total_turns,
        "extra_turns": extra_turns,
        "covered_competencies": len(covered_competencies),
        "coverage_label": coverage_label,
        "signal_quality": signal_quality,
        "validated_topics": validated_topics,
        "partial_topics": partial_topics,
        "unverified_claim_topics": unverified_claim_topics,
        "honest_gaps": honest_gaps,
        "generic_topics": generic_topics,
        "evasive_topics": evasive_topics,
        "generic_or_evasive_topics": evasive_or_generic,
        "strong_topics": strong_topics,
        "topic_outcomes": topic_outcomes,
    }


def _build_interview_summary_text(
    target_role: str,
    report_language: str,
    summary_model: dict,
    overall_score: float,
) -> str:
    role_label = _role_label(target_role, report_language)
    core_topics = summary_model.get("core_topics", 0)
    extra_turns = summary_model.get("extra_turns", 0)
    honest_gaps = summary_model.get("honest_gaps", 0)
    signal_quality = summary_model.get("signal_quality")
    signal_quality_label = {
        "ru": {
            "high": "высокий",
            "medium": "средний",
            "limited": "ограниченный",
        },
        "en": {
            "high": "high",
            "medium": "medium",
            "limited": "limited",
        },
    }[report_language].get(signal_quality, signal_quality)

    if report_language == "ru":
        parts = [
            f"Интервью на роль «{role_label}» покрыло {core_topics} ключевых тем",
        ]
        if extra_turns:
            parts.append(f"и включало {extra_turns} уточняющих хода")
        parts.append(f"Уровень сигнала: {signal_quality_label}.")
        if honest_gaps:
            parts.append(f"По {honest_gaps} темам кандидат честно обозначил пробелы в опыте.")
        parts.append(f"Итоговый балл: {overall_score}/10.")
        return " ".join(parts)

    parts = [
        f"The {role_label} interview covered {core_topics} core topics",
    ]
    if extra_turns:
        parts.append(f"and included {extra_turns} extra probing turns")
    parts.append(f"Signal quality was {signal_quality_label}.")
    if honest_gaps:
        parts.append(f"The candidate explicitly acknowledged experience gaps in {honest_gaps} topics.")
    parts.append(f"Overall score: {overall_score}/10.")
    return " ".join(parts)


_CALIBRATED_METRIC_WEIGHTS: dict[str, float] = {
    "technical_depth": 0.22,
    "practical_experience": 0.20,
    "problem_solving": 0.18,
    "communication": 0.14,
    "ownership": 0.10,
    "role_fit": 0.10,
    "growth_potential": 0.06,
}

_CALIBRATED_BLOCK_WEIGHTS: dict[str, float] = {
    "intro": 0.10,
    "resume_followup": 0.20,
    "technical_foundation": 0.28,
    "technical_depth": 0.30,
    "behavioral_closing": 0.12,
}


def _depth_score_10(depth: str) -> float:
    return {
        "none": 1.0,
        "surface": 3.0,
        "adequate": 6.0,
        "strong": 8.0,
        "expert": 10.0,
    }.get(str(depth or "").strip().lower(), 4.0)


def _specificity_score_10(specificity: str) -> float:
    return {
        "low": 3.5,
        "medium": 6.8,
        "high": 9.0,
    }.get(str(specificity or "").strip().lower(), 5.5)


def _metric_score_from_question(question_item: dict, metric: str) -> float:
    answer_quality = max(0.0, min(_to_float(question_item.get("answer_quality"), 5.0), 10.0))
    depth_score = _depth_score_10(str(question_item.get("depth", "adequate")))
    specificity_score = _specificity_score_10(str(question_item.get("specificity", "medium")))
    evidence_text = str(question_item.get("evidence", "")).strip().lower()
    evidence_len = len(evidence_text)
    evidence_density = min(10.0, max(2.5, evidence_len / 18.0))
    targeted_count = len(_to_str_list(question_item.get("targeted_competencies")))
    has_tradeoff_signal = bool(re.search(r"(trade-?off|компромисс|почему|because|why|решил|decid)", evidence_text))
    has_ownership_signal = bool(re.search(r"\b(я|i|my|мой|моя|мы|our)\b", evidence_text))
    has_growth_signal = bool(re.search(r"(learn|improv|growth|ошиб|ретро|feedback|развив|улучш)", evidence_text))

    metric_key = str(metric or "").strip()
    if metric_key == "technical_depth":
        score = answer_quality * 0.55 + depth_score * 0.45
    elif metric_key == "practical_experience":
        score = answer_quality * 0.45 + specificity_score * 0.30 + evidence_density * 0.25
    elif metric_key == "problem_solving":
        score = answer_quality * 0.55 + depth_score * 0.25 + (8.5 if has_tradeoff_signal else 5.0) * 0.20
    elif metric_key == "communication":
        score = answer_quality * 0.45 + specificity_score * 0.35 + evidence_density * 0.20
    elif metric_key == "ownership":
        score = answer_quality * 0.55 + specificity_score * 0.20 + (8.8 if has_ownership_signal else 5.2) * 0.25
    elif metric_key == "role_fit":
        role_fit_signal = min(10.0, 5.5 + targeted_count * 1.3)
        score = answer_quality * 0.70 + role_fit_signal * 0.30
    elif metric_key == "growth_potential":
        growth_signal = 8.5 if has_growth_signal else 5.0
        score = answer_quality * 0.55 + specificity_score * 0.20 + growth_signal * 0.25
    else:
        score = answer_quality * 0.65 + depth_score * 0.20 + specificity_score * 0.15

    return round(max(0.0, min(score, 10.0)), 2)


def _normalize_metric_weight_subset(metrics: list[str]) -> dict[str, float]:
    normalized_metrics = [item for item in metrics if item in _CALIBRATED_METRIC_WEIGHTS]
    if not normalized_metrics:
        normalized_metrics = ["technical_depth", "practical_experience", "problem_solving", "communication"]
    total = sum(_CALIBRATED_METRIC_WEIGHTS[item] for item in normalized_metrics)
    if total <= 0:
        equal = round(1.0 / max(1, len(normalized_metrics)), 4)
        return {item: equal for item in normalized_metrics}
    return {item: round(_CALIBRATED_METRIC_WEIGHTS[item] / total, 4) for item in normalized_metrics}


def _normalize_block_weight_subset(blocks: list[str]) -> dict[str, float]:
    normalized_blocks = [item for item in blocks if item in _CALIBRATED_BLOCK_WEIGHTS]
    if not normalized_blocks:
        return {}
    total = sum(_CALIBRATED_BLOCK_WEIGHTS[item] for item in normalized_blocks)
    if total <= 0:
        equal = round(1.0 / max(1, len(normalized_blocks)), 4)
        return {item: equal for item in normalized_blocks}
    return {item: round(_CALIBRATED_BLOCK_WEIGHTS[item] / total, 4) for item in normalized_blocks}


def _build_calibrated_scoring(
    *,
    per_question_analysis: list[dict],
    summary_model: dict,
    report_language: str,
    aggregates_pre_penalty: dict[str, float],
    aggregates_final: dict[str, float],
    penalties: list[str],
) -> dict:
    block_rows: dict[str, dict] = {}
    for qa in per_question_analysis:
        block = str(qa.get("block") or "").strip().lower() or "technical_foundation"
        row = block_rows.setdefault(
            block,
            {
                "question_count": 0,
                "answer_quality_sum": 0.0,
                "depth_sum": 0.0,
                "specificity_sum": 0.0,
                "metrics": set(),
                "metric_values": {},
            },
        )
        row["question_count"] += 1
        row["answer_quality_sum"] += max(0.0, min(_to_float(qa.get("answer_quality"), 5.0), 10.0))
        row["depth_sum"] += _depth_score_10(str(qa.get("depth", "adequate")))
        row["specificity_sum"] += _specificity_score_10(str(qa.get("specificity", "medium")))
        scored_metrics = _to_str_list(qa.get("scored_metrics"))
        if not scored_metrics:
            scored_metrics = ["technical_depth", "practical_experience", "problem_solving", "communication"]
        for metric in scored_metrics:
            if metric not in _CALIBRATED_METRIC_WEIGHTS:
                continue
            row["metrics"].add(metric)
            row["metric_values"].setdefault(metric, []).append(_metric_score_from_question(qa, metric))

    present_blocks = list(block_rows.keys())
    block_weights = _normalize_block_weight_subset(present_blocks)
    block_metrics: list[dict] = []
    weighted_sum = 0.0
    total_weight = 0.0
    for block in present_blocks:
        row = block_rows[block]
        q_count = max(1, int(row["question_count"]))
        metrics_sorted = sorted(row["metrics"]) if row["metrics"] else []
        metric_weights = _normalize_metric_weight_subset(metrics_sorted)
        metric_scores: dict[str, float] = {}
        block_score_sum = 0.0
        block_score_weight = 0.0
        for metric, weight in metric_weights.items():
            values = row["metric_values"].get(metric, [])
            metric_score = round(sum(values) / len(values), 2) if values else 0.0
            metric_scores[metric] = metric_score
            block_score_sum += metric_score * weight
            block_score_weight += weight
        block_score = round(block_score_sum / block_score_weight, 2) if block_score_weight > 0 else 0.0
        block_weight = block_weights.get(block, 0.0)
        weighted_sum += block_score * block_weight
        total_weight += block_weight
        block_metrics.append(
            {
                "block": block,
                "weight": block_weight,
                "question_count": q_count,
                "score": block_score,
                "avg_answer_quality": round(row["answer_quality_sum"] / q_count, 2),
                "avg_depth_score": round(row["depth_sum"] / q_count, 2),
                "avg_specificity_score": round(row["specificity_sum"] / q_count, 2),
                "metric_weights": metric_weights,
                "metric_scores": metric_scores,
                "why_asked": _topic_why_asked(block, report_language),
                "what_was_scored": _topic_scoring_focus(metrics_sorted, report_language),
            }
        )

    block_metrics.sort(key=lambda item: item["weight"], reverse=True)
    block_weighted_score = round(weighted_sum / total_weight, 2) if total_weight > 0 else 0.0
    pre_overall = round(_to_float(aggregates_pre_penalty.get("overall_score"), 0.0), 2)
    final_overall = round(_to_float(aggregates_final.get("overall_score"), 0.0), 2)

    return {
        "metric_weight_model": _CALIBRATED_METRIC_WEIGHTS,
        "block_weight_model": block_weights,
        "block_metrics": block_metrics,
        "block_weighted_score": block_weighted_score,
        "penalties": penalties,
        "pre_penalty_overall_score": pre_overall,
        "post_penalty_overall_score": final_overall,
        "penalty_delta": round(final_overall - pre_overall, 2),
        "topic_signal_quality": str(summary_model.get("signal_quality") or "unknown"),
    }


def _recommendation_label(recommendation: str, report_language: str) -> str:
    mapping_ru = {
        "strong_yes": "Strong Yes",
        "yes": "Yes",
        "maybe": "Maybe",
        "no": "No",
    }
    mapping_en = {
        "strong_yes": "Strong Yes",
        "yes": "Yes",
        "maybe": "Maybe",
        "no": "No",
    }
    if report_language == "ru":
        return mapping_ru.get(recommendation, recommendation)
    return mapping_en.get(recommendation, recommendation)


def _short_text(text: str | None, limit: int = 180) -> str:
    normalized = str(text or "").strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)].rstrip() + "..."


def _map_penalty_to_explanation(penalty: str, report_language: str) -> str:
    normalized = str(penalty or "").strip().lower()
    if not normalized:
        return ""
    if report_language == "ru":
        mapping = [
            ("short_answers", "Короткие ответы снизили итоговый балл, потому что не хватило проверяемой конкретики."),
            ("generic_answers", "Часть ответов была слишком общей, поэтому сигнал по практическому опыту ослаб."),
            ("weak_answers", "Среднее качество ответов было низким, из-за чего общий балл ограничен."),
            ("critical_weakness", "Критические просадки по ключевым компетенциям ограничили финальную рекомендацию."),
            ("multiple_critical_weaknesses", "Несколько критически слабых компетенций ограничили общий потолок оценки."),
            ("low_response_consistency", "Обнаружены противоречия между ответами, это снизило доверие к итоговому уровню."),
            ("unstable_response_consistency", "Согласованность ответов ниже желаемой, поэтому итоговая оценка ограничена."),
            ("low_signal_quality", "Низкое качество сигнала по темам интервью не позволило поднять итог выше."),
        ]
    else:
        mapping = [
            ("short_answers", "Short answers reduced the score because there was not enough verifiable detail."),
            ("generic_answers", "Several answers were too generic, which weakened the practical signal."),
            ("weak_answers", "Average answer quality was low, so the overall score was capped."),
            ("critical_weakness", "Critical weakness in key competencies limited the final recommendation."),
            ("multiple_critical_weaknesses", "Multiple critical competency weaknesses capped the overall result."),
            ("low_response_consistency", "Contradictions between answers lowered trust in the final level."),
            ("unstable_response_consistency", "Cross-answer consistency was below target, so the score was constrained."),
            ("low_signal_quality", "Low topic-level signal quality prevented a higher final result."),
        ]
    for marker, text in mapping:
        if marker in normalized:
            return text
    return penalty


def _build_explainability_report(
    *,
    target_role: str,
    report_language: str,
    summary_model: dict,
    per_question_analysis: list[dict],
    strengths: list[str],
    weaknesses: list[str],
    recommendations: list[str],
    hiring_recommendation: str,
    overall_score: float,
    overall_confidence: float | None,
    calibrated_scoring: dict,
    penalties: list[str],
) -> dict:
    topic_outcomes = list(summary_model.get("topic_outcomes", []) or [])
    qa_by_question: dict[int, dict] = {}
    for qa in per_question_analysis:
        question_number = int(qa.get("question_number", 0) or 0)
        if question_number <= 0:
            continue
        current = qa_by_question.get(question_number)
        if current is None or _to_float(qa.get("answer_quality"), 0.0) >= _to_float(current.get("answer_quality"), 0.0):
            qa_by_question[question_number] = qa

    def _build_evidence_item(topic: dict) -> dict:
        question_number = int(topic.get("slot", 0) or 0)
        qa = qa_by_question.get(question_number, {})
        evidence_hint = str(topic.get("evidence_hint") or qa.get("evidence") or "").strip()
        return {
            "question_number": question_number,
            "topic": str(topic.get("label") or ""),
            "signal": str(topic.get("signal") or "unknown"),
            "outcome": str(topic.get("outcome") or "partial"),
            "answer_quality": round(_to_float(qa.get("answer_quality"), 0.0), 1) if qa else None,
            "evidence_excerpt": _short_text(evidence_hint, 220),
            "why_asked": str(topic.get("why_asked") or qa.get("why_asked") or ""),
            "what_was_scored": str(topic.get("what_was_scored") or qa.get("what_was_scored") or ""),
            "scored_metrics": _to_str_list(topic.get("scored_metrics") or qa.get("scored_metrics")),
        }

    strength_topics = [
        item
        for item in topic_outcomes
        if item.get("outcome") == "validated" or (item.get("outcome") == "partial" and item.get("signal") == "strong")
    ][:3]
    if not strength_topics:
        strength_topics = [item for item in topic_outcomes if item.get("outcome") == "partial"][:2]

    gap_topics = [
        item
        for item in topic_outcomes
        if item.get("outcome") in {"honest_gap", "unverified_claim", "evasive"}
    ][:4]
    if not gap_topics:
        gap_topics = [item for item in topic_outcomes if item.get("outcome") == "partial" and item.get("signal") in {"generic", "evasive"}][:3]

    strength_items: list[dict] = []
    for topic in strength_topics:
        label = str(topic.get("label") or "")
        if report_language == "ru":
            title = f"Подтвержден рабочий сигнал по теме «{label}»."
            why_it_matters = "Это повышает предсказуемость выполнения задач роли в продакшн-среде."
        else:
            title = f"Validated working signal in “{label}”."
            why_it_matters = "This increases confidence in day-to-day execution for the target role."
        strength_items.append(
            {
                "title": title,
                "why_it_matters": why_it_matters,
                "evidence": [_build_evidence_item(topic)],
            }
        )

    gap_items: list[dict] = []
    for topic in gap_topics:
        label = str(topic.get("label") or "")
        outcome = str(topic.get("outcome") or "")
        if report_language == "ru":
            if outcome == "honest_gap":
                risk = "Есть честно признанный пробел: без практики по этой теме скорость входа в задачи будет ниже."
            elif outcome == "unverified_claim":
                risk = "Заявленный навык пока не подтверждён кейсом из практики, это риск для точности self-assessment."
            elif outcome == "evasive":
                risk = "Ответы по теме были уклончивыми, поэтому сложно подтвердить глубину владения."
            else:
                risk = "По теме не хватило глубины, чтобы уверенно подтвердить уровень."
            title = f"Зона роста: «{label}»."
        else:
            if outcome == "honest_gap":
                risk = "This is an explicit experience gap, so ramp-up risk is higher for related tasks."
            elif outcome == "unverified_claim":
                risk = "The claimed skill was not backed by a concrete example, which increases self-assessment risk."
            elif outcome == "evasive":
                risk = "Answers were evasive, so depth in this area could not be validated."
            else:
                risk = "Depth in this topic was not sufficient for confident validation."
            title = f"Growth area: “{label}”."
        gap_items.append(
            {
                "title": title,
                "risk": risk,
                "evidence": [_build_evidence_item(topic)],
            }
        )

    recommendation_items: list[dict] = []
    for idx, recommendation in enumerate(recommendations[:3]):
        linked_gap = gap_items[idx]["title"] if idx < len(gap_items) else ""
        if report_language == "ru":
            actions = [
                "Подготовьте один короткий кейс в формате: контекст → действие → результат.",
                "Добавьте 1-2 технических детали: выбор подхода, компромисс, проверка результата.",
            ]
            success_criteria = "На следующем интервью по теме получается дать конкретный пример и объяснить решение без общих формулировок."
        else:
            actions = [
                "Prepare one short case in context → action → result format.",
                "Add 1-2 technical details: decision trade-off and validation method.",
            ]
            success_criteria = "In the next interview you can explain a concrete case with clear decision logic and outcome."
        recommendation_items.append(
            {
                "title": recommendation,
                "linked_gap": linked_gap,
                "actions": actions,
                "success_criteria": success_criteria,
            }
        )

    penalty_explanations = [
        text
        for text in (_map_penalty_to_explanation(item, report_language) for item in penalties)
        if text
    ]
    penalty_explanations = list(dict.fromkeys(penalty_explanations))[:4]
    block_metrics = list(calibrated_scoring.get("block_metrics", []) or [])
    top_block_signals = [
        {
            "block": str(item.get("block") or ""),
            "score": round(_to_float(item.get("score"), 0.0), 2),
            "weight": round(_to_float(item.get("weight"), 0.0), 4),
            "question_count": int(item.get("question_count") or 0),
        }
        for item in sorted(block_metrics, key=lambda row: _to_float(row.get("weight"), 0.0), reverse=True)[:3]
    ]
    confidence_verdict = _confidence_verdict_band(overall_confidence)
    insufficient_signal = confidence_verdict != "normal"

    if report_language == "ru":
        if confidence_verdict == "insufficient_data":
            confidence_pct = int(round(_to_float(overall_confidence, 0.0) * 100))
            overall_text = (
                f"Итог: {_role_label(target_role, report_language)} получил {overall_score:.1f}/10. "
                f"Сигнал недостаточный (confidence {confidence_pct}%), поэтому жёсткий verdict по найму не выносится."
            )
        elif confidence_verdict == "needs_human_review":
            confidence_pct = int(round(_to_float(overall_confidence, 0.0) * 100))
            overall_text = (
                f"Итог: {_role_label(target_role, report_language)} получил {overall_score:.1f}/10. "
                f"Confidence {confidence_pct}%: нужен ручной review перед финальным решением по найму."
            )
        else:
            overall_text = (
                f"Итог: {_role_label(target_role, report_language)} получил {overall_score:.1f}/10 "
                f"с рекомендацией {_recommendation_label(hiring_recommendation, report_language)}. "
                "Оценка основана на подтверждённых ответах по темам интервью, а не на резюме."
            )
    else:
        if confidence_verdict == "insufficient_data":
            confidence_pct = int(round(_to_float(overall_confidence, 0.0) * 100))
            overall_text = (
                f"Final result: {_role_label(target_role, report_language)} scored {overall_score:.1f}/10. "
                f"Signal is insufficient (confidence {confidence_pct}%), so no hard hiring verdict is issued."
            )
        elif confidence_verdict == "needs_human_review":
            confidence_pct = int(round(_to_float(overall_confidence, 0.0) * 100))
            overall_text = (
                f"Final result: {_role_label(target_role, report_language)} scored {overall_score:.1f}/10. "
                f"Confidence {confidence_pct}% requires human review before a final hiring verdict."
            )
        else:
            overall_text = (
                f"Final result: { _role_label(target_role, report_language) } scored {overall_score:.1f}/10 "
                f"with recommendation {_recommendation_label(hiring_recommendation, report_language)}. "
                "The result is based on validated interview evidence, not resume claims alone."
            )

    return {
        "version": "2.0",
        "overall_assessment": {
            "summary": overall_text,
            "overall_score": round(_to_float(overall_score), 2),
            "recommendation": hiring_recommendation,
            "signal_quality": str(summary_model.get("signal_quality") or "unknown"),
            "overall_confidence": round(_to_float(overall_confidence), 3) if overall_confidence is not None else None,
            "insufficient_signal": insufficient_signal,
            "confidence_verdict": confidence_verdict,
            "score_method": "evidence_weighted_with_penalties",
        },
        "evidence_based_strengths": strength_items,
        "evidence_based_gaps": gap_items,
        "growth_recommendations": recommendation_items,
        "scoring_trace": {
            "pre_penalty_overall_score": round(_to_float(calibrated_scoring.get("pre_penalty_overall_score"), overall_score), 2),
            "post_penalty_overall_score": round(_to_float(calibrated_scoring.get("post_penalty_overall_score"), overall_score), 2),
            "penalty_explanations": penalty_explanations,
            "top_block_signals": top_block_signals,
        },
        "summary_strengths": strengths[:3],
        "summary_weaknesses": weaknesses[:3],
    }


def _apply_recommendation_gates(
    *,
    llm_rec: str,
    overall_score: float,
    summary_model: dict,
    answer_metrics: dict,
    confidence_metrics: dict,
    competency_scores: list[dict],
) -> tuple[str, list[str]]:
    """Clamp recommendation based on signal quality and evidence strength."""
    reasons: list[str] = []
    core_topics = int(summary_model.get("core_topics", 0) or 0)
    signal_quality = str(summary_model.get("signal_quality", "limited"))
    strong_topics = int(summary_model.get("strong_topics", 0) or 0)
    validated_topics = int(summary_model.get("validated_topics", 0) or 0)
    honest_gaps = int(summary_model.get("honest_gaps", 0) or 0)
    generic_topics = int(summary_model.get("generic_or_evasive_topics", 0) or 0)
    overall_confidence = _to_float(confidence_metrics.get("overall_confidence"), 0.0)
    confidence_verdict = _confidence_verdict_band(overall_confidence)

    recommendation_rank = {"no": 0, "maybe": 1, "yes": 2, "strong_yes": 3}
    max_allowed = "strong_yes"

    if confidence_verdict == "insufficient_data":
        reasons.append("overall confidence below 40%; signal is insufficient for a hard hire verdict")
        return "maybe", reasons
    if confidence_verdict == "needs_human_review":
        reasons.append("overall confidence below 70%; human review is required before hard hire verdict")
        return "maybe", reasons

    critical = [cs for cs in competency_scores if _to_float(cs.get("score"), 5.0) <= 4.0]
    if critical:
        max_allowed = min((max_allowed, "maybe"), key=lambda item: recommendation_rank[item])
        reasons.append("critical competency weakness blocks positive recommendation")

    if answer_metrics["short_answer_ratio"] > 0.3 or answer_metrics["avg_answer_quality"] < 4.5:
        max_allowed = min((max_allowed, "no"), key=lambda item: recommendation_rank[item])
        reasons.append("insufficient answer evidence blocks recommendation")
    elif signal_quality == "limited":
        max_allowed = min((max_allowed, "maybe"), key=lambda item: recommendation_rank[item])
        reasons.append("limited signal quality caps recommendation at maybe")

    if core_topics and honest_gaps >= max(2, core_topics // 2):
        max_allowed = min((max_allowed, "no"), key=lambda item: recommendation_rank[item])
        reasons.append("too many explicit experience gaps")

    if generic_topics >= max(2, core_topics // 2 or 1) and int(summary_model.get("validated_topics", 0) or 0) < max(2, core_topics // 3 or 1):
        max_allowed = min((max_allowed, "maybe"), key=lambda item: recommendation_rank[item])
        reasons.append("too many generic or evasive topic outcomes")

    if llm_rec == "strong_yes":
        if overall_score < 8.5 or overall_confidence < 0.7 or signal_quality != "high" or strong_topics < max(2, core_topics // 2 or 1):
            max_allowed = min((max_allowed, "yes"), key=lambda item: recommendation_rank[item])
            reasons.append("strong_yes requires strong validated signal")

    if llm_rec == "yes":
        strong_yes_structure = (
            signal_quality == "high"
            and validated_topics >= max(4, core_topics // 2 or 1)
            and generic_topics <= 1
            and honest_gaps == 0
        )
        if (
            (overall_score < 7.0 and not (strong_yes_structure and overall_score >= 6.8))
            or signal_quality == "limited"
            or overall_confidence < 0.55
        ):
            max_allowed = min((max_allowed, "maybe"), key=lambda item: recommendation_rank[item])
            reasons.append("yes requires stable medium-or-better evidence")

    final_rec = llm_rec
    if recommendation_rank[final_rec] > recommendation_rank[max_allowed]:
        final_rec = max_allowed

    return final_rec, reasons


def _apply_summary_penalties(
    aggregates: dict[str, float],
    summary_model: dict,
    confidence_metrics: dict,
) -> tuple[dict[str, float], list[str]]:
    """Reduce inflated scores when topic outcomes show weak validated evidence."""
    penalties: list[str] = []
    cap = 10.0

    core_topics = int(summary_model.get("core_topics", 0) or 0)
    validated_topics = int(summary_model.get("validated_topics", 0) or 0)
    unverified_claim_topics = int(summary_model.get("unverified_claim_topics", 0) or 0)
    honest_gaps = int(summary_model.get("honest_gaps", 0) or 0)
    signal_quality = str(summary_model.get("signal_quality", "limited"))
    strong_topics = int(summary_model.get("strong_topics", 0) or 0)
    overall_confidence = _to_float(confidence_metrics.get("overall_confidence"), 0.0)

    partial_topics = int(summary_model.get("partial_topics", 0) or 0)
    generic_topics = int(summary_model.get("generic_or_evasive_topics", 0) or 0)

    if validated_topics == 0:
        if (
            partial_topics >= max(5, core_topics - 2)
            and honest_gaps == 0
            and generic_topics <= 1
            and unverified_claim_topics <= 1
        ):
            cap = min(cap, 6.8)
            penalties.append("no_validated_topics_but_broad_relevant_partial_signal: capped_at_6.8")
        elif (
            partial_topics >= max(5, core_topics - 2)
            and honest_gaps == 0
            and generic_topics <= 2
            and unverified_claim_topics <= 2
        ):
            cap = min(cap, 6.2)
            penalties.append("no_validated_topics_but_stable_partial_signal: capped_at_6.2")
        elif partial_topics >= max(5, core_topics - 2) and honest_gaps == 0:
            cap = min(cap, 5.8)
            penalties.append("no_validated_topics_but_many_partial: capped_at_5.8")
        else:
            cap = min(cap, 4.5)
            penalties.append("no_validated_topics: capped_at_4.5")
    elif core_topics and validated_topics <= max(1, core_topics // 4):
        if strong_topics >= 1 and partial_topics >= max(4, core_topics // 2):
            cap = min(cap, 6.8)
            penalties.append("few_validated_but_broad_partial_signal: capped_at_6.8")
        else:
            cap = min(cap, 5.5)
            penalties.append("too_few_validated_topics: capped_at_5.5")
    elif validated_topics >= max(4, core_topics // 2 or 1) and signal_quality == "high" and honest_gaps == 0:
        cap = min(cap, 8.4)
        penalties.append("high_signal_with_many_validated_topics: capped_at_8.4")
    elif validated_topics >= max(3, core_topics // 2 or 1) and honest_gaps == 0:
        cap = min(cap, 7.8)
        penalties.append("multiple_validated_topics_allow_higher_cap: capped_at_7.8")

    if core_topics and unverified_claim_topics >= max(2, core_topics // 3):
        cap = min(cap, 5.5)
        penalties.append("many_unverified_claim_topics: capped_at_5.5")

    if core_topics and honest_gaps >= max(2, core_topics // 2):
        cap = min(cap, 5.0)
        penalties.append("many_honest_gaps: capped_at_5.0")

    if signal_quality == "limited":
        if (
            strong_topics >= 1
            and partial_topics >= max(4, core_topics // 2)
            and generic_topics <= 1
            and unverified_claim_topics <= 1
        ):
            cap = min(cap, 7.2)
            penalties.append("limited_signal_but_relevant_partial_depth: capped_at_7.2")
        elif strong_topics >= 1 and partial_topics >= max(4, core_topics // 2):
            cap = min(cap, 6.8)
            penalties.append("limited_signal_with_some_validated_depth: capped_at_6.8")
        else:
            cap = min(cap, 6.0)
            penalties.append("limited_signal_quality: capped_at_6.0")
    elif signal_quality == "medium" and validated_topics >= max(3, core_topics // 2 or 1):
        cap = min(cap, 7.8)
        penalties.append("medium_signal_with_multiple_validated_topics: capped_at_7.8")

    if overall_confidence < 0.45:
        cap = min(cap, 6.0)
        penalties.append("low_overall_confidence: capped_at_6.0")

    if strong_topics == 0 and validated_topics < 2 and core_topics >= 6:
        if partial_topics >= max(5, core_topics - 2) and honest_gaps == 0 and generic_topics <= 2:
            cap = min(cap, 6.4)
            penalties.append("no_strong_topics_but_broad_partial_signal: capped_at_6.4")
        else:
            cap = min(cap, 6.0)
            penalties.append("no_strong_topics: capped_at_6.0")

    if cap < 10.0:
        return {k: round(min(v, cap), 1) for k, v in aggregates.items()}, penalties
    return aggregates, penalties


def _is_generic_feedback(text: str) -> bool:
    normalized = text.strip().lower()
    if not normalized:
        return True
    generic_markers = (
        "завершил полное структурированное собеседование",
        "ответы могут включать более конкретные метрики",
        "используйте формат star",
        "completed the full structured interview",
        "answers may include more concrete metrics",
        "use the star format",
    )
    return any(marker in normalized for marker in generic_markers)


def _build_outcome_feedback(summary_model: dict, report_language: str) -> tuple[list[str], list[str], list[str]]:
    topic_outcomes = list(summary_model.get("topic_outcomes", []) or [])
    validated_topics = int(summary_model.get("validated_topics", 0) or 0)
    strong_topics = int(summary_model.get("strong_topics", 0) or 0)
    honest_gaps = int(summary_model.get("honest_gaps", 0) or 0)
    unverified_claim_topics = int(summary_model.get("unverified_claim_topics", 0) or 0)
    evasive_topics = int(summary_model.get("evasive_topics", 0) or 0)
    partial_topics = int(summary_model.get("partial_topics", 0) or 0)

    def items_for(outcome: str) -> list[dict]:
        return [item for item in topic_outcomes if item.get("outcome") == outcome][:3]

    def labels_for(outcome: str) -> list[str]:
        return [str(item.get("label")) for item in items_for(outcome)]

    def example_for(outcome: str) -> str | None:
        for item in items_for(outcome):
            hint = str(item.get("evidence_hint") or "").strip()
            if hint:
                return hint
        return None

    if report_language == "ru":
        strengths: list[str] = []
        weaknesses: list[str] = []
        recommendations: list[str] = []
        validated_labels = labels_for("validated")
        partial_labels = labels_for("partial")
        honest_gap_labels = labels_for("honest_gap")
        unverified_labels = labels_for("unverified_claim")
        evasive_labels = labels_for("evasive")
        validated_example = example_for("validated")
        partial_example = example_for("partial")

        if strong_topics > 0:
            text = (
                "Сильные ответы с практической конкретикой прозвучали по темам: "
                + ", ".join(validated_labels[: max(1, min(3, len(validated_labels)))])
                + "."
            )
            if validated_example:
                text += f" Например: {validated_example}"
            strengths.append(text)
        elif validated_topics > 0:
            text = (
                "Удалось подтвердить практический опыт по темам: "
                + ", ".join(validated_labels[: max(1, min(3, len(validated_labels)))])
                + "."
            )
            if validated_example:
                text += f" Например: {validated_example}"
            strengths.append(text)
        elif partial_topics > 0 and partial_labels:
            if honest_gaps >= max(2, len(topic_outcomes) // 2 or 1):
                strengths.append(
                    "Есть только базовый сигнал по отдельным темам: "
                    + ", ".join(partial_labels[: max(1, min(2, len(partial_labels)))])
                    + "."
                )
            else:
                text = (
                    "Есть содержательная база по темам: "
                    + ", ".join(partial_labels[: max(1, min(3, len(partial_labels)))])
                    + "."
                )
                if partial_example:
                    text += f" Например: {partial_example}"
                strengths.append(text)

        if honest_gaps > 0:
            label_tail = f" ({', '.join(honest_gap_labels)})" if honest_gap_labels else ""
            weaknesses.append(f"По {honest_gaps} темам кандидат честно обозначил пробелы в опыте{label_tail}.")
            recommendations.append("Сфокусируйтесь на темах, где опыта пока не было, и подготовьте базовые рабочие кейсы.")

        if unverified_claim_topics > 0:
            label_tail = f" ({', '.join(unverified_labels)})" if unverified_labels else ""
            weaknesses.append(
                f"По {unverified_claim_topics} заявленным технологиям не удалось подтвердить реальный hands-on опыт{label_tail}."
            )
            recommendations.append("Если технология указана в резюме, подготовьте один конкретный пример использования: задача, решение и результат.")

        if evasive_topics > 0:
            label_tail = f" ({', '.join(evasive_labels)})" if evasive_labels else ""
            weaknesses.append(f"По {evasive_topics} темам ответы оставались уклончивыми или слишком общими{label_tail}.")
            recommendations.append("На технических вопросах отвечайте через конкретный кейс: контекст, ваши действия, trade-off и итог.")

        if partial_topics > 0 and len(recommendations) < 3:
            recommendations.append("Добавляйте больше деталей уровня implementation: как именно работало решение и почему выбрали именно его.")

        if partial_topics > 0 and partial_labels:
            text = (
                "Часть тем раскрыта на рабочем, но не глубоком уровне: "
                + ", ".join(partial_labels[: max(1, min(3, len(partial_labels)))])
                + "."
            )
            if partial_example:
                text += f" Пример ответа: {partial_example}"
            weaknesses.append(text)

        return strengths[:3], weaknesses[:3], recommendations[:3]

    strengths = []
    weaknesses = []
    recommendations = []
    validated_labels = labels_for("validated")
    partial_labels = labels_for("partial")
    honest_gap_labels = labels_for("honest_gap")
    unverified_labels = labels_for("unverified_claim")
    evasive_labels = labels_for("evasive")
    validated_example = example_for("validated")
    partial_example = example_for("partial")
    if strong_topics > 0:
        text = (
            "Strong, concrete answers were demonstrated in topics such as "
            + ", ".join(validated_labels[: max(1, min(3, len(validated_labels)))])
            + "."
        )
        if validated_example:
            text += f" Example: {validated_example}"
        strengths.append(text)
    elif validated_topics > 0:
        text = (
            "Hands-on experience was validated in topics such as "
            + ", ".join(validated_labels[: max(1, min(3, len(validated_labels)))])
            + "."
        )
        if validated_example:
            text += f" Example: {validated_example}"
        strengths.append(text)
    elif partial_topics > 0 and partial_labels:
        if honest_gaps >= max(2, len(topic_outcomes) // 2 or 1):
            strengths.append(
                "Only a limited baseline signal appeared in topics such as "
                + ", ".join(partial_labels[: max(1, min(2, len(partial_labels)))])
                + "."
            )
        else:
            text = (
                "The interview still showed a meaningful baseline in topics such as "
                + ", ".join(partial_labels[: max(1, min(3, len(partial_labels)))])
                + "."
            )
            if partial_example:
                text += f" Example: {partial_example}"
            strengths.append(text)
    if honest_gaps > 0:
        label_tail = f" ({', '.join(honest_gap_labels)})" if honest_gap_labels else ""
        weaknesses.append(f"The candidate explicitly acknowledged experience gaps in {honest_gaps} topics{label_tail}.")
        recommendations.append("Prepare short real-world examples for topics where hands-on experience is still limited.")
    if unverified_claim_topics > 0:
        label_tail = f" ({', '.join(unverified_labels)})" if unverified_labels else ""
        weaknesses.append(
            f"Real hands-on experience could not be validated for {unverified_claim_topics} claimed technologies{label_tail}."
        )
        recommendations.append("For each resume claim, prepare one concrete example with task, implementation, and outcome.")
    if evasive_topics > 0:
        label_tail = f" ({', '.join(evasive_labels)})" if evasive_labels else ""
        weaknesses.append(f"Answers stayed generic or evasive in {evasive_topics} topics{label_tail}.")
        recommendations.append("Use concrete implementation details, trade-offs, and outcomes instead of general statements.")
    if partial_topics > 0 and len(recommendations) < 3:
        recommendations.append("Add more implementation-level detail to otherwise decent answers.")
    if partial_topics > 0 and partial_labels:
        text = (
            "Several topics stayed at a workable but not yet deep level: "
            + ", ".join(partial_labels[: max(1, min(3, len(partial_labels)))])
            + "."
        )
        if partial_example:
            text += f" Example answer: {partial_example}"
        weaknesses.append(text)
    return strengths[:3], weaknesses[:3], recommendations[:3]


def _prefer_outcome_feedback(
    current_items: list[str],
    generated_items: list[str],
) -> list[str]:
    generated_items = [item for item in generated_items if item and not _is_generic_feedback(item)]
    if not generated_items:
        return [item for item in current_items if item and not _is_generic_feedback(item)]
    if not current_items:
        return generated_items
    specific_current = [item for item in current_items if not _is_generic_feedback(item)]
    if not specific_current:
        return generated_items
    merged: list[str] = []
    for item in [*generated_items, *specific_current]:
        if item and item not in merged:
            merged.append(item)
    return merged[:3]


def _compute_answer_metrics(
    per_question_analysis: list[dict],
    message_history: list[dict],
) -> dict:
    """Compute answer quality metrics used for penalization logic.

    Returns answer_quality_score, depth_score, and generated red flags
    derived from per-question Pass 1 data and raw word counts.
    """
    word_counts = [
        len(str(msg.get("content", "")).split())
        for msg in message_history
        if msg["role"] == "candidate"
    ]
    short_count = sum(1 for w in word_counts if w < 10)
    short_ratio = round(short_count / len(word_counts), 2) if word_counts else 0.0
    avg_words = round(sum(word_counts) / len(word_counts), 1) if word_counts else 0.0

    quality_scores = [
        _to_float(q.get("answer_quality"), 5.0) for q in per_question_analysis
    ]
    avg_quality = round(sum(quality_scores) / len(quality_scores), 2) if quality_scores else 5.0

    specificity_vals = [str(q.get("specificity", "low")) for q in per_question_analysis]
    low_spec_ratio = round(
        specificity_vals.count("low") / len(specificity_vals), 2
    ) if specificity_vals else 0.0

    depth_order = {"none": 0, "surface": 1, "adequate": 2, "strong": 3, "expert": 4}
    depth_vals = [str(q.get("depth", "surface")) for q in per_question_analysis]
    depth_nums = [depth_order.get(d, 1) for d in depth_vals]
    avg_depth_num = sum(depth_nums) / len(depth_nums) if depth_nums else 1.0
    depth_score_10 = round((avg_depth_num / 4.0) * 10, 1)

    red_flags: list[str] = []
    if short_ratio > 0.3:
        red_flags.append("answers too short")
    if low_spec_ratio > 0.5:
        red_flags.append("answers too generic")
    if avg_quality < 4.5:
        red_flags.append("lack of technical depth")
    surface_none = depth_vals.count("surface") + depth_vals.count("none")
    if depth_vals and surface_none / len(depth_vals) > 0.5:
        if "answers too generic" not in red_flags:
            red_flags.append("no real-world examples")

    # Check for evasion / repetition patterns in LLM-generated red flags
    llm_flags_text = " ".join(
        str(f) for q in per_question_analysis for f in q.get("red_flags", [])
    ).lower()
    if "evad" in llm_flags_text or "avoid" in llm_flags_text:
        red_flags.append("unclear understanding")
    if "repeat" in llm_flags_text or "same" in llm_flags_text:
        red_flags.append("answers seem repeated")

    return {
        "answer_quality_score": round(avg_quality, 1),
        "depth_score": depth_score_10,
        "short_answer_ratio": short_ratio,
        "low_specificity_ratio": low_spec_ratio,
        "avg_word_count": avg_words,
        "avg_answer_quality": avg_quality,
        "generated_red_flags": red_flags,
    }


_SYSTEM_DESIGN_STAGE_WEIGHTS = {
    "requirements": 0.3,
    "high_level_design": 0.4,
    "tradeoffs": 0.3,
}

_SYSTEM_DESIGN_STAGE_KEYWORDS = {
    "requirements": (
        "sla",
        "latency",
        "throughput",
        "qps",
        "rps",
        "traffic",
        "consistency",
        "availability",
        "retention",
        "auth",
        "integration",
        "constraint",
        "users",
        "tenant",
    ),
    "high_level_design": (
        "api",
        "gateway",
        "service",
        "worker",
        "queue",
        "kafka",
        "cache",
        "redis",
        "database",
        "postgres",
        "shard",
        "partition",
        "replica",
        "load balancer",
        "cdn",
        "websocket",
        "storage",
    ),
    "tradeoffs": (
        "trade-off",
        "tradeoff",
        "компром",
        "latency",
        "throughput",
        "consistency",
        "availability",
        "cost",
        "bottleneck",
        "failure",
        "retry",
        "timeout",
        "circuit breaker",
        "idempot",
        "observability",
        "monitoring",
        "p95",
        "p99",
        "degrad",
        "scale",
    ),
}

_SYSTEM_DESIGN_RELIABILITY_KEYWORDS = (
    "availability",
    "consistency",
    "retry",
    "timeout",
    "idempot",
    "failover",
    "replica",
    "replication",
    "monitoring",
    "observability",
    "p95",
    "p99",
    "latency",
    "throughput",
    "autoscal",
    "degrad",
    "backpressure",
    "bottleneck",
)

_CODING_TASK_STAGE_WEIGHTS = {
    "task_brief": 0.25,
    "implementation": 0.45,
    "review": 0.30,
}

_CODING_TASK_STAGE_KEYWORDS = {
    "task_brief": (
        "input",
        "output",
        "constraint",
        "edge",
        "case",
        "complexity",
        "latency",
        "validation",
        "error",
        "invalid",
    ),
    "implementation": (
        "function",
        "return",
        "class",
        "loop",
        "dict",
        "map",
        "set",
        "queue",
        "cache",
        "state",
        "sort",
        "filter",
        "async",
        "await",
        "if ",
        "for ",
        "while ",
    ),
    "review": (
        "test",
        "assert",
        "edge",
        "case",
        "complexity",
        "o(",
        "refactor",
        "failure",
        "retry",
        "timeout",
        "bug",
        "coverage",
    ),
}

_CODING_TASK_CODE_HINTS = (
    "def ",
    "function ",
    "const ",
    "let ",
    "return ",
    "class ",
    "=>",
    "if (",
    "for (",
    "while (",
    "{",
    "}",
    "```",
)

_CODING_TASK_DEFAULT_COVERAGE_CHECKS = (
    {
        "check_key": "core_state_logic",
        "title_en": "Defines explicit state or data-flow logic",
        "title_ru": "Определяет явную state/data-flow логику",
        "stage_key": "implementation",
        "patterns": ("dict", "map", "queue", "state", "class", "cache", "return"),
        "required_hits": 2,
    },
    {
        "check_key": "decision_branching",
        "title_en": "Implements clear decision branches",
        "title_ru": "Реализует явные ветки принятия решения",
        "stage_key": "implementation",
        "patterns": ("if ", "else", "invalid", "error", "allow", "reject", "return false"),
        "required_hits": 2,
    },
    {
        "check_key": "test_edge_cases",
        "title_en": "Covers tests and edge cases",
        "title_ru": "Покрывает тесты и edge cases",
        "stage_key": "review",
        "patterns": ("test", "assert", "edge", "case", "boundary", "coverage", "complexity"),
        "required_hits": 2,
    },
)

_CODING_TASK_SCENARIO_COVERAGE_CHECKS = {
    "rate_limiter_window_counter": (
        {
            "check_key": "input_validation",
            "title_en": "Handles input and timestamp validation",
            "title_ru": "Обрабатывает валидацию входов и timestamp",
            "stage_key": "task_brief",
            "patterns": ("validate", "user_id", "timestamp", "invalid", "empty"),
            "required_hits": 2,
        },
        {
            "check_key": "expired_window_cleanup",
            "title_en": "Evicts expired entries from the active window",
            "title_ru": "Удаляет истёкшие элементы из активного окна",
            "stage_key": "implementation",
            "patterns": ("popleft", "queue[0]", "window", "expire", "while queue"),
            "required_hits": 2,
        },
        {
            "check_key": "limit_enforcement",
            "title_en": "Rejects requests when the limit is reached",
            "title_ru": "Отклоняет запросы при достижении лимита",
            "stage_key": "implementation",
            "patterns": ("limit", "len(queue)", "return false", ">= limit", "allow_request"),
            "required_hits": 2,
        },
        {
            "check_key": "test_boundary_cases",
            "title_en": "Mentions boundary and repeated-request tests",
            "title_ru": "Упоминает boundary- и repeated-request тесты",
            "stage_key": "review",
            "patterns": ("boundary", "timestamp", "repeated", "same second", "test"),
            "required_hits": 2,
        },
    ),
}

_CODING_TASK_SCENARIO_STACK_CHECKS = {
    "rate_limiter_window_counter": (
        {
            "check_key": "backend_service_boundaries",
            "title_en": "Shows backend handler/service boundaries",
            "title_ru": "Показывает backend-границы handler/service",
            "stage_key": "implementation",
            "patterns": ("fastapi", "endpoint", "middleware", "service", "handler", "pydantic", "request", "response"),
            "required_hits": 2,
        },
        {
            "check_key": "backend_async_reliability",
            "title_en": "Mentions async or reliability concerns for backend integration",
            "title_ru": "Учитывает async или reliability-аспекты backend-интеграции",
            "stage_key": "review",
            "patterns": ("async", "await", "redis", "concurrency", "race", "timeout", "429", "retry", "test"),
            "required_hits": 2,
        },
    ),
    "async_search_state_manager": (
        {
            "check_key": "frontend_state_model",
            "title_en": "Shows React-style state and transition thinking",
            "title_ru": "Показывает React-style подход к state и transition",
            "stage_key": "implementation",
            "patterns": ("react", "hook", "usestate", "reducer", "state", "loading", "error", "query"),
            "required_hits": 2,
        },
        {
            "check_key": "frontend_stale_response_control",
            "title_en": "Handles cancellation and stale-response UX",
            "title_ru": "Обрабатывает cancelation и stale-response UX",
            "stage_key": "review",
            "patterns": ("abort", "cancel", "stale", "debounce", "effect", "spinner", "empty state", "retry"),
            "required_hits": 2,
        },
    ),
    "flaky_test_classifier": (
        {
            "check_key": "qa_assertion_strategy",
            "title_en": "Shows test assertions, fixtures, or automation structure",
            "title_ru": "Показывает assertions, fixtures или структуру automation",
            "stage_key": "implementation",
            "patterns": ("pytest", "fixture", "assert", "parametrize", "playwright", "test case", "spec"),
            "required_hits": 2,
        },
        {
            "check_key": "qa_ci_diagnostics",
            "title_en": "Explains CI diagnostics and flaky-test evidence",
            "title_ru": "Объясняет CI diagnostics и evidence по flaky-тестам",
            "stage_key": "review",
            "patterns": ("ci", "artifact", "trace", "report", "rerun", "history", "screenshot", "diagnostic"),
            "required_hits": 2,
        },
    ),
    "deployment_rollout_guard": (
        {
            "check_key": "ops_health_thresholds",
            "title_en": "Defines rollout health thresholds and rollback triggers",
            "title_ru": "Определяет rollout thresholds и rollback triggers",
            "stage_key": "implementation",
            "patterns": ("latency", "error rate", "slo", "threshold", "rollback", "pause", "continue", "canary"),
            "required_hits": 2,
        },
        {
            "check_key": "ops_observability_signals",
            "title_en": "Uses observability and event signals in the decision path",
            "title_ru": "Использует observability и event signals в decision path",
            "stage_key": "review",
            "patterns": ("metric", "alert", "event", "monitor", "dashboard", "trace", "burn rate", "pager"),
            "required_hits": 2,
        },
    ),
    "feature_freshness_monitor": (
        {
            "check_key": "data_validation_thresholds",
            "title_en": "Defines concrete data-validation thresholds and fallbacks",
            "title_ru": "Задаёт конкретные пороги data-validation и fallback",
            "stage_key": "implementation",
            "patterns": ("threshold", "freshness", "null", "fallback", "stale", "feature", "block", "allow"),
            "required_hits": 2,
        },
        {
            "check_key": "data_pipeline_reasoning",
            "title_en": "Explains how the logic fits into a scoring pipeline",
            "title_ru": "Объясняет, как логика встроится в scoring pipeline",
            "stage_key": "review",
            "patterns": ("pipeline", "batch", "stream", "latency", "monitor", "backfill", "scoring"),
            "required_hits": 2,
        },
    ),
    "experiment_guardrail_parser": (
        {
            "check_key": "product_decision_rules",
            "title_en": "Shows explicit rollout decision rules",
            "title_ru": "Показывает явные rollout decision rules",
            "stage_key": "implementation",
            "patterns": ("guardrail", "metric", "threshold", "rollout", "launch", "block", "decision"),
            "required_hits": 2,
        },
        {
            "check_key": "product_payload_shape",
            "title_en": "Defines a structured output payload for decision makers",
            "title_ru": "Определяет структурированный output payload для decision makers",
            "stage_key": "review",
            "patterns": ("payload", "owner", "reason", "recommendation", "status", "invalid", "summary"),
            "required_hits": 2,
        },
    ),
    "offline_sync_queue": (
        {
            "check_key": "mobile_sync_state",
            "title_en": "Shows offline sync state and conflict markers",
            "title_ru": "Показывает состояние offline sync и conflict markers",
            "stage_key": "implementation",
            "patterns": ("queue", "sync", "conflict", "retry", "batch", "offline", "reconnect", "marker"),
            "required_hits": 2,
        },
        {
            "check_key": "mobile_failure_battery_tradeoffs",
            "title_en": "Explains battery or retry trade-offs for mobile behavior",
            "title_ru": "Объясняет battery/retry trade-offs для mobile-поведения",
            "stage_key": "review",
            "patterns": ("battery", "background", "backoff", "network", "latency", "retry", "flush"),
            "required_hits": 2,
        },
    ),
    "design_token_transformer": (
        {
            "check_key": "design_token_schema",
            "title_en": "Defines token schema and validation rules",
            "title_ru": "Определяет схему токенов и правила валидации",
            "stage_key": "implementation",
            "patterns": ("token", "alias", "schema", "validate", "required", "platform", "transform"),
            "required_hits": 2,
        },
        {
            "check_key": "design_handoff_outputs",
            "title_en": "Explains platform outputs and actionable errors",
            "title_ru": "Объясняет platform outputs и понятные ошибки",
            "stage_key": "review",
            "patterns": ("ios", "android", "web", "error", "output", "handoff", "theme"),
            "required_hits": 2,
        },
    ),
}

_SQL_LIVE_STAGE_WEIGHTS = {
    "schema_review": 0.25,
    "query_authoring": 0.45,
    "result_review": 0.30,
}

_SQL_LIVE_STAGE_KEYWORDS = {
    "schema_review": (
        "table",
        "join",
        "filter",
        "group",
        "aggregate",
        "customer",
        "orders",
        "status",
        "date",
        "march",
        "active",
    ),
    "query_authoring": (
        "select",
        "from",
        "join",
        "where",
        "group by",
        "having",
        "order by",
        "sum(",
        "count(",
        "completed",
    ),
    "result_review": (
        "validate",
        "check",
        "result",
        "duplicate",
        "null",
        "index",
        "performance",
        "explain",
        "test",
        "sort",
    ),
}

_SQL_LIVE_QUERY_HINTS = (
    "select ",
    "from ",
    "join ",
    "where ",
    "group by",
    "order by",
    "having ",
    "with ",
)

_WRITTEN_COMMUNICATION_STAGE_WEIGHTS = {
    "brief_alignment": 0.25,
    "drafting": 0.45,
    "editing": 0.30,
}

_WRITTEN_COMMUNICATION_STAGE_KEYWORDS = {
    "brief_alignment": (
        "audience",
        "stakeholder",
        "decision",
        "goal",
        "impact",
        "context",
        "ask",
        "reader",
        "tone",
        "summary",
    ),
    "drafting": (
        "update",
        "status",
        "risk",
        "next step",
        "owner",
        "plan",
        "mitigation",
        "because",
        "paragraph",
        "message",
    ),
    "editing": (
        "clarity",
        "rewrite",
        "shorten",
        "tone",
        "ambiguous",
        "explicit",
        "headline",
        "opening",
        "next step",
        "action",
    ),
}

_WRITTEN_COMMUNICATION_CLARITY_HINTS = (
    "because",
    "therefore",
    "next step",
    "action",
    "owner",
    "deadline",
    "impact",
    "status",
    "решение",
    "следующий",
    "статус",
    "влияние",
    "дальше",
)

_WRITTEN_COMMUNICATION_AUDIENCE_HINTS = (
    "audience",
    "reader",
    "leadership",
    "stakeholder",
    "customer",
    "support",
    "engineering",
    "product",
    "manager",
    "команда",
    "стейкхолдер",
    "руковод",
    "клиент",
    "поддержк",
)

_BEHAVIORAL_INTERVIEW_STAGE_WEIGHTS = {
    "ownership": 0.28,
    "collaboration": 0.24,
    "leadership": 0.28,
    "reflection": 0.20,
}

_BEHAVIORAL_INTERVIEW_STAGE_KEYWORDS = {
    "ownership": (
        "decision",
        "decide",
        "owned",
        "ownership",
        "scope",
        "ambigu",
        "risk",
        "trade-off",
        "initiative",
        "responsib",
        "реш",
        "взял",
        "риск",
        "неяс",
        "ответствен",
    ),
    "collaboration": (
        "team",
        "stakeholder",
        "partner",
        "conflict",
        "tension",
        "align",
        "alignment",
        "feedback",
        "communicat",
        "support",
        "команд",
        "стейк",
        "напряж",
        "соглас",
        "обратн",
    ),
    "leadership": (
        "influence",
        "clarity",
        "priorit",
        "decision",
        "coach",
        "delegate",
        "direction",
        "alignment",
        "pressure",
        "authority",
        "влиял",
        "ясност",
        "приоритет",
        "направл",
        "давлен",
    ),
    "reflection": (
        "learn",
        "learned",
        "would",
        "next time",
        "changed",
        "feedback",
        "mistake",
        "retrospective",
        "improve",
        "habit",
        "понял",
        "измен",
        "ошиб",
        "обратн",
        "улучш",
    ),
}

_BEHAVIORAL_INTERVIEW_COLLABORATION_HINTS = (
    "stakeholder",
    "team",
    "partner",
    "alignment",
    "align",
    "conflict",
    "feedback",
    "support",
    "customer",
    "cross-functional",
    "команд",
    "стейк",
    "соглас",
    "конфликт",
    "поддерж",
)

_BEHAVIORAL_INTERVIEW_LEADERSHIP_HINTS = (
    "decision",
    "clarity",
    "influence",
    "priorit",
    "direction",
    "coach",
    "delegate",
    "pressure",
    "authority",
    "aligned",
    "реш",
    "ясност",
    "влиял",
    "приоритет",
    "давлен",
)

_BEHAVIORAL_INTERVIEW_REFLECTION_HINTS = (
    "learn",
    "learned",
    "changed",
    "would do differently",
    "next time",
    "feedback",
    "mistake",
    "improve",
    "habit",
    "rule",
    "понял",
    "измен",
    "иначе",
    "ошиб",
    "улучш",
)

_SQL_LIVE_SCENARIO_VALIDATION_DEFS = {
    "customer_revenue_rollup": {
        "schema_statements": (
            """
            CREATE TABLE customers (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                is_active INTEGER NOT NULL
            );
            """,
            """
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                customer_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                total_amount REAL NOT NULL,
                created_at TEXT NOT NULL
            );
            """,
        ),
        "seed_statements": (
            "INSERT INTO customers (id, name, is_active) VALUES (1, 'Alice', 1);",
            "INSERT INTO customers (id, name, is_active) VALUES (2, 'Bob', 1);",
            "INSERT INTO customers (id, name, is_active) VALUES (3, 'Carol', 0);",
            "INSERT INTO customers (id, name, is_active) VALUES (4, 'Dana', 1);",
            "INSERT INTO orders (id, customer_id, status, total_amount, created_at) VALUES (1, 1, 'completed', 120, '2024-03-05');",
            "INSERT INTO orders (id, customer_id, status, total_amount, created_at) VALUES (2, 1, 'completed', 80, '2024-03-18');",
            "INSERT INTO orders (id, customer_id, status, total_amount, created_at) VALUES (3, 1, 'pending', 40, '2024-03-20');",
            "INSERT INTO orders (id, customer_id, status, total_amount, created_at) VALUES (4, 1, 'completed', 50, '2024-02-27');",
            "INSERT INTO orders (id, customer_id, status, total_amount, created_at) VALUES (5, 2, 'completed', 60, '2024-03-09');",
            "INSERT INTO orders (id, customer_id, status, total_amount, created_at) VALUES (6, 2, 'completed', 40, '2024-03-11');",
            "INSERT INTO orders (id, customer_id, status, total_amount, created_at) VALUES (7, 2, 'refunded', 25, '2024-03-14');",
            "INSERT INTO orders (id, customer_id, status, total_amount, created_at) VALUES (8, 3, 'completed', 500, '2024-03-12');",
            "INSERT INTO orders (id, customer_id, status, total_amount, created_at) VALUES (9, 4, 'completed', 110, '2024-03-21');",
            "INSERT INTO orders (id, customer_id, status, total_amount, created_at) VALUES (10, 4, 'completed', 20, '2024-04-02');",
            "INSERT INTO orders (id, customer_id, status, total_amount, created_at) VALUES (11, 4, 'pending', 70, '2024-03-25');",
        ),
        "expected_columns": ("customer_name", "completed_order_count", "completed_revenue"),
        "expected_rows": (
            ("Alice", 2, 200.0),
            ("Dana", 1, 110.0),
            ("Bob", 2, 100.0),
        ),
        "check_defs": (
            {
                "check_key": "query_is_select_only",
                "title_en": "Uses a single SELECT-style query",
                "title_ru": "Использует один SELECT-style запрос",
            },
            {
                "check_key": "query_executes",
                "title_en": "Executes successfully against the sandbox dataset",
                "title_ru": "Успешно выполняется на sandbox dataset",
            },
            {
                "check_key": "expected_columns",
                "title_en": "Returns the expected output columns",
                "title_ru": "Возвращает ожидаемые колонки результата",
            },
            {
                "check_key": "expected_rows",
                "title_en": "Returns the expected result rows in the required order",
                "title_ru": "Возвращает ожидаемые строки в нужном порядке",
            },
        ),
    },
    "signup_funnel_rollup": {
        "schema_statements": (
            """
            CREATE TABLE signup_events (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                event_date TEXT NOT NULL
            );
            """,
        ),
        "seed_statements": (
            "INSERT INTO signup_events (id, user_id, event_type, event_date) VALUES (1, 101, 'started', '2024-04-01');",
            "INSERT INTO signup_events (id, user_id, event_type, event_date) VALUES (2, 102, 'started', '2024-04-01');",
            "INSERT INTO signup_events (id, user_id, event_type, event_date) VALUES (3, 103, 'started', '2024-04-01');",
            "INSERT INTO signup_events (id, user_id, event_type, event_date) VALUES (4, 104, 'started', '2024-04-01');",
            "INSERT INTO signup_events (id, user_id, event_type, event_date) VALUES (5, 101, 'verified', '2024-04-01');",
            "INSERT INTO signup_events (id, user_id, event_type, event_date) VALUES (6, 102, 'verified', '2024-04-01');",
            "INSERT INTO signup_events (id, user_id, event_type, event_date) VALUES (7, 104, 'verified', '2024-04-01');",
            "INSERT INTO signup_events (id, user_id, event_type, event_date) VALUES (8, 201, 'started', '2024-04-02');",
            "INSERT INTO signup_events (id, user_id, event_type, event_date) VALUES (9, 202, 'started', '2024-04-02');",
            "INSERT INTO signup_events (id, user_id, event_type, event_date) VALUES (10, 203, 'started', '2024-04-02');",
            "INSERT INTO signup_events (id, user_id, event_type, event_date) VALUES (11, 201, 'verified', '2024-04-02');",
            "INSERT INTO signup_events (id, user_id, event_type, event_date) VALUES (12, 301, 'started', '2024-04-03');",
            "INSERT INTO signup_events (id, user_id, event_type, event_date) VALUES (13, 302, 'started', '2024-04-03');",
            "INSERT INTO signup_events (id, user_id, event_type, event_date) VALUES (14, 301, 'verified', '2024-04-03');",
        ),
        "expected_columns": ("event_date", "started_users", "verified_users", "verified_rate"),
        "expected_rows": (
            ("2024-04-01", 4, 3, 0.75),
            ("2024-04-02", 3, 1, 0.3333),
        ),
        "check_defs": (
            {
                "check_key": "query_is_select_only",
                "title_en": "Uses a single SELECT-style query",
                "title_ru": "Использует один SELECT-style запрос",
            },
            {
                "check_key": "query_executes",
                "title_en": "Executes successfully against the signup-event sandbox",
                "title_ru": "Успешно выполняется на sandbox signup events",
            },
            {
                "check_key": "expected_columns",
                "title_en": "Returns the requested funnel columns",
                "title_ru": "Возвращает запрошенные колонки funnel-отчёта",
            },
            {
                "check_key": "expected_rows",
                "title_en": "Returns the expected daily funnel rows and conversion values",
                "title_ru": "Возвращает ожидаемые дневные funnel-строки и conversion values",
            },
        ),
    },
    "incident_error_budget_audit": {
        "schema_statements": (
            """
            CREATE TABLE service_daily_metrics (
                id INTEGER PRIMARY KEY,
                service_name TEXT NOT NULL,
                metric_date TEXT NOT NULL,
                error_rate REAL NOT NULL
            );
            """,
        ),
        "seed_statements": (
            "INSERT INTO service_daily_metrics (id, service_name, metric_date, error_rate) VALUES (1, 'auth', '2024-04-01', 0.012);",
            "INSERT INTO service_daily_metrics (id, service_name, metric_date, error_rate) VALUES (2, 'auth', '2024-04-02', 0.021);",
            "INSERT INTO service_daily_metrics (id, service_name, metric_date, error_rate) VALUES (3, 'auth', '2024-04-03', 0.011);",
            "INSERT INTO service_daily_metrics (id, service_name, metric_date, error_rate) VALUES (4, 'payments', '2024-04-01', 0.015);",
            "INSERT INTO service_daily_metrics (id, service_name, metric_date, error_rate) VALUES (5, 'payments', '2024-04-02', 0.004);",
            "INSERT INTO service_daily_metrics (id, service_name, metric_date, error_rate) VALUES (6, 'payments', '2024-04-03', 0.013);",
            "INSERT INTO service_daily_metrics (id, service_name, metric_date, error_rate) VALUES (7, 'search', '2024-04-01', 0.009);",
            "INSERT INTO service_daily_metrics (id, service_name, metric_date, error_rate) VALUES (8, 'search', '2024-04-02', 0.014);",
            "INSERT INTO service_daily_metrics (id, service_name, metric_date, error_rate) VALUES (9, 'search', '2024-04-03', 0.008);",
        ),
        "expected_columns": ("service_name", "breach_days", "max_error_rate"),
        "expected_rows": (
            ("auth", 3, 0.021),
            ("payments", 2, 0.015),
        ),
        "check_defs": (
            {
                "check_key": "query_is_select_only",
                "title_en": "Uses a single SELECT-style query",
                "title_ru": "Использует один SELECT-style запрос",
            },
            {
                "check_key": "query_executes",
                "title_en": "Executes successfully against the service-metrics sandbox",
                "title_ru": "Успешно выполняется на sandbox service metrics",
            },
            {
                "check_key": "expected_columns",
                "title_en": "Returns the requested audit columns",
                "title_ru": "Возвращает запрошенные колонки audit-отчёта",
            },
            {
                "check_key": "expected_rows",
                "title_en": "Returns the expected breached services in the required order",
                "title_ru": "Возвращает ожидаемые сервисы с breach в нужном порядке",
            },
        ),
    },
}

_CODING_TASK_RUNNER_TIMEOUT_SECONDS = 2.0
_SQL_LIVE_VALIDATION_TIMEOUT_SECONDS = 2.0

_CODING_TASK_RUNNER_CHECK_DEFS = {
    "rate_limiter_window_counter": (
        {
            "check_key": "runner_allows_within_limit",
            "title_en": "Allows requests while the user stays within the limit",
            "title_ru": "Разрешает запросы, пока пользователь не превысил лимит",
        },
        {
            "check_key": "runner_blocks_over_limit",
            "title_en": "Blocks the request after the sliding-window limit is reached",
            "title_ru": "Блокирует запрос после достижения лимита в sliding window",
        },
        {
            "check_key": "runner_expires_old_entries",
            "title_en": "Expires old entries so the user can recover after the window moves",
            "title_ru": "Удаляет старые события и снова разрешает запрос после сдвига окна",
        },
        {
            "check_key": "runner_isolates_users",
            "title_en": "Keeps per-user state isolated",
            "title_ru": "Сохраняет изоляцию состояния между пользователями",
        },
    ),
    "feature_freshness_monitor": (
        {
            "check_key": "runner_allows_fresh_features",
            "title_en": "Allows scoring when required features are fresh",
            "title_ru": "Разрешает scoring, когда необходимые фичи свежие",
        },
        {
            "check_key": "runner_blocks_stale_features",
            "title_en": "Blocks scoring when feature age exceeds the threshold",
            "title_ru": "Блокирует scoring, когда возраст фич превышает threshold",
        },
        {
            "check_key": "runner_uses_fallback_for_missing_feature",
            "title_en": "Uses fallback data for a missing feature value",
            "title_ru": "Использует fallback-данные для отсутствующей фичи",
        },
        {
            "check_key": "runner_explains_feature_decision",
            "title_en": "Returns a reason explaining the freshness decision",
            "title_ru": "Возвращает причину freshness-решения",
        },
    ),
    "flaky_test_classifier": (
        {
            "check_key": "runner_groups_repeated_runs",
            "title_en": "Groups repeated test runs by stable test id",
            "title_ru": "Группирует повторные прогоны по стабильному test id",
        },
        {
            "check_key": "runner_flags_flaky_mixed_outcomes",
            "title_en": "Flags tests with both pass and fail outcomes as flaky",
            "title_ru": "Помечает тесты с pass и fail исходами как flaky",
        },
        {
            "check_key": "runner_separates_stable_failures",
            "title_en": "Separates consistently failing tests from flaky tests",
            "title_ru": "Отделяет стабильно падающие тесты от flaky-тестов",
        },
        {
            "check_key": "runner_emits_ci_diagnostics",
            "title_en": "Emits a stable CI diagnostic summary",
            "title_ru": "Формирует стабильную CI diagnostic summary",
        },
    ),
    "deployment_rollout_guard": (
        {
            "check_key": "runner_continues_healthy_rollout",
            "title_en": "Continues rollout when canary health is good",
            "title_ru": "Продолжает rollout, когда canary health в норме",
        },
        {
            "check_key": "runner_pauses_degraded_rollout",
            "title_en": "Pauses rollout when metrics degrade but rollback is not mandatory",
            "title_ru": "Ставит rollout на паузу при деградации без обязательного rollback",
        },
        {
            "check_key": "runner_rolls_back_critical_failure",
            "title_en": "Rolls back when error or latency thresholds are critical",
            "title_ru": "Откатывает при критических error/latency thresholds",
        },
        {
            "check_key": "runner_explains_rollout_decision",
            "title_en": "Returns a clear reason for the rollout decision",
            "title_ru": "Возвращает понятную причину rollout-решения",
        },
    ),
}


def _score_system_design_question_block(
    questions: list[dict],
    keyword_hints: tuple[str, ...],
) -> dict:
    depth_scale = {
        "none": 1.0,
        "surface": 3.5,
        "adequate": 6.2,
        "strong": 8.1,
        "expert": 9.3,
    }
    specificity_scale = {
        "low": 3.5,
        "medium": 6.7,
        "high": 9.0,
    }

    question_numbers: list[int] = []
    qualities: list[float] = []
    depth_scores: list[float] = []
    specificity_scores: list[float] = []
    evidence_items: list[str] = []
    all_text_parts: list[str] = []
    red_flag_count = 0

    for question in questions:
        try:
            question_number = int(question.get("question_number") or 0)
        except (TypeError, ValueError):
            question_number = 0
        if question_number > 0:
            question_numbers.append(question_number)

        qualities.append(_to_float(question.get("answer_quality"), 0.0))
        depth_scores.append(depth_scale.get(str(question.get("depth", "surface")).lower(), 3.5))
        specificity_scores.append(
            specificity_scale.get(str(question.get("specificity", "low")).lower(), 3.5)
        )

        evidence = str(question.get("evidence") or "").strip()
        if evidence:
            evidence_items.append(evidence)
            all_text_parts.append(evidence.lower())

        for skill in question.get("skills_mentioned", []) or []:
            skill_name = str(skill.get("skill") or "").strip()
            if skill_name:
                all_text_parts.append(skill_name.lower())

        for red_flag in question.get("red_flags", []) or []:
            if red_flag:
                red_flag_count += 1
                all_text_parts.append(str(red_flag).lower())

    if not question_numbers:
        return {
            "question_numbers": [],
            "average_answer_quality": None,
            "stage_score": None,
            "evidence_items": [],
            "keyword_score": None,
        }

    combined_text = " ".join(all_text_parts)
    keyword_hits = sum(1 for hint in keyword_hints if hint in combined_text)
    keyword_score = min(10.0, keyword_hits * 2.0)
    avg_quality = sum(qualities) / len(qualities)
    avg_depth = sum(depth_scores) / len(depth_scores)
    avg_specificity = sum(specificity_scores) / len(specificity_scores)
    red_flag_penalty = min(1.2, red_flag_count * 0.2)
    stage_score = round(
        max(
            0.0,
            min(
                10.0,
                (avg_quality * 0.55)
                + (avg_depth * 0.20)
                + (avg_specificity * 0.15)
                + (keyword_score * 0.10)
                - red_flag_penalty,
            ),
        ),
        1,
    )
    return {
        "question_numbers": sorted(question_numbers),
        "average_answer_quality": round(avg_quality, 2),
        "stage_score": stage_score,
        "evidence_items": evidence_items[:3],
        "keyword_score": round(keyword_score, 1),
    }


def _build_system_design_evaluation(
    interview_meta: dict | None,
    per_question_analysis: list[dict],
) -> dict | None:
    interview_meta = interview_meta or {}
    module_type = str(interview_meta.get("module_type") or "").strip().lower()
    if module_type != "system_design":
        return None

    stage_plan = (
        list(interview_meta.get("module_stage_plan", []) or [])
        if isinstance(interview_meta.get("module_stage_plan"), list)
        else []
    )
    if not stage_plan:
        return None

    question_history = (
        list(interview_meta.get("module_question_history", []) or [])
        if isinstance(interview_meta.get("module_question_history"), list)
        else []
    )
    stage_map: dict[int, dict[str, str | None]] = {}
    for item in question_history:
        if not isinstance(item, dict):
            continue
        try:
            assistant_turn = int(item.get("assistant_turn") or 0)
        except (TypeError, ValueError):
            assistant_turn = 0
        if assistant_turn <= 0:
            continue
        stage_map[assistant_turn] = {
            "stage_key": str(item.get("stage_key") or "").strip() or None,
            "stage_title": str(item.get("stage_title") or "").strip() or None,
        }

    questions_by_stage: dict[str, list[dict]] = {}
    for question in per_question_analysis:
        if not isinstance(question, dict):
            continue
        try:
            question_number = int(question.get("question_number") or 0)
        except (TypeError, ValueError):
            question_number = 0
        if question_number <= 0:
            continue
        stage_key = str(stage_map.get(question_number, {}).get("stage_key") or "").strip()
        if not stage_key:
            continue
        questions_by_stage.setdefault(stage_key, []).append(question)

    stages: list[dict] = []
    stage_scores: dict[str, float | None] = {}
    for stage in stage_plan:
        if not isinstance(stage, dict):
            continue
        stage_key = str(stage.get("stage_key") or "").strip()
        stage_title = str(stage.get("stage_title") or "").strip()
        if not stage_key:
            continue
        scored = _score_system_design_question_block(
            questions_by_stage.get(stage_key, []),
            _SYSTEM_DESIGN_STAGE_KEYWORDS.get(stage_key, ()),
        )
        stage_score = scored["stage_score"] if isinstance(scored["stage_score"], (int, float)) else None
        stage_scores[stage_key] = stage_score
        stages.append(
            {
                "stage_key": stage_key,
                "stage_title": stage_title or stage_key.replace("_", " ").title(),
                "question_numbers": scored["question_numbers"],
                "average_answer_quality": scored["average_answer_quality"],
                "stage_score": stage_score,
                "evidence_items": scored["evidence_items"],
            }
        )

    weighted_scores = [
        (float(score), weight)
        for stage_key, weight in _SYSTEM_DESIGN_STAGE_WEIGHTS.items()
        for score in [stage_scores.get(stage_key)]
        if isinstance(score, (int, float))
    ]
    overall_score = None
    if weighted_scores:
        total_weight = sum(weight for _, weight in weighted_scores)
        if total_weight > 0:
            overall_score = round(
                sum(score * weight for score, weight in weighted_scores) / total_weight,
                1,
            )

    reliability_questions = [
        *questions_by_stage.get("high_level_design", []),
        *questions_by_stage.get("tradeoffs", []),
    ]
    reliability_scored = _score_system_design_question_block(
        reliability_questions,
        _SYSTEM_DESIGN_RELIABILITY_KEYWORDS,
    )
    reliability_score = (
        reliability_scored["stage_score"]
        if isinstance(reliability_scored["stage_score"], (int, float))
        else None
    )

    rubric_scores = [
        {
            "rubric_key": "requirements_clarity",
            "score": stage_scores.get("requirements"),
        },
        {
            "rubric_key": "architecture_quality",
            "score": stage_scores.get("high_level_design"),
        },
        {
            "rubric_key": "tradeoff_reasoning",
            "score": stage_scores.get("tradeoffs"),
        },
        {
            "rubric_key": "reliability_scaling",
            "score": reliability_score,
        },
    ]

    return {
        "module_title": str(interview_meta.get("module_title") or "").strip() or None,
        "scenario_id": str(interview_meta.get("module_scenario_id") or "").strip() or None,
        "scenario_title": str(interview_meta.get("module_scenario_title") or "").strip() or None,
        "scenario_prompt": str(interview_meta.get("module_scenario_prompt") or "").strip() or None,
        "stage_count": len(stages),
        "overall_score": overall_score,
        "rubric_scores": rubric_scores,
        "stages": stages,
    }


def _build_stage_answer_map(
    interview_meta: dict | None,
    message_history: list[dict] | None,
) -> dict[str, list[str]]:
    interview_meta = interview_meta or {}
    question_history = (
        list(interview_meta.get("module_question_history", []) or [])
        if isinstance(interview_meta.get("module_question_history"), list)
        else []
    )
    assistant_stage_map: dict[int, str] = {}
    for item in question_history:
        if not isinstance(item, dict):
            continue
        assistant_turn = _to_int(item.get("assistant_turn"), 0)
        stage_key = str(item.get("stage_key") or "").strip()
        if assistant_turn > 0 and stage_key:
            assistant_stage_map[assistant_turn] = stage_key

    answers_by_stage: dict[str, list[str]] = {}
    assistant_turn = 0
    last_stage_key: str | None = None
    for msg in message_history or []:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "").strip().lower()
        content = str(msg.get("content") or "").strip()
        if not content:
            continue
        if role == "assistant":
            assistant_turn += 1
            last_stage_key = assistant_stage_map.get(assistant_turn)
        elif role == "candidate" and last_stage_key:
            answers_by_stage.setdefault(last_stage_key, []).append(content)
    return answers_by_stage


def _extract_code_excerpt(texts: list[str]) -> str | None:
    for text in texts:
        normalized = str(text or "").strip()
        if not normalized:
            continue
        fenced_blocks = re.findall(r"```(?:[\w#+.-]+)?\n(.*?)```", normalized, flags=re.DOTALL)
        for block in fenced_blocks:
            excerpt = str(block or "").strip()
            if excerpt:
                return excerpt[:1200]
        if any(hint in normalized for hint in _CODING_TASK_CODE_HINTS):
            return normalized[:1200]
    return None


def _extract_sql_excerpt(texts: list[str]) -> str | None:
    for text in texts:
        normalized = str(text or "").strip()
        if not normalized:
            continue
        lowered = normalized.lower()
        if any(hint in lowered for hint in _SQL_LIVE_QUERY_HINTS):
            return normalized[:1200]
    return None


def _extract_written_excerpt(texts: list[str]) -> str | None:
    for text in texts:
        normalized = str(text or "").strip()
        if not normalized:
            continue
        return normalized[:1200]
    return None


def _find_matching_evidence(
    texts: list[str],
    patterns: tuple[str, ...],
) -> str | None:
    lowered_patterns = [pattern.lower() for pattern in patterns if pattern]
    for text in texts:
        raw = str(text or "").strip()
        lowered = raw.lower()
        if raw and any(pattern in lowered for pattern in lowered_patterns):
            return raw[:240]
    return None


def _sql_live_check_title(
    *,
    scenario_id: str | None,
    check_key: str,
    report_language: str,
) -> str:
    normalized_language = _normalized_report_language(report_language)
    scenario_def = _SQL_LIVE_SCENARIO_VALIDATION_DEFS.get(str(scenario_id or "").strip(), {})
    for item in scenario_def.get("check_defs", ()):
        if str(item.get("check_key") or "").strip() != check_key:
            continue
        if normalized_language == "ru":
            return str(item.get("title_ru") or check_key).strip()
        return str(item.get("title_en") or check_key).strip()
    return check_key


def _normalize_sql_result_row(row: tuple) -> tuple:
    normalized: list[object] = []
    for value in row:
        if isinstance(value, (int, float)):
            normalized.append(round(float(value), 4))
            continue
        if isinstance(value, float):
            normalized.append(round(value, 4))
        else:
            normalized.append(value)
    return tuple(normalized)


def _map_sql_live_validation_payload(
    *,
    scenario_id: str,
    payload: dict,
    report_language: str,
) -> tuple[list[dict], float | None]:
    raw_checks = payload.get("validation_checks")
    if not isinstance(raw_checks, list):
        raise RuntimeError("sandbox returned invalid SQL validation payload")

    checks: list[dict] = []
    for item in raw_checks:
        if not isinstance(item, dict):
            continue
        check_key = str(item.get("check_key") or "").strip()
        if not check_key:
            continue
        raw_score = item.get("score")
        score = round(float(raw_score), 1) if isinstance(raw_score, (int, float)) else 0.0
        evidence = str(item.get("evidence") or "").strip() or None
        checks.append(
            {
                "check_key": check_key,
                "title": _sql_live_check_title(
                    scenario_id=scenario_id,
                    check_key=check_key,
                    report_language=report_language,
                ),
                "status": str(item.get("status") or "missed").strip() or "missed",
                "score": score,
                "evidence": evidence,
            }
        )

    raw_validation_score = payload.get("validation_score")
    validation_score = (
        round(float(raw_validation_score), 1)
        if isinstance(raw_validation_score, (int, float))
        else None
    )
    return checks, validation_score


def _build_sql_live_validation_checks(
    *,
    scenario_id: str | None,
    query_text: str | None,
    report_language: str,
) -> tuple[list[dict], float | None]:
    normalized_scenario_id = str(scenario_id or "").strip()
    scenario_def = _SQL_LIVE_SCENARIO_VALIDATION_DEFS.get(normalized_scenario_id)
    query = str(query_text or "").strip()
    if not scenario_def or not query:
        return [], None

    if settings.SANDBOX_SERVICE_URL:
        try:
            payload = _run_sql_live_validation_in_sandbox(
                scenario_id=normalized_scenario_id,
                query_text=query,
            )
            return _map_sql_live_validation_payload(
                scenario_id=normalized_scenario_id,
                payload=payload,
                report_language=report_language,
            )
        except Exception:
            logger.warning("SQL live sandbox validation failed, falling back to local SQLite", exc_info=True)

    stripped_query = query.strip().rstrip(";").strip()
    lowered_query = stripped_query.lower()
    is_select_only = (
        bool(stripped_query)
        and lowered_query.startswith(("select", "with"))
        and ";" not in stripped_query
    )

    checks: list[dict] = [
        {
            "check_key": "query_is_select_only",
            "title": _sql_live_check_title(
                scenario_id=normalized_scenario_id,
                check_key="query_is_select_only",
                report_language=report_language,
            ),
            "status": "passed" if is_select_only else "missed",
            "score": 10.0 if is_select_only else 0.0,
            "evidence": None if is_select_only else "Only a single SELECT/CTE query is allowed.",
        }
    ]

    if not is_select_only:
        for check_key in ("query_executes", "expected_columns", "expected_rows"):
            checks.append(
                {
                    "check_key": check_key,
                    "title": _sql_live_check_title(
                        scenario_id=normalized_scenario_id,
                        check_key=check_key,
                        report_language=report_language,
                    ),
                    "status": "missed",
                    "score": 0.0,
                    "evidence": None,
                }
            )
        return checks, 2.5

    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(":memory:")
        cursor = conn.cursor()
        for statement in scenario_def.get("schema_statements", ()):
            cursor.executescript(str(statement))
        for statement in scenario_def.get("seed_statements", ()):
            cursor.execute(str(statement))

        cursor.execute(stripped_query)
        rows = [_normalize_sql_result_row(tuple(row)) for row in cursor.fetchall()]
        columns = tuple(str(item[0] or "").strip().lower() for item in (cursor.description or ()))
        expected_columns = tuple(str(item).strip().lower() for item in scenario_def.get("expected_columns", ()))
        expected_rows = tuple(_normalize_sql_result_row(tuple(row)) for row in scenario_def.get("expected_rows", ()))

        columns_match = columns == expected_columns
        rows_match = rows == list(expected_rows)
        checks.extend(
            [
                {
                    "check_key": "query_executes",
                    "title": _sql_live_check_title(
                        scenario_id=normalized_scenario_id,
                        check_key="query_executes",
                        report_language=report_language,
                    ),
                    "status": "passed",
                    "score": 10.0,
                    "evidence": f"rows={len(rows)}",
                },
                {
                    "check_key": "expected_columns",
                    "title": _sql_live_check_title(
                        scenario_id=normalized_scenario_id,
                        check_key="expected_columns",
                        report_language=report_language,
                    ),
                    "status": "passed" if columns_match else "missed",
                    "score": 10.0 if columns_match else 0.0,
                    "evidence": ", ".join(columns) if columns else None,
                },
                {
                    "check_key": "expected_rows",
                    "title": _sql_live_check_title(
                        scenario_id=normalized_scenario_id,
                        check_key="expected_rows",
                        report_language=report_language,
                    ),
                    "status": "passed" if rows_match else "missed",
                    "score": 10.0 if rows_match else 0.0,
                    "evidence": str(rows[:3])[:240] if rows else None,
                },
            ]
        )
    except Exception as exc:
        checks.extend(
            [
                {
                    "check_key": "query_executes",
                    "title": _sql_live_check_title(
                        scenario_id=normalized_scenario_id,
                        check_key="query_executes",
                        report_language=report_language,
                    ),
                    "status": "missed",
                    "score": 0.0,
                    "evidence": str(exc)[:240] or None,
                },
                {
                    "check_key": "expected_columns",
                    "title": _sql_live_check_title(
                        scenario_id=normalized_scenario_id,
                        check_key="expected_columns",
                        report_language=report_language,
                    ),
                    "status": "missed",
                    "score": 0.0,
                    "evidence": None,
                },
                {
                    "check_key": "expected_rows",
                    "title": _sql_live_check_title(
                        scenario_id=normalized_scenario_id,
                        check_key="expected_rows",
                        report_language=report_language,
                    ),
                    "status": "missed",
                    "score": 0.0,
                    "evidence": None,
                },
            ]
        )
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    validation_score = round(
        sum(float(item.get("score") or 0.0) for item in checks) / len(checks),
        1,
    ) if checks else None
    return checks, validation_score


def _build_coding_task_coverage_checks(
    *,
    scenario_id: str | None,
    answers_by_stage: dict[str, list[str]],
    implementation_excerpt: str | None,
    report_language: str,
) -> tuple[list[dict], float | None]:
    normalized_language = _normalized_report_language(report_language)
    check_bank = _CODING_TASK_SCENARIO_COVERAGE_CHECKS.get(
        str(scenario_id or "").strip(),
        _CODING_TASK_DEFAULT_COVERAGE_CHECKS,
    )
    coverage_checks: list[dict] = []
    scores: list[float] = []

    implementation_texts = list(answers_by_stage.get("implementation", []))
    if implementation_excerpt:
        implementation_texts = [implementation_excerpt, *implementation_texts]

    for raw_check in check_bank:
        stage_key = str(raw_check.get("stage_key") or "").strip() or "implementation"
        stage_texts = implementation_texts if stage_key == "implementation" else list(answers_by_stage.get(stage_key, []))
        patterns = tuple(str(item).lower() for item in raw_check.get("patterns", ()) if str(item).strip())
        required_hits = max(_to_int(raw_check.get("required_hits"), 1), 1)
        searchable = "\n".join(text.lower() for text in stage_texts if str(text).strip())
        hits = sum(1 for pattern in patterns if pattern in searchable)

        if hits >= required_hits:
            status = "passed"
            score = 10.0
        elif hits > 0:
            status = "partial"
            score = 5.0
        else:
            status = "missed"
            score = 0.0

        title = (
            str(raw_check.get("title_ru") or "").strip()
            if normalized_language == "ru"
            else str(raw_check.get("title_en") or "").strip()
        ) or str(raw_check.get("check_key") or "").strip()
        evidence = _find_matching_evidence(stage_texts, patterns)
        coverage_checks.append(
            {
                "check_key": str(raw_check.get("check_key") or "").strip(),
                "title": title,
                "status": status,
                "score": score,
                "evidence": evidence,
            }
        )
        scores.append(score)

    coverage_score = round(sum(scores) / len(scores), 1) if scores else None
    return coverage_checks, coverage_score


def _build_coding_task_stack_checks(
    *,
    scenario_id: str | None,
    answers_by_stage: dict[str, list[str]],
    implementation_excerpt: str | None,
    report_language: str,
) -> tuple[list[dict], float | None]:
    normalized_language = _normalized_report_language(report_language)
    check_bank = _CODING_TASK_SCENARIO_STACK_CHECKS.get(str(scenario_id or "").strip(), ())
    stack_checks: list[dict] = []
    scores: list[float] = []
    if not check_bank:
        return stack_checks, None

    implementation_texts = list(answers_by_stage.get("implementation", []))
    if implementation_excerpt:
        implementation_texts = [implementation_excerpt, *implementation_texts]

    for raw_check in check_bank:
        stage_key = str(raw_check.get("stage_key") or "").strip() or "implementation"
        stage_texts = implementation_texts if stage_key == "implementation" else list(answers_by_stage.get(stage_key, []))
        patterns = tuple(str(item).lower() for item in raw_check.get("patterns", ()) if str(item).strip())
        required_hits = max(_to_int(raw_check.get("required_hits"), 1), 1)
        searchable = "\n".join(text.lower() for text in stage_texts if str(text).strip())
        hits = sum(1 for pattern in patterns if pattern in searchable)

        if hits >= required_hits:
            status = "passed"
            score = 10.0
        elif hits > 0:
            status = "partial"
            score = 5.0
        else:
            status = "missed"
            score = 0.0

        title = (
            str(raw_check.get("title_ru") or "").strip()
            if normalized_language == "ru"
            else str(raw_check.get("title_en") or "").strip()
        ) or str(raw_check.get("check_key") or "").strip()
        evidence = _find_matching_evidence(stage_texts, patterns)
        stack_checks.append(
            {
                "check_key": str(raw_check.get("check_key") or "").strip(),
                "title": title,
                "status": status,
                "score": score,
                "evidence": evidence,
            }
        )
        scores.append(score)

    stack_score = round(sum(scores) / len(scores), 1) if scores else None
    return stack_checks, stack_score


def _build_coding_task_review_notes(
    *,
    report_language: str,
    stack_focus: str | None,
    preferred_language: str | None,
    coverage_checks: list[dict],
    stack_checks: list[dict],
    runner_checks: list[dict],
    implementation_score: float | None,
    review_score: float | None,
    correctness_score: float | None,
) -> tuple[list[str], list[str], list[str]]:
    normalized_language = _normalized_report_language(report_language)
    stack_label = str(stack_focus or "").strip() or (
        "the selected stack" if normalized_language == "en" else "выбранный стек"
    )
    language_label = str(preferred_language or "").strip() or (
        "the chosen language" if normalized_language == "en" else "выбранный язык"
    )

    def _titles(checks: list[dict], statuses: tuple[str, ...]) -> list[str]:
        seen: set[str] = set()
        items: list[str] = []
        for check in checks:
            if str(check.get("status") or "").strip() not in statuses:
                continue
            title = str(check.get("title") or "").strip()
            if not title or title in seen:
                continue
            seen.add(title)
            items.append(title)
        return items

    def _join_titles(titles: list[str]) -> str:
        return ", ".join(titles[:3])

    def _append_unique(target: list[str], message: str | None) -> None:
        text = str(message or "").strip()
        if text and text not in target:
            target.append(text)

    passed_stack = _titles(stack_checks, ("passed",))
    partial_stack = _titles(stack_checks, ("partial",))
    weak_stack = _titles(stack_checks, ("missed", "partial"))
    passed_coverage = _titles(coverage_checks, ("passed",))
    weak_coverage = _titles(coverage_checks, ("missed", "partial"))
    weak_runner = _titles(runner_checks, ("missed", "partial"))

    strengths: list[str] = []
    gaps: list[str] = []
    next_steps: list[str] = []

    if isinstance(implementation_score, (int, float)) and float(implementation_score) >= 7.0:
        _append_unique(
            strengths,
            (
                "Implementation stayed structured and readable during the live task."
                if normalized_language == "en"
                else "Реализация оставалась структурной и читаемой во время задания."
            ),
        )
    if passed_stack:
        _append_unique(
            strengths,
            (
                f"Showed practical fluency in {stack_label}: {_join_titles(passed_stack)}."
                if normalized_language == "en"
                else f"Показал практическое владение стеком {stack_label}: {_join_titles(passed_stack)}."
            ),
        )
    elif partial_stack:
        _append_unique(
            strengths,
            (
                f"Showed partial fluency in {stack_label}: {_join_titles(partial_stack)}."
                if normalized_language == "en"
                else f"Показал частичное владение стеком {stack_label}: {_join_titles(partial_stack)}."
            ),
        )
    if passed_coverage:
        _append_unique(
            strengths,
            (
                f"Covered key functional requirements: {_join_titles(passed_coverage)}."
                if normalized_language == "en"
                else f"Покрыл ключевые функциональные требования: {_join_titles(passed_coverage)}."
            ),
        )

    if weak_stack:
        _append_unique(
            gaps,
            (
                f"Stack-specific patterns are still weak in {stack_label}: {_join_titles(weak_stack)}."
                if normalized_language == "en"
                else f"Стековые паттерны пока слабые в области {stack_label}: {_join_titles(weak_stack)}."
            ),
        )
    if weak_coverage:
        _append_unique(
            gaps,
            (
                f"Functional coverage is incomplete around {_join_titles(weak_coverage)}."
                if normalized_language == "en"
                else f"Функциональное покрытие неполное в части {_join_titles(weak_coverage)}."
            ),
        )
    if weak_runner:
        _append_unique(
            gaps,
            (
                f"Hidden execution checks exposed issues in {_join_titles(weak_runner)}."
                if normalized_language == "en"
                else f"Скрытые проверки выполнения выявили проблемы в части {_join_titles(weak_runner)}."
            ),
        )
    if isinstance(review_score, (int, float)) and float(review_score) < 6.0:
        _append_unique(
            gaps,
            (
                "Code explanation and trade-off discussion stayed too shallow."
                if normalized_language == "en"
                else "Объяснение кода и обсуждение trade-off осталось слишком поверхностным."
            ),
        )
    if isinstance(correctness_score, (int, float)) and float(correctness_score) < 6.0:
        _append_unique(
            gaps,
            (
                "Correctness and edge-case reasoning need tighter validation."
                if normalized_language == "en"
                else "Корректность и разбор edge-case требуют более строгой проверки."
            ),
        )

    if weak_stack:
        _append_unique(
            next_steps,
            (
                f"Practice {_join_titles(weak_stack)} in {language_label} with one small end-to-end exercise."
                if normalized_language == "en"
                else f"Отработай {_join_titles(weak_stack)} на {language_label} через одно небольшое end-to-end задание."
            ),
        )
    if weak_coverage:
        _append_unique(
            next_steps,
            (
                f"Add explicit handling for {_join_titles(weak_coverage)} and explain the trade-offs in review."
                if normalized_language == "en"
                else f"Добавь явную обработку {_join_titles(weak_coverage)} и проговори trade-off на этапе review."
            ),
        )
    if weak_runner:
        _append_unique(
            next_steps,
            (
                f"Re-run the solution against failure and edge scenarios around {_join_titles(weak_runner)}."
                if normalized_language == "en"
                else f"Перепроверь решение на сбойных и граничных сценариях вокруг {_join_titles(weak_runner)}."
            ),
        )
    if not next_steps:
        _append_unique(
            next_steps,
            (
                f"Keep explaining design choices in {language_label} while implementing to preserve stack clarity."
                if normalized_language == "en"
                else f"Продолжай проговаривать решения на {language_label} во время реализации, чтобы сохранять ясность по стеку."
            ),
        )

    return strengths[:3], gaps[:3], next_steps[:3]


def _coding_task_runner_title(
    *,
    scenario_id: str | None,
    check_key: str,
    report_language: str,
) -> str:
    normalized_language = _normalized_report_language(report_language)
    for item in _CODING_TASK_RUNNER_CHECK_DEFS.get(str(scenario_id or "").strip(), ()):
        if str(item.get("check_key") or "").strip() != check_key:
            continue
        if normalized_language == "ru":
            return str(item.get("title_ru") or check_key).strip()
        return str(item.get("title_en") or check_key).strip()
    if check_key == "runner_execution_timeout":
        return "Runner timed out" if normalized_language == "en" else "Runner превысил лимит времени"
    if check_key == "runner_execution_failed":
        return "Runner execution failed" if normalized_language == "en" else "Runner завершился с ошибкой"
    return check_key


def _build_coding_task_runner_checks(
    *,
    scenario_id: str | None,
    artifact_code: str | None,
    artifact_language: str | None,
    report_language: str,
) -> tuple[list[dict], float | None]:
    normalized_scenario_id = str(scenario_id or "").strip()
    normalized_language = str(artifact_language or "").strip().lower()
    if not artifact_code or normalized_language not in {"python", "py"}:
        return [], None
    if normalized_scenario_id not in _CODING_TASK_RUNNER_CHECK_DEFS:
        return [], None

    wrapper = textwrap.dedent(
        """
        import ast
        import json
        import sys
        from collections import defaultdict, deque

        ALLOWED_MODULES = {"collections", "typing"}
        DISALLOWED_CALLS = {
            "open", "exec", "eval", "compile", "input", "globals",
            "locals", "vars", "dir", "getattr", "setattr", "delattr", "breakpoint"
        }

        def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
            root = str(name or "").split(".")[0]
            if root not in ALLOWED_MODULES:
                raise ImportError(f"import '{name}' is not allowed")
            return __import__(name, globals, locals, fromlist, level)

        def validate_tree(tree):
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if str(alias.name or "").split(".")[0] not in ALLOWED_MODULES:
                            raise ValueError(f"disallowed import: {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    module = str(node.module or "").split(".")[0]
                    if module not in ALLOWED_MODULES:
                        raise ValueError(f"disallowed import: {node.module}")
                elif isinstance(node, ast.Attribute):
                    if str(getattr(node, "attr", "")).startswith("__"):
                        raise ValueError("dunder attribute access is not allowed")
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    if node.func.id in DISALLOWED_CALLS:
                        raise ValueError(f"disallowed call: {node.func.id}")

        def safe_globals():
            return {
                "__builtins__": {
                    "len": len,
                    "range": range,
                    "min": min,
                    "max": max,
                    "sum": sum,
                    "abs": abs,
                    "enumerate": enumerate,
                    "list": list,
                    "dict": dict,
                    "set": set,
                    "tuple": tuple,
                    "int": int,
                    "float": float,
                    "str": str,
                    "bool": bool,
                    "any": any,
                    "all": all,
                    "zip": zip,
                    "sorted": sorted,
                    "reversed": reversed,
                    "Exception": Exception,
                    "ValueError": ValueError,
                    "TypeError": TypeError,
                    "KeyError": KeyError,
                    "__import__": safe_import,
                },
                "defaultdict": defaultdict,
                "deque": deque,
            }

        def run_rate_limiter_checks(ns):
            fn = ns.get("allow_request")
            if not callable(fn):
                raise ValueError("allow_request function was not found")

            def reset_state():
                if "windows" in ns:
                    ns["windows"] = defaultdict(deque)

            results = []

            reset_state()
            within_limit = [bool(fn("user-a", ts)) for ts in (0, 1, 2, 3, 4)]
            results.append({
                "check_key": "runner_allows_within_limit",
                "passed": all(within_limit),
                "details": f"sequence={within_limit}",
            })

            reset_state()
            for ts in (0, 1, 2, 3, 4):
                fn("user-a", ts)
            blocked = bool(fn("user-a", 5)) is False
            results.append({
                "check_key": "runner_blocks_over_limit",
                "passed": blocked,
                "details": f"sixth_request_blocked={blocked}",
            })

            reset_state()
            for ts in (0, 1, 2, 3, 4):
                fn("user-a", ts)
            expired_ok = bool(fn("user-a", 60)) is True
            results.append({
                "check_key": "runner_expires_old_entries",
                "passed": expired_ok,
                "details": f"request_after_window={expired_ok}",
            })

            reset_state()
            for ts in (0, 1, 2, 3, 4):
                fn("user-a", ts)
            other_user_ok = bool(fn("user-b", 5)) is True
            results.append({
                "check_key": "runner_isolates_users",
                "passed": other_user_ok,
                "details": f"other_user_allowed={other_user_ok}",
            })
            return results

        def _call_feature_freshness(fn, record, now_ts=10000):
            try:
                return fn(record, now_ts, max_age_seconds=3600)
            except TypeError:
                try:
                    return fn(record, now_ts)
                except TypeError:
                    return fn(record)

        def _decision_allows(result):
            if isinstance(result, bool):
                return result
            if isinstance(result, str):
                lowered = result.strip().lower()
                if any(token in lowered for token in ("allow", "allowed", "pass", "ok")):
                    return True
                if any(token in lowered for token in ("block", "blocked", "deny", "reject", "stale")):
                    return False
            if isinstance(result, dict):
                if "allowed" in result:
                    return bool(result.get("allowed"))
                if "allow" in result:
                    return bool(result.get("allow"))
                if "blocked" in result:
                    return not bool(result.get("blocked"))
                if "block" in result:
                    return not bool(result.get("block"))
                for key in ("decision", "status", "action", "recommendation"):
                    value = str(result.get(key) or "").strip().lower()
                    if value in {"allow", "allowed", "pass", "ok", "use_fallback"}:
                        return True
                    if value in {"block", "blocked", "deny", "reject", "stale"}:
                        return False
            return None

        def _used_fallback(result):
            if not isinstance(result, dict):
                return False
            if bool(result.get("used_fallback") or result.get("fallback_used") or result.get("fallback")):
                return True
            return str(result.get("source") or "").strip().lower() == "fallback"

        def _has_reason(result):
            if isinstance(result, str):
                return bool(result.strip())
            if not isinstance(result, dict):
                return False
            for key in ("reason", "explanation", "message", "details"):
                if str(result.get(key) or "").strip():
                    return True
            return False

        def run_feature_freshness_checks(ns):
            fn = ns.get("evaluate_feature_freshness")
            if not callable(fn):
                raise ValueError("evaluate_feature_freshness function was not found")

            fresh_record = {
                "feature_age_seconds": 120,
                "features": {"risk_score": 0.42},
                "fallback_features": {"risk_score": 0.50},
            }
            stale_record = {
                "feature_age_seconds": 7200,
                "features": {"risk_score": 0.42},
                "fallback_features": {"risk_score": 0.50},
            }
            missing_record = {
                "feature_age_seconds": 120,
                "features": {"risk_score": None},
                "fallback_features": {"risk_score": 0.55},
            }

            fresh_result = _call_feature_freshness(fn, fresh_record)
            stale_result = _call_feature_freshness(fn, stale_record)
            fallback_result = _call_feature_freshness(fn, missing_record)
            fresh_decision = _decision_allows(fresh_result)
            stale_decision = _decision_allows(stale_result)
            fallback_decision = _decision_allows(fallback_result)

            results = [
                {
                    "check_key": "runner_allows_fresh_features",
                    "passed": fresh_decision is True,
                    "details": f"fresh_decision={fresh_decision}",
                },
                {
                    "check_key": "runner_blocks_stale_features",
                    "passed": stale_decision is False,
                    "details": f"stale_decision={stale_decision}",
                },
                {
                    "check_key": "runner_uses_fallback_for_missing_feature",
                    "passed": fallback_decision is True and _used_fallback(fallback_result),
                    "details": f"fallback_decision={fallback_decision}; used_fallback={_used_fallback(fallback_result)}",
                },
                {
                    "check_key": "runner_explains_feature_decision",
                    "passed": any(_has_reason(item) for item in (fresh_result, stale_result, fallback_result)),
                    "details": "reason_present=" + str(any(_has_reason(item) for item in (fresh_result, stale_result, fallback_result))),
                },
            ]
            return results

        def _call_flaky_classifier(fn, runs):
            try:
                return fn(runs)
            except TypeError:
                return fn(test_runs=runs)

        def _item_name(item):
            if isinstance(item, str):
                return item
            if not isinstance(item, dict):
                return ""
            for key in ("test_id", "test", "name", "id", "nodeid"):
                value = str(item.get(key) or "").strip()
                if value:
                    return value
            return ""

        def _items_from_keys(result, keys):
            if isinstance(result, dict):
                for key in keys:
                    value = result.get(key)
                    if isinstance(value, (list, tuple, set)):
                        return list(value)
            if isinstance(result, (list, tuple, set)):
                return list(result)
            return []

        def _contains_named_item(items, target):
            return any(_item_name(item) == target for item in items)

        def _has_flaky(result, target):
            flaky_items = _items_from_keys(result, ("flaky_tests", "flaky", "flakes", "unstable_tests", "unstable"))
            if _contains_named_item(flaky_items, target):
                return True
            for item in flaky_items:
                if isinstance(item, dict) and bool(item.get("flaky")) and _item_name(item) == target:
                    return True
            if isinstance(result, (list, tuple, set)):
                for item in result:
                    if not isinstance(item, dict) or _item_name(item) != target:
                        continue
                    classification = str(item.get("classification") or item.get("status") or item.get("kind") or "").lower()
                    if bool(item.get("flaky")) or "flaky" in classification:
                        return True
            return False

        def _has_stable_failure(result, target):
            stable_items = _items_from_keys(result, ("stable_failures", "persistent_failures", "consistent_failures", "failed_tests"))
            if _contains_named_item(stable_items, target):
                return True
            if isinstance(result, (list, tuple, set)):
                for item in result:
                    if not isinstance(item, dict) or _item_name(item) != target:
                        continue
                    classification = str(item.get("classification") or item.get("status") or item.get("kind") or "").lower()
                    if "stable" in classification or "persistent" in classification or "consistent" in classification:
                        return True
            return False

        def _has_diagnostics(result):
            if isinstance(result, str):
                return bool(result.strip())
            if isinstance(result, dict):
                for key in ("summary", "diagnostics", "report", "message"):
                    value = result.get(key)
                    if isinstance(value, str) and value.strip():
                        return True
                    if isinstance(value, (list, tuple, dict)) and value:
                        return True
            return False

        def run_flaky_classifier_checks(ns):
            fn = ns.get("classify_flaky_tests")
            if not callable(fn):
                raise ValueError("classify_flaky_tests function was not found")

            runs = [
                {"test_id": "test_login", "run_id": "build-1", "status": "failed"},
                {"test_id": "test_login", "run_id": "build-2", "status": "passed"},
                {"test_id": "test_checkout", "run_id": "build-1", "status": "failed"},
                {"test_id": "test_checkout", "run_id": "build-2", "status": "failed"},
                {"test_id": "test_search", "run_id": "build-1", "status": "passed"},
                {"test_id": "test_search", "run_id": "build-2", "status": "passed"},
            ]
            result = _call_flaky_classifier(fn, runs)
            grouped = False
            if isinstance(result, dict):
                groups = result.get("groups") or result.get("by_test") or result.get("grouped_runs")
                grouped = isinstance(groups, dict) and "test_login" in groups and "test_checkout" in groups
            flags_flaky = _has_flaky(result, "test_login")
            separates_stable = _has_stable_failure(result, "test_checkout") and not _has_flaky(result, "test_checkout")

            return [
                {
                    "check_key": "runner_groups_repeated_runs",
                    "passed": grouped,
                    "details": f"grouped={grouped}",
                },
                {
                    "check_key": "runner_flags_flaky_mixed_outcomes",
                    "passed": flags_flaky,
                    "details": f"test_login_flaky={flags_flaky}",
                },
                {
                    "check_key": "runner_separates_stable_failures",
                    "passed": separates_stable,
                    "details": f"test_checkout_stable_failure={separates_stable}",
                },
                {
                    "check_key": "runner_emits_ci_diagnostics",
                    "passed": _has_diagnostics(result),
                    "details": f"diagnostics_present={_has_diagnostics(result)}",
                },
            ]

        def _call_rollout_guard(fn, snapshot):
            try:
                return fn(snapshot)
            except TypeError:
                return fn(metrics=snapshot)

        def _rollout_action(result):
            if isinstance(result, str):
                lowered = result.strip().lower()
                if "rollback" in lowered or "roll back" in lowered:
                    return "rollback"
                if "pause" in lowered or "hold" in lowered:
                    return "pause"
                if "continue" in lowered or "proceed" in lowered:
                    return "continue"
            if isinstance(result, dict):
                for key in ("action", "decision", "recommendation", "status"):
                    value = str(result.get(key) or "").strip().lower().replace("-", "_")
                    if value in {"rollback", "roll_back", "revert"}:
                        return "rollback"
                    if value in {"pause", "hold", "stop", "wait"}:
                        return "pause"
                    if value in {"continue", "proceed", "advance", "ok"}:
                        return "continue"
            return ""

        def run_deployment_rollout_checks(ns):
            fn = ns.get("evaluate_rollout_health")
            if not callable(fn):
                raise ValueError("evaluate_rollout_health function was not found")

            healthy = {
                "stage": "canary",
                "error_rate": 0.004,
                "latency_p95_ms": 180,
                "slo_burn_rate": 0.7,
                "alerts": [],
                "events": [{"type": "deploy_started", "severity": "info"}],
            }
            degraded = {
                "stage": "canary",
                "error_rate": 0.018,
                "latency_p95_ms": 460,
                "slo_burn_rate": 1.8,
                "alerts": [{"name": "latency-warning", "severity": "warning"}],
                "events": [{"type": "latency_regression", "severity": "warning"}],
            }
            critical = {
                "stage": "canary",
                "error_rate": 0.082,
                "latency_p95_ms": 1250,
                "slo_burn_rate": 6.5,
                "alerts": [{"name": "error-budget-burn", "severity": "critical"}],
                "events": [{"type": "customer-impact", "severity": "critical"}],
            }

            healthy_result = _call_rollout_guard(fn, healthy)
            degraded_result = _call_rollout_guard(fn, degraded)
            critical_result = _call_rollout_guard(fn, critical)
            healthy_action = _rollout_action(healthy_result)
            degraded_action = _rollout_action(degraded_result)
            critical_action = _rollout_action(critical_result)

            return [
                {
                    "check_key": "runner_continues_healthy_rollout",
                    "passed": healthy_action == "continue",
                    "details": f"healthy_action={healthy_action}",
                },
                {
                    "check_key": "runner_pauses_degraded_rollout",
                    "passed": degraded_action == "pause",
                    "details": f"degraded_action={degraded_action}",
                },
                {
                    "check_key": "runner_rolls_back_critical_failure",
                    "passed": critical_action == "rollback",
                    "details": f"critical_action={critical_action}",
                },
                {
                    "check_key": "runner_explains_rollout_decision",
                    "passed": any(_has_reason(item) for item in (healthy_result, degraded_result, critical_result)),
                    "details": "reason_present=" + str(any(_has_reason(item) for item in (healthy_result, degraded_result, critical_result))),
                },
            ]

        payload = json.loads(sys.stdin.read())
        source = str(payload.get("code") or "")
        scenario_id = str(payload.get("scenario_id") or "")

        tree = ast.parse(source, mode="exec")
        validate_tree(tree)
        ns = safe_globals()
        exec(compile(tree, "<candidate_code>", "exec"), ns, ns)

        if scenario_id == "rate_limiter_window_counter":
            results = run_rate_limiter_checks(ns)
        elif scenario_id == "feature_freshness_monitor":
            results = run_feature_freshness_checks(ns)
        elif scenario_id == "flaky_test_classifier":
            results = run_flaky_classifier_checks(ns)
        elif scenario_id == "deployment_rollout_guard":
            results = run_deployment_rollout_checks(ns)
        else:
            results = []

        runner_score = round(
            sum(10.0 if item.get("passed") else 0.0 for item in results) / len(results),
            1,
        ) if results else None
        print(json.dumps({"runner_score": runner_score, "runner_checks": results}))
        """
    )

    temp_path = None
    try:
        if settings.SANDBOX_SERVICE_URL:
            try:
                payload = _run_coding_task_runner_in_sandbox(
                    scenario_id=normalized_scenario_id,
                    artifact_code=artifact_code,
                    artifact_language=normalized_language,
                )
                raw_checks = payload.get("runner_checks")
                if not isinstance(raw_checks, list):
                    return [], None
                runner_checks = [
                    {
                        "check_key": str(item.get("check_key") or "").strip(),
                        "title": _coding_task_runner_title(
                            scenario_id=normalized_scenario_id,
                            check_key=str(item.get("check_key") or "").strip(),
                            report_language=report_language,
                        ),
                        "status": "passed" if item.get("passed") else "missed",
                        "score": 10.0 if item.get("passed") else 0.0,
                        "evidence": str(item.get("details") or "").strip() or None,
                    }
                    for item in raw_checks
                    if isinstance(item, dict) and str(item.get("check_key") or "").strip()
                ]
                runner_score = payload.get("runner_score")
                return runner_checks, round(float(runner_score), 1) if isinstance(runner_score, (int, float)) else None
            except Exception:
                logger.warning("Coding task sandbox runner failed, falling back to local runner", exc_info=True)

        with tempfile.NamedTemporaryFile("w", suffix="_coding_runner.py", delete=False) as handle:
            handle.write(wrapper)
            temp_path = handle.name

        completed = subprocess.run(
            [sys.executable, temp_path],
            input=json.dumps(
                {
                    "scenario_id": normalized_scenario_id,
                    "code": artifact_code,
                }
            ),
            text=True,
            capture_output=True,
            timeout=_CODING_TASK_RUNNER_TIMEOUT_SECONDS,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or completed.stdout or "runner failed").strip()[:400])
        payload = json.loads(completed.stdout or "{}")
        raw_checks = payload.get("runner_checks")
        if not isinstance(raw_checks, list):
            return [], None
        runner_checks = [
            {
                "check_key": str(item.get("check_key") or "").strip(),
                "title": _coding_task_runner_title(
                    scenario_id=normalized_scenario_id,
                    check_key=str(item.get("check_key") or "").strip(),
                    report_language=report_language,
                ),
                "status": "passed" if item.get("passed") else "missed",
                "score": 10.0 if item.get("passed") else 0.0,
                "evidence": str(item.get("details") or "").strip() or None,
            }
            for item in raw_checks
            if isinstance(item, dict) and str(item.get("check_key") or "").strip()
        ]
        runner_score = payload.get("runner_score")
        return runner_checks, round(float(runner_score), 1) if isinstance(runner_score, (int, float)) else None
    except subprocess.TimeoutExpired:
        return [
            {
                "check_key": "runner_execution_timeout",
                "title": _coding_task_runner_title(
                    scenario_id=normalized_scenario_id,
                    check_key="runner_execution_timeout",
                    report_language=report_language,
                ),
                "status": "missed",
                "score": 0.0,
                "evidence": "timeout",
            }
        ], 0.0
    except Exception as exc:
        return [
            {
                "check_key": "runner_execution_failed",
                "title": _coding_task_runner_title(
                    scenario_id=normalized_scenario_id,
                    check_key="runner_execution_failed",
                    report_language=report_language,
                ),
                "status": "missed",
                "score": 0.0,
                "evidence": str(exc)[:240] or None,
            }
        ], 0.0
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def _run_coding_task_runner_in_sandbox(
    *,
    scenario_id: str,
    artifact_code: str,
    artifact_language: str,
) -> dict:
    base_url = settings.SANDBOX_SERVICE_URL.rstrip("/")
    with httpx.Client(base_url=base_url, timeout=_CODING_TASK_RUNNER_TIMEOUT_SECONDS + 1.0) as client:
        response = client.post(
            "/v1/coding/python",
            json={
                "scenario_id": scenario_id,
                "language": artifact_language,
                "code": artifact_code,
                "timeout_seconds": _CODING_TASK_RUNNER_TIMEOUT_SECONDS,
            },
        )

    if response.is_success:
        payload = response.json()
        if isinstance(payload, dict):
            return payload
        raise RuntimeError("sandbox returned invalid payload")

    detail = _extract_sandbox_error_detail(response)
    raise RuntimeError(detail)


def _run_sql_live_validation_in_sandbox(
    *,
    scenario_id: str,
    query_text: str,
) -> dict:
    base_url = settings.SANDBOX_SERVICE_URL.rstrip("/")
    with httpx.Client(base_url=base_url, timeout=_SQL_LIVE_VALIDATION_TIMEOUT_SECONDS + 1.0) as client:
        response = client.post(
            "/v1/sql/validate",
            json={
                "scenario_id": scenario_id,
                "query": query_text,
                "timeout_seconds": _SQL_LIVE_VALIDATION_TIMEOUT_SECONDS,
            },
        )

    if response.is_success:
        payload = response.json()
        if isinstance(payload, dict):
            return payload
        raise RuntimeError("sandbox returned invalid payload")

    detail = _extract_sandbox_error_detail(response)
    raise RuntimeError(detail)


def _extract_sandbox_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except Exception:
        payload = None
    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("message") or payload.get("error")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
    body = response.text.strip()
    return body or f"HTTP {response.status_code}"


def _build_coding_task_evaluation(
    interview_meta: dict | None,
    per_question_analysis: list[dict],
    message_history: list[dict] | None,
    report_language: str = "ru",
) -> dict | None:
    interview_meta = interview_meta or {}
    module_type = str(interview_meta.get("module_type") or "").strip().lower()
    if module_type != "coding_task":
        return None

    stage_plan = (
        list(interview_meta.get("module_stage_plan", []) or [])
        if isinstance(interview_meta.get("module_stage_plan"), list)
        else []
    )
    if not stage_plan:
        return None

    question_history = (
        list(interview_meta.get("module_question_history", []) or [])
        if isinstance(interview_meta.get("module_question_history"), list)
        else []
    )
    stage_map: dict[int, dict[str, str | None]] = {}
    for item in question_history:
        if not isinstance(item, dict):
            continue
        assistant_turn = _to_int(item.get("assistant_turn"), 0)
        if assistant_turn <= 0:
            continue
        stage_map[assistant_turn] = {
            "stage_key": str(item.get("stage_key") or "").strip() or None,
            "stage_title": str(item.get("stage_title") or "").strip() or None,
        }

    questions_by_stage: dict[str, list[dict]] = {}
    for question in per_question_analysis:
        if not isinstance(question, dict):
            continue
        question_number = _to_int(question.get("question_number"), 0)
        if question_number <= 0:
            continue
        stage_key = str(stage_map.get(question_number, {}).get("stage_key") or "").strip()
        if stage_key:
            questions_by_stage.setdefault(stage_key, []).append(question)

    answers_by_stage = _build_stage_answer_map(interview_meta, message_history)
    stages: list[dict] = []
    stage_scores: dict[str, float | None] = {}
    artifact_payload = (
        interview_meta.get("coding_task_artifact")
        if isinstance(interview_meta.get("coding_task_artifact"), dict)
        else {}
    )
    artifact_code = str(artifact_payload.get("code") or "").strip() or None
    artifact_language = str(artifact_payload.get("language") or "").strip() or None
    implementation_answers = list(answers_by_stage.get("implementation", []))
    if artifact_code:
        implementation_answers = [artifact_code, *implementation_answers]
    implementation_code_excerpt = _extract_code_excerpt(implementation_answers)

    for stage in stage_plan:
        if not isinstance(stage, dict):
            continue
        stage_key = str(stage.get("stage_key") or "").strip()
        stage_title = str(stage.get("stage_title") or "").strip()
        if not stage_key:
            continue
        scored = _score_system_design_question_block(
            questions_by_stage.get(stage_key, []),
            _CODING_TASK_STAGE_KEYWORDS.get(stage_key, ()),
        )
        stage_score = scored["stage_score"] if isinstance(scored["stage_score"], (int, float)) else None

        stage_answers = implementation_answers if stage_key == "implementation" else answers_by_stage.get(stage_key, [])
        code_signal = 0.0
        if stage_key == "implementation" and stage_answers:
            code_hits = sum(
                1
                for answer in stage_answers
                if any(hint in answer for hint in _CODING_TASK_CODE_HINTS)
            )
            code_signal = min(10.0, 4.0 + code_hits * 2.0)
            if stage_score is None:
                stage_score = round(code_signal, 1)
            else:
                stage_score = round(min(10.0, (stage_score * 0.75) + (code_signal * 0.25)), 1)

        stage_scores[stage_key] = stage_score
        evidence_items = list(scored["evidence_items"])
        if stage_key == "implementation" and implementation_code_excerpt:
            evidence_items = [implementation_code_excerpt[:240], *evidence_items]
        stages.append(
            {
                "stage_key": stage_key,
                "stage_title": stage_title or stage_key.replace("_", " ").title(),
                "question_numbers": scored["question_numbers"],
                "average_answer_quality": scored["average_answer_quality"],
                "stage_score": stage_score,
                "evidence_items": evidence_items[:3],
            }
        )

    weighted_scores = [
        (float(score), weight)
        for stage_key, weight in _CODING_TASK_STAGE_WEIGHTS.items()
        for score in [stage_scores.get(stage_key)]
        if isinstance(score, (int, float))
    ]
    overall_score = None
    if weighted_scores:
        total_weight = sum(weight for _, weight in weighted_scores)
        if total_weight > 0:
            overall_score = round(
                sum(score * weight for score, weight in weighted_scores) / total_weight,
                1,
            )

    review_questions = [
        *questions_by_stage.get("task_brief", []),
        *questions_by_stage.get("review", []),
    ]
    correctness_scored = _score_system_design_question_block(
        review_questions,
        ("edge", "case", "test", "assert", "invalid", "error"),
    )
    correctness_score = (
        correctness_scored["stage_score"]
        if isinstance(correctness_scored["stage_score"], (int, float))
        else None
    )

    implementation_score = stage_scores.get("implementation")
    has_code_submission = bool(implementation_code_excerpt)
    code_signal_score = None
    if implementation_answers:
        signal_hits = sum(
            1
            for answer in implementation_answers
            if any(hint in answer for hint in _CODING_TASK_CODE_HINTS)
        )
        code_signal_score = round(min(10.0, 3.0 + signal_hits * 2.5), 1)

    scenario_id = str(interview_meta.get("module_scenario_id") or "").strip() or None
    coverage_checks, coverage_score = _build_coding_task_coverage_checks(
        scenario_id=scenario_id,
        answers_by_stage=answers_by_stage,
        implementation_excerpt=implementation_code_excerpt,
        report_language=report_language,
    )
    stack_checks, stack_score = _build_coding_task_stack_checks(
        scenario_id=scenario_id,
        answers_by_stage=answers_by_stage,
        implementation_excerpt=implementation_code_excerpt,
        report_language=report_language,
    )
    runner_checks, runner_score = _build_coding_task_runner_checks(
        scenario_id=scenario_id,
        artifact_code=artifact_code,
        artifact_language=artifact_language,
        report_language=report_language,
    )
    strengths, gaps, next_steps = _build_coding_task_review_notes(
        report_language=report_language,
        stack_focus=str(interview_meta.get("module_stack_focus") or "").strip() or None,
        preferred_language=str(interview_meta.get("module_preferred_language") or "").strip() or None,
        coverage_checks=coverage_checks,
        stack_checks=stack_checks,
        runner_checks=runner_checks,
        implementation_score=implementation_score if isinstance(implementation_score, (int, float)) else None,
        review_score=stage_scores.get("review") if isinstance(stage_scores.get("review"), (int, float)) else None,
        correctness_score=correctness_score if isinstance(correctness_score, (int, float)) else None,
    )

    rubric_scores = [
        {
            "rubric_key": "problem_breakdown",
            "score": stage_scores.get("task_brief"),
        },
        {
            "rubric_key": "implementation_quality",
            "score": implementation_score,
        },
        {
            "rubric_key": "correctness_testing",
            "score": correctness_score,
        },
        {
            "rubric_key": "code_communication",
            "score": stage_scores.get("review"),
        },
        {
            "rubric_key": "functional_coverage",
            "score": coverage_score,
        },
        {
            "rubric_key": "stack_fluency",
            "score": stack_score,
        },
    ]
    if runner_score is not None:
        rubric_scores.append(
            {
                "rubric_key": "hidden_test_execution",
                "score": runner_score,
            }
        )

    if overall_score is not None:
        weighted_parts = [(overall_score, 0.7)]
        if coverage_score is not None:
            weighted_parts.append((coverage_score, 0.15))
        if stack_score is not None:
            weighted_parts.append((stack_score, 0.1))
        if runner_score is not None:
            weighted_parts.append((runner_score, 0.05))
        total_weight = sum(weight for _, weight in weighted_parts)
        if total_weight > 0:
            overall_score = round(sum(score * weight for score, weight in weighted_parts) / total_weight, 1)

    return {
        "module_title": str(interview_meta.get("module_title") or "").strip() or None,
        "scenario_id": scenario_id,
        "scenario_title": str(interview_meta.get("module_scenario_title") or "").strip() or None,
        "scenario_prompt": str(interview_meta.get("module_scenario_prompt") or "").strip() or None,
        "stack_focus": str(interview_meta.get("module_stack_focus") or "").strip() or None,
        "preferred_language": str(interview_meta.get("module_preferred_language") or "").strip() or None,
        "workspace_hint": str(interview_meta.get("module_workspace_hint") or "").strip() or None,
        "stage_count": len(stages),
        "overall_score": overall_score,
        "rubric_scores": rubric_scores,
        "stages": stages,
        "implementation_excerpt": implementation_code_excerpt,
        "has_code_submission": has_code_submission,
        "code_signal_score": code_signal_score,
        "coverage_score": coverage_score,
        "coverage_checks": coverage_checks,
        "stack_score": stack_score,
        "stack_checks": stack_checks,
        "runner_score": runner_score,
        "runner_checks": runner_checks,
        "strengths": strengths,
        "gaps": gaps,
        "next_steps": next_steps,
    }


def _build_sql_live_evaluation(
    interview_meta: dict | None,
    per_question_analysis: list[dict],
    message_history: list[dict] | None,
    report_language: str = "ru",
) -> dict | None:
    interview_meta = interview_meta or {}
    module_type = str(interview_meta.get("module_type") or "").strip().lower()
    if module_type != "sql_live":
        return None

    stage_plan = (
        list(interview_meta.get("module_stage_plan", []) or [])
        if isinstance(interview_meta.get("module_stage_plan"), list)
        else []
    )
    if not stage_plan:
        return None

    question_history = (
        list(interview_meta.get("module_question_history", []) or [])
        if isinstance(interview_meta.get("module_question_history"), list)
        else []
    )
    stage_map: dict[int, dict[str, str | None]] = {}
    for item in question_history:
        if not isinstance(item, dict):
            continue
        assistant_turn = _to_int(item.get("assistant_turn"), 0)
        if assistant_turn <= 0:
            continue
        stage_map[assistant_turn] = {
            "stage_key": str(item.get("stage_key") or "").strip() or None,
            "stage_title": str(item.get("stage_title") or "").strip() or None,
        }

    questions_by_stage: dict[str, list[dict]] = {}
    for question in per_question_analysis:
        if not isinstance(question, dict):
            continue
        question_number = _to_int(question.get("question_number"), 0)
        if question_number <= 0:
            continue
        stage_key = str(stage_map.get(question_number, {}).get("stage_key") or "").strip()
        if stage_key:
            questions_by_stage.setdefault(stage_key, []).append(question)

    answers_by_stage = _build_stage_answer_map(interview_meta, message_history)
    artifact_payload = (
        interview_meta.get("coding_task_artifact")
        if isinstance(interview_meta.get("coding_task_artifact"), dict)
        else {}
    )
    query_text = str(artifact_payload.get("code") or "").strip() or None
    query_answers = list(answers_by_stage.get("query_authoring", []))
    if query_text:
        query_answers = [query_text, *query_answers]
    query_excerpt = _extract_sql_excerpt(query_answers)

    stages: list[dict] = []
    stage_scores: dict[str, float | None] = {}
    for stage in stage_plan:
        if not isinstance(stage, dict):
            continue
        stage_key = str(stage.get("stage_key") or "").strip()
        stage_title = str(stage.get("stage_title") or "").strip()
        if not stage_key:
            continue
        scored = _score_system_design_question_block(
            questions_by_stage.get(stage_key, []),
            _SQL_LIVE_STAGE_KEYWORDS.get(stage_key, ()),
        )
        stage_score = scored["stage_score"] if isinstance(scored["stage_score"], (int, float)) else None
        evidence_items = list(scored["evidence_items"])
        if stage_key == "query_authoring" and query_excerpt:
            evidence_items = [query_excerpt[:240], *evidence_items]
        stage_scores[stage_key] = stage_score
        stages.append(
            {
                "stage_key": stage_key,
                "stage_title": stage_title or stage_key.replace("_", " ").title(),
                "question_numbers": scored["question_numbers"],
                "average_answer_quality": scored["average_answer_quality"],
                "stage_score": stage_score,
                "evidence_items": evidence_items[:3],
            }
        )

    weighted_scores = [
        (float(score), weight)
        for stage_key, weight in _SQL_LIVE_STAGE_WEIGHTS.items()
        for score in [stage_scores.get(stage_key)]
        if isinstance(score, (int, float))
    ]
    overall_score = None
    if weighted_scores:
        total_weight = sum(weight for _, weight in weighted_scores)
        if total_weight > 0:
            overall_score = round(
                sum(score * weight for score, weight in weighted_scores) / total_weight,
                1,
            )

    scenario_id = str(interview_meta.get("module_scenario_id") or "").strip() or None
    validation_checks, validation_score = _build_sql_live_validation_checks(
        scenario_id=scenario_id,
        query_text=query_text,
        report_language=report_language,
    )
    if overall_score is not None and validation_score is not None:
        overall_score = round((overall_score * 0.8) + (validation_score * 0.2), 1)

    return {
        "module_title": str(interview_meta.get("module_title") or "").strip() or None,
        "scenario_id": scenario_id,
        "scenario_title": str(interview_meta.get("module_scenario_title") or "").strip() or None,
        "scenario_prompt": str(interview_meta.get("module_scenario_prompt") or "").strip() or None,
        "stage_count": len(stages),
        "overall_score": overall_score,
        "validation_score": validation_score,
        "rubric_scores": [
            {"rubric_key": "schema_planning", "score": stage_scores.get("schema_review")},
            {"rubric_key": "query_construction", "score": stage_scores.get("query_authoring")},
            {"rubric_key": "validation_reasoning", "score": stage_scores.get("result_review")},
            {"rubric_key": "query_correctness", "score": validation_score},
        ],
        "validation_checks": validation_checks,
        "stages": stages,
        "query_excerpt": query_excerpt,
        "has_query_submission": bool(query_excerpt),
    }


def _build_written_communication_evaluation(
    interview_meta: dict | None,
    per_question_analysis: list[dict],
    message_history: list[dict] | None,
    report_language: str = "ru",
) -> dict | None:
    interview_meta = interview_meta or {}
    module_type = str(interview_meta.get("module_type") or "").strip().lower()
    if module_type != "written_communication":
        return None

    stage_plan = (
        list(interview_meta.get("module_stage_plan", []) or [])
        if isinstance(interview_meta.get("module_stage_plan"), list)
        else []
    )
    if not stage_plan:
        return None

    question_history = (
        list(interview_meta.get("module_question_history", []) or [])
        if isinstance(interview_meta.get("module_question_history"), list)
        else []
    )
    stage_map: dict[int, dict[str, str | None]] = {}
    for item in question_history:
        if not isinstance(item, dict):
            continue
        assistant_turn = _to_int(item.get("assistant_turn"), 0)
        if assistant_turn <= 0:
            continue
        stage_map[assistant_turn] = {
            "stage_key": str(item.get("stage_key") or "").strip() or None,
            "stage_title": str(item.get("stage_title") or "").strip() or None,
        }

    questions_by_stage: dict[str, list[dict]] = {}
    for question in per_question_analysis:
        if not isinstance(question, dict):
            continue
        question_number = _to_int(question.get("question_number"), 0)
        if question_number <= 0:
            continue
        stage_key = str(stage_map.get(question_number, {}).get("stage_key") or "").strip()
        if stage_key:
            questions_by_stage.setdefault(stage_key, []).append(question)

    answers_by_stage = _build_stage_answer_map(interview_meta, message_history)
    artifact_payload = (
        interview_meta.get("written_artifact")
        if isinstance(interview_meta.get("written_artifact"), dict)
        else {}
    )
    artifact_text = str(artifact_payload.get("content") or "").strip() or None
    drafting_answers = list(answers_by_stage.get("drafting", []))
    if artifact_text:
        drafting_answers = [artifact_text, *drafting_answers]
    writing_excerpt = _extract_written_excerpt(drafting_answers)

    stages: list[dict] = []
    stage_scores: dict[str, float | None] = {}
    for stage in stage_plan:
        if not isinstance(stage, dict):
            continue
        stage_key = str(stage.get("stage_key") or "").strip()
        stage_title = str(stage.get("stage_title") or "").strip()
        if not stage_key:
            continue
        scored = _score_system_design_question_block(
            questions_by_stage.get(stage_key, []),
            _WRITTEN_COMMUNICATION_STAGE_KEYWORDS.get(stage_key, ()),
        )
        stage_score = scored["stage_score"] if isinstance(scored["stage_score"], (int, float)) else None
        evidence_items = list(scored["evidence_items"])
        if stage_key == "drafting" and writing_excerpt:
            evidence_items = [writing_excerpt[:240], *evidence_items]
        stage_scores[stage_key] = stage_score
        stages.append(
            {
                "stage_key": stage_key,
                "stage_title": stage_title or stage_key.replace("_", " ").title(),
                "question_numbers": scored["question_numbers"],
                "average_answer_quality": scored["average_answer_quality"],
                "stage_score": stage_score,
                "evidence_items": evidence_items[:3],
            }
        )

    weighted_scores = [
        (float(score), weight)
        for stage_key, weight in _WRITTEN_COMMUNICATION_STAGE_WEIGHTS.items()
        for score in [stage_scores.get(stage_key)]
        if isinstance(score, (int, float))
    ]
    base_stage_score = None
    if weighted_scores:
        total_weight = sum(weight for _, weight in weighted_scores)
        if total_weight > 0:
            base_stage_score = round(
                sum(score * weight for score, weight in weighted_scores) / total_weight,
                1,
            )

    clarity_score = None
    structure_score = None
    audience_awareness_score = None
    strengths: list[str] = []
    gaps: list[str] = []
    next_steps: list[str] = []

    if writing_excerpt:
        lowered = writing_excerpt.lower()
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", writing_excerpt) if part.strip()]
        lines = [part.strip() for part in writing_excerpt.splitlines() if part.strip()]
        sentences = [part.strip() for part in re.split(r"[.!?]+", writing_excerpt) if part.strip()]
        word_count = len(re.findall(r"[a-zA-Zа-яА-Я0-9_+#.-]+", writing_excerpt))

        clarity_hits = sum(1 for hint in _WRITTEN_COMMUNICATION_CLARITY_HINTS if hint in lowered)
        audience_hits = sum(1 for hint in _WRITTEN_COMMUNICATION_AUDIENCE_HINTS if hint in lowered)
        structure_hits = 0
        if len(paragraphs) >= 2:
            structure_hits += 2
        if len(lines) >= 3:
            structure_hits += 1
        if any(line.endswith(":") for line in lines[:4]):
            structure_hits += 1
        if any(marker in lowered for marker in ("- ", "* ", "1.", "2.", "status", "impact", "next step", "ask", "контекст", "статус", "следующие шаги", "запрос")):
            structure_hits += 2

        clarity_score = min(10.0, 4.0 + (clarity_hits * 0.8) + (1.0 if 50 <= word_count <= 260 else 0.0))
        structure_score = min(10.0, 4.0 + (structure_hits * 1.0))
        audience_awareness_score = min(10.0, 4.0 + (audience_hits * 0.9) + (1.0 if len(sentences) >= 3 else 0.0))

        if isinstance(stage_scores.get("editing"), (int, float)):
            clarity_score = round((clarity_score * 0.65) + (float(stage_scores["editing"]) * 0.35), 1)
        else:
            clarity_score = round(clarity_score, 1)

        if isinstance(stage_scores.get("drafting"), (int, float)):
            structure_score = round((structure_score * 0.65) + (float(stage_scores["drafting"]) * 0.35), 1)
        else:
            structure_score = round(structure_score, 1)

        alignment_stage = stage_scores.get("brief_alignment")
        alignment_score = float(alignment_stage) if isinstance(alignment_stage, (int, float)) else None
        if alignment_score is not None:
            audience_awareness_score = round((audience_awareness_score * 0.6) + (alignment_score * 0.4), 1)
        else:
            audience_awareness_score = round(audience_awareness_score, 1)

        if clarity_score >= 7.0:
            strengths.append(
                "Keeps the message clear and actionable instead of burying the decision."
                if report_language == "en"
                else "Держит сообщение ясным и action-oriented, не пряча ключевое решение в деталях."
            )
        else:
            gaps.append(
                "Key actions or conclusions are still too easy to miss in the draft."
                if report_language == "en"
                else "Ключевые действия или выводы в черновике пока слишком легко упустить."
            )
            next_steps.append(
                "Move the core decision and next step closer to the opening and cut weaker filler phrases."
                if report_language == "en"
                else "Перенести главное решение и следующий шаг ближе к началу и убрать слабые filler-фразы."
            )

        if structure_score >= 7.0:
            strengths.append(
                "Uses a scan-friendly structure that separates context, impact, and next steps."
                if report_language == "en"
                else "Использует scan-friendly структуру с явным разделением контекста, impact и следующих шагов."
            )
        else:
            gaps.append(
                "The structure could be easier to scan for a busy stakeholder audience."
                if report_language == "en"
                else "Структуру стоит сделать проще для быстрого чтения занятой stakeholder-аудиторией."
            )
            next_steps.append(
                "Introduce explicit sections or bullets so status, impact, and ask are visually separate."
                if report_language == "en"
                else "Добавить явные секции или bullets, чтобы статус, impact и запрос читались отдельно."
            )

        if audience_awareness_score >= 7.0:
            strengths.append(
                "Adjusts the writing to the audience instead of sounding like an internal engineering note."
                if report_language == "en"
                else "Подстраивает текст под аудиторию, а не звучит как внутренняя инженерная заметка для всех подряд."
            )
        else:
            gaps.append(
                "Audience needs and likely objections are not yet addressed explicitly enough."
                if report_language == "en"
                else "Потребности аудитории и ожидаемые возражения пока отражены недостаточно явно."
            )
            next_steps.append(
                "Call out who the note is for, what they need to decide, and what risk matters most to them."
                if report_language == "en"
                else "Явно обозначить, для кого написан текст, какое решение от них требуется и какой риск для них главный."
            )

    overall_parts = []
    if base_stage_score is not None:
        overall_parts.append((base_stage_score, 0.6))
    if clarity_score is not None:
        overall_parts.append((clarity_score, 0.15))
    if structure_score is not None:
        overall_parts.append((structure_score, 0.15))
    if audience_awareness_score is not None:
        overall_parts.append((audience_awareness_score, 0.1))
    overall_score = None
    if overall_parts:
        total_weight = sum(weight for _, weight in overall_parts)
        if total_weight > 0:
            overall_score = round(sum(score * weight for score, weight in overall_parts) / total_weight, 1)

    return {
        "module_title": str(interview_meta.get("module_title") or "").strip() or None,
        "scenario_id": str(interview_meta.get("module_scenario_id") or "").strip() or None,
        "scenario_title": str(interview_meta.get("module_scenario_title") or "").strip() or None,
        "scenario_prompt": str(interview_meta.get("module_scenario_prompt") or "").strip() or None,
        "workspace_hint": str(interview_meta.get("module_workspace_hint") or "").strip() or None,
        "stage_count": len(stages),
        "overall_score": overall_score,
        "clarity_score": clarity_score,
        "structure_score": structure_score,
        "audience_awareness_score": audience_awareness_score,
        "rubric_scores": [
            {"rubric_key": "audience_alignment", "score": audience_awareness_score if audience_awareness_score is not None else stage_scores.get("brief_alignment")},
            {"rubric_key": "message_structure", "score": structure_score},
            {"rubric_key": "clarity_actionability", "score": clarity_score},
            {"rubric_key": "revision_judgment", "score": stage_scores.get("editing")},
        ],
        "stages": stages,
        "writing_excerpt": writing_excerpt,
        "has_draft_submission": bool(writing_excerpt),
        "strengths": strengths[:3],
        "gaps": gaps[:3],
        "next_steps": next_steps[:3],
    }


def _behavioral_stage_signal_score(
    *,
    texts: list[str],
    stage_score: float | None,
    patterns: tuple[str, ...],
    base_score: float,
) -> float | None:
    searchable = "\n".join(str(text or "").lower() for text in texts if str(text or "").strip())
    if not searchable and not isinstance(stage_score, (int, float)):
        return None

    hint_hits = sum(1 for pattern in patterns if pattern in searchable)
    computed_score = min(10.0, base_score + (hint_hits * 0.9)) if searchable else None
    if isinstance(stage_score, (int, float)) and computed_score is not None:
        return round((float(stage_score) * 0.7) + (computed_score * 0.3), 1)
    if isinstance(stage_score, (int, float)):
        return round(float(stage_score), 1)
    if computed_score is not None:
        return round(computed_score, 1)
    return None


def _build_behavioral_interview_evaluation(
    interview_meta: dict | None,
    per_question_analysis: list[dict],
    message_history: list[dict] | None,
    report_language: str = "ru",
) -> dict | None:
    interview_meta = interview_meta or {}
    module_type = str(interview_meta.get("module_type") or "").strip().lower()
    if module_type != "behavioral_interview":
        return None

    stage_plan = (
        list(interview_meta.get("module_stage_plan", []) or [])
        if isinstance(interview_meta.get("module_stage_plan"), list)
        else []
    )
    if not stage_plan:
        return None

    question_history = (
        list(interview_meta.get("module_question_history", []) or [])
        if isinstance(interview_meta.get("module_question_history"), list)
        else []
    )
    stage_map: dict[int, dict[str, str | None]] = {}
    for item in question_history:
        if not isinstance(item, dict):
            continue
        assistant_turn = _to_int(item.get("assistant_turn"), 0)
        if assistant_turn <= 0:
            continue
        stage_map[assistant_turn] = {
            "stage_key": str(item.get("stage_key") or "").strip() or None,
            "stage_title": str(item.get("stage_title") or "").strip() or None,
        }

    questions_by_stage: dict[str, list[dict]] = {}
    for question in per_question_analysis:
        if not isinstance(question, dict):
            continue
        question_number = _to_int(question.get("question_number"), 0)
        if question_number <= 0:
            continue
        stage_key = str(stage_map.get(question_number, {}).get("stage_key") or "").strip()
        if stage_key:
            questions_by_stage.setdefault(stage_key, []).append(question)

    answers_by_stage = _build_stage_answer_map(interview_meta, message_history)
    stages: list[dict] = []
    stage_scores: dict[str, float | None] = {}
    for stage in stage_plan:
        if not isinstance(stage, dict):
            continue
        stage_key = str(stage.get("stage_key") or "").strip()
        stage_title = str(stage.get("stage_title") or "").strip()
        if not stage_key:
            continue
        scored = _score_system_design_question_block(
            questions_by_stage.get(stage_key, []),
            _BEHAVIORAL_INTERVIEW_STAGE_KEYWORDS.get(stage_key, ()),
        )
        stage_score = scored["stage_score"] if isinstance(scored["stage_score"], (int, float)) else None
        stage_answers = list(answers_by_stage.get(stage_key, []))
        if stage_answers and stage_score is None:
            stage_score = _behavioral_stage_signal_score(
                texts=stage_answers,
                stage_score=None,
                patterns=_BEHAVIORAL_INTERVIEW_STAGE_KEYWORDS.get(stage_key, ()),
                base_score=4.5,
            )
        stage_scores[stage_key] = stage_score
        evidence_items = list(scored["evidence_items"])
        if stage_answers:
            fallback_evidence = _find_matching_evidence(stage_answers, _BEHAVIORAL_INTERVIEW_STAGE_KEYWORDS.get(stage_key, ()))
            if fallback_evidence:
                evidence_items = [fallback_evidence, *evidence_items]
        stages.append(
            {
                "stage_key": stage_key,
                "stage_title": stage_title or stage_key.replace("_", " ").title(),
                "question_numbers": scored["question_numbers"],
                "average_answer_quality": scored["average_answer_quality"],
                "stage_score": stage_score,
                "evidence_items": evidence_items[:3],
            }
        )

    weighted_scores = [
        (float(score), weight)
        for stage_key, weight in _BEHAVIORAL_INTERVIEW_STAGE_WEIGHTS.items()
        for score in [stage_scores.get(stage_key)]
        if isinstance(score, (int, float))
    ]
    overall_score = None
    if weighted_scores:
        total_weight = sum(weight for _, weight in weighted_scores)
        if total_weight > 0:
            overall_score = round(
                sum(score * weight for score, weight in weighted_scores) / total_weight,
                1,
            )

    ownership_score = (
        round(float(stage_scores["ownership"]), 1)
        if isinstance(stage_scores.get("ownership"), (int, float))
        else None
    )
    collaboration_score = _behavioral_stage_signal_score(
        texts=list(answers_by_stage.get("collaboration", [])),
        stage_score=stage_scores.get("collaboration"),
        patterns=_BEHAVIORAL_INTERVIEW_COLLABORATION_HINTS,
        base_score=4.2,
    )
    leadership_score = _behavioral_stage_signal_score(
        texts=list(answers_by_stage.get("leadership", [])),
        stage_score=stage_scores.get("leadership"),
        patterns=_BEHAVIORAL_INTERVIEW_LEADERSHIP_HINTS,
        base_score=4.4,
    )
    reflection_score = _behavioral_stage_signal_score(
        texts=list(answers_by_stage.get("reflection", [])),
        stage_score=stage_scores.get("reflection"),
        patterns=_BEHAVIORAL_INTERVIEW_REFLECTION_HINTS,
        base_score=4.0,
    )

    overall_parts = []
    if overall_score is not None:
        overall_parts.append((overall_score, 0.7))
    if collaboration_score is not None:
        overall_parts.append((collaboration_score, 0.1))
    if leadership_score is not None:
        overall_parts.append((leadership_score, 0.1))
    if reflection_score is not None:
        overall_parts.append((reflection_score, 0.1))
    if overall_parts:
        total_weight = sum(weight for _, weight in overall_parts)
        if total_weight > 0:
            overall_score = round(sum(score * weight for score, weight in overall_parts) / total_weight, 1)

    strengths: list[str] = []
    gaps: list[str] = []
    next_steps: list[str] = []
    is_en = _normalized_report_language(report_language) == "en"

    def _append_unique(target: list[str], message: str) -> None:
        text = str(message or "").strip()
        if text and text not in target:
            target.append(text)

    if ownership_score is not None and ownership_score >= 7.0:
        _append_unique(
            strengths,
            "Shows clear ownership under ambiguity and names personal judgment calls."
            if is_en
            else "Показывает явный ownership в условиях неопределённости и называет собственные judgment calls.",
        )
    else:
        _append_unique(
            gaps,
            "Ownership examples stay too generic and do not show enough personal decision weight."
            if is_en
            else "Примеры ownership пока слишком общие и не показывают личный вес принятого решения.",
        )
        _append_unique(
            next_steps,
            "Answer with one ambiguous situation, the risk you personally owned, and the option you rejected."
            if is_en
            else "Разбирать один неясный кейс через риск, который вы лично взяли на себя, и альтернативу, от которой отказались.",
        )

    if collaboration_score is not None and collaboration_score >= 7.0:
        _append_unique(
            strengths,
            "Navigates stakeholder tension with concrete alignment moves instead of abstract teamwork language."
            if is_en
            else "Проходит через stakeholder-напряжение через конкретные шаги выравнивания, а не общие слова про teamwork.",
        )
    else:
        _append_unique(
            gaps,
            "Collaboration answers do not yet show enough conflict handling or stakeholder calibration."
            if is_en
            else "Ответы про collaboration пока недостаточно показывают работу с конфликтом и калибровку стейкхолдеров.",
        )
        _append_unique(
            next_steps,
            "Name the tension, what you said or changed, and the signal that told you alignment improved."
            if is_en
            else "Явно называть источник напряжения, что именно вы сказали или изменили, и по какому сигналу поняли, что alignment улучшился.",
        )

    if leadership_score is not None and leadership_score >= 7.0:
        _append_unique(
            strengths,
            "Demonstrates influence and decision framing without relying only on formal authority."
            if is_en
            else "Показывает влияние и framing решения без опоры только на формальную власть.",
        )
    else:
        _append_unique(
            gaps,
            "Leadership examples need clearer evidence of influence, prioritization, or clarity under pressure."
            if is_en
            else "Примерам лидерства не хватает более явных признаков влияния, приоритизации или наведения ясности под давлением.",
        )
        _append_unique(
            next_steps,
            "Show where people resisted, how you reframed the decision, and what changed after your intervention."
            if is_en
            else "Показывать, где люди сопротивлялись, как вы переупаковали решение и что изменилось после вашего вмешательства.",
        )

    if reflection_score is not None and reflection_score >= 7.0:
        _append_unique(
            strengths,
            "Reflection is concrete: feedback, mistake, and changed behavior are tied together."
            if is_en
            else "Рефлексия конкретная: feedback, ошибка и изменившееся поведение связаны между собой.",
        )
    else:
        _append_unique(
            gaps,
            "Reflection is still light on what actually changed after the mistake or feedback."
            if is_en
            else "Рефлексия пока слабо показывает, что именно реально изменилось после ошибки или feedback.",
        )
        _append_unique(
            next_steps,
            "End with the behavior or decision rule that changed and where you reused it later."
            if is_en
            else "Завершать ответ тем, какое поведение или decision rule изменились и где вы потом это переиспользовали.",
        )

    return {
        "module_title": str(interview_meta.get("module_title") or "").strip() or None,
        "scenario_id": str(interview_meta.get("module_scenario_id") or "").strip() or None,
        "scenario_title": str(interview_meta.get("module_scenario_title") or "").strip() or None,
        "scenario_prompt": str(interview_meta.get("module_scenario_prompt") or "").strip() or None,
        "stage_count": len(stages),
        "overall_score": overall_score,
        "ownership_score": ownership_score,
        "collaboration_score": collaboration_score,
        "leadership_score": leadership_score,
        "reflection_score": reflection_score,
        "rubric_scores": [
            {"rubric_key": "ownership_judgment", "score": ownership_score},
            {"rubric_key": "collaboration_navigation", "score": collaboration_score},
            {"rubric_key": "leadership_influence", "score": leadership_score},
            {"rubric_key": "reflection_growth", "score": reflection_score},
        ],
        "stages": stages,
        "strengths": strengths[:3],
        "gaps": gaps[:3],
        "next_steps": next_steps[:3],
    }


def _apply_score_penalties(
    aggregates: dict[str, float],
    answer_metrics: dict,
    competency_scores: list[dict],
    response_consistency: float | None = None,
) -> tuple[dict[str, float], list[str]]:
    """Apply deterministic hard caps on scores to prevent inflation.

    Rules (applied after LLM scoring):
    - Short answers (>30% < 10 words)   → cap all scores at 6
    - Generic answers (>50% low specificity) → cap at 6
    - Weak answers (avg quality < 4.5)  → cap at 5
    - ≥1 competency scored ≤ 4          → cap overall at 6
    - ≥2 competencies scored ≤ 3        → cap overall at 5
    - Low response consistency (<5.0)   → additional consistency cap
    """
    penalties: list[str] = []
    cap = 10.0

    if answer_metrics["short_answer_ratio"] > 0.3:
        cap = min(cap, 6.0)
        penalties.append(
            f"short_answers ({answer_metrics['short_answer_ratio']:.0%} under 10 words): capped_at_6"
        )

    if answer_metrics["low_specificity_ratio"] > 0.5:
        cap = min(cap, 6.0)
        penalties.append(
            f"low_specificity ({answer_metrics['low_specificity_ratio']:.0%} generic): capped_at_6"
        )

    if answer_metrics["avg_answer_quality"] < 4.5:
        cap = min(cap, 5.0)
        penalties.append(
            f"weak_answers (avg quality {answer_metrics['avg_answer_quality']:.1f}/10): capped_at_5"
        )

    critical = [cs for cs in competency_scores if _to_float(cs.get("score"), 5.0) <= 4.0]
    very_critical = [cs for cs in competency_scores if _to_float(cs.get("score"), 5.0) <= 3.0]

    if len(very_critical) >= 2:
        cap = min(cap, 5.0)
        penalties.append(
            f"multiple_critical_weaknesses ({len(very_critical)} competencies ≤3): capped_at_5"
        )
    elif len(critical) >= 1:
        cap = min(cap, 6.0)
        penalties.append(
            f"critical_weakness ({len(critical)} competencies ≤4): overall_capped_at_6"
        )

    consistency = _to_float(response_consistency, 0.0)
    if response_consistency is not None:
        if consistency < 4.0:
            cap = min(cap, 5.5)
            penalties.append(
                f"low_response_consistency ({consistency:.1f}/10): capped_at_5.5"
            )
        elif consistency < 5.0:
            cap = min(cap, 6.0)
            penalties.append(
                f"unstable_response_consistency ({consistency:.1f}/10): capped_at_6.0"
            )

    if cap < 10.0:
        return {k: round(min(v, cap), 1) for k, v in aggregates.items()}, penalties
    return aggregates, penalties


def _question_evidence_confidence(q: dict) -> float:
    """Estimate confidence in a question-level evidence item (0.0–1.0)."""
    quality = max(0.0, min(_to_float(q.get("answer_quality"), 0.0), 10.0))
    specificity = str(q.get("specificity", "low")).lower()
    depth = str(q.get("depth", "none")).lower()
    ai_likelihood = max(0.0, min(_to_float(q.get("ai_likelihood"), 0.0), 1.0))
    evidence_len = len(str(q.get("evidence", "")).strip())

    confidence = quality / 10.0
    confidence += {"high": 0.15, "medium": 0.05}.get(specificity, -0.15)
    confidence += {"expert": 0.2, "strong": 0.15, "adequate": 0.05}.get(depth, -0.15)
    confidence += 0.05 if evidence_len >= 24 else -0.05
    confidence -= ai_likelihood * 0.2
    return max(0.0, min(confidence, 1.0))


def _confidence_verdict_band(overall_confidence: float | None) -> str:
    confidence = max(0.0, min(_to_float(overall_confidence, 0.0), 1.0))
    if confidence < 0.40:
        return "insufficient_data"
    if confidence < 0.70:
        return "needs_human_review"
    return "normal"


def _competency_confidence_sample_cap(sample_count: int) -> float:
    """Avoid 97–100% confidence from a single strong answer."""
    if sample_count <= 0:
        return 0.45
    if sample_count == 1:
        return 0.74
    if sample_count == 2:
        return 0.84
    if sample_count == 3:
        return 0.92
    return 1.0


def _compute_confidence_metrics(
    competency_scores: list[dict],
    per_question_analysis: list[dict],
    *,
    summary_model: dict | None = None,
    interview_meta: dict | None = None,
) -> dict:
    """Compute confidence envelope for report-level and competency-level signals."""
    competency_evidence: dict[str, list[float]] = {}
    question_confidences: list[float] = []
    ai_scores: list[float] = []
    concrete_evidence_count = 0

    for q in per_question_analysis:
        q_conf = _question_evidence_confidence(q)
        question_confidences.append(q_conf)

        ai = q.get("ai_likelihood")
        if ai is not None:
            ai_scores.append(max(0.0, min(_to_float(ai, 0.0), 1.0)))

        evidence_len = len(str(q.get("evidence", "")).strip())
        specificity = str(q.get("specificity", "low")).lower()
        if evidence_len >= 24 and specificity != "low":
            concrete_evidence_count += 1

        for name in q.get("targeted_competencies", []):
            comp_name = str(name).strip()
            if comp_name:
                competency_evidence.setdefault(comp_name, []).append(q_conf)

    competency_confidence: dict[str, float] = {}
    weighted_sum = 0.0
    total_weight = 0.0
    for cs in competency_scores:
        name = str(cs.get("competency", "")).strip()
        if not name:
            continue
        from_questions = competency_evidence.get(name, [])
        base = sum(from_questions) / len(from_questions) if from_questions else 0.45
        evidence_len = len(str(cs.get("evidence", "")).strip())
        evidence_bonus = min(evidence_len / 320.0, 1.0) * 0.1
        sample_cap = _competency_confidence_sample_cap(len(from_questions))
        score = max(0.0, min(base + evidence_bonus, sample_cap))
        competency_confidence[name] = round(score, 2)

        weight = max(_to_float(cs.get("weight"), 0.0), 0.0) or 1.0
        weighted_sum += score * weight
        total_weight += weight

    analyzed_questions = len(per_question_analysis)
    high_conf_q = sum(1 for c in question_confidences if c >= 0.7)
    low_conf_q = sum(1 for c in question_confidences if c < 0.5)
    avg_ai = round(sum(ai_scores) / len(ai_scores), 2) if ai_scores else None
    coverage_ratio = (
        round(concrete_evidence_count / analyzed_questions, 2)
        if analyzed_questions
        else 0.0
    )
    if total_weight > 0:
        overall_conf = weighted_sum / total_weight
    elif question_confidences:
        overall_conf = sum(question_confidences) / len(question_confidences)
    else:
        overall_conf = 0.0

    core_topics = int((summary_model or {}).get("core_topics", 0) or 0)
    validated_topics = int((summary_model or {}).get("validated_topics", 0) or 0)
    validated_ratio = (
        max(0.0, min(validated_topics / max(1, core_topics), 1.0))
        if core_topics > 0
        else 0.0
    )

    strong_answers_count = int((interview_meta or {}).get("strong_answers_count", 0) or 0)
    candidate_answers_count = int((interview_meta or {}).get("candidate_answers_count", 0) or 0)
    inferred_strong_answers = sum(
        1
        for q in per_question_analysis
        if _to_float(q.get("answer_quality"), 0.0) >= 7.0
        and str(q.get("depth", "surface")).lower() in {"strong", "expert"}
    )
    if strong_answers_count <= 0:
        strong_answers_count = inferred_strong_answers
    if candidate_answers_count <= 0:
        candidate_answers_count = analyzed_questions
    strong_answer_ratio = (
        max(0.0, min(strong_answers_count / max(1, candidate_answers_count), 1.0))
        if candidate_answers_count > 0
        else 0.0
    )

    depth_scale = {"none": 0.0, "surface": 0.25, "adequate": 0.55, "strong": 0.8, "expert": 1.0}
    depth_values = [depth_scale.get(str(q.get("depth", "surface")).lower(), 0.25) for q in per_question_analysis]
    avg_case_depth = sum(depth_values) / len(depth_values) if depth_values else 0.0
    qa_completed_cases = len(
        {
            str(item).strip()
            for item in (interview_meta or {}).get("qa_completed_scenarios", [])
            if str(item).strip()
        }
    )
    if qa_completed_cases >= 2:
        avg_case_depth = min(1.0, avg_case_depth + 0.08)
    case_depth_ratio = max(0.0, min(avg_case_depth, 1.0))

    structural_components = [coverage_ratio, strong_answer_ratio, case_depth_ratio]
    if core_topics > 0:
        structural_components.append(validated_ratio)
    structural_signal = sum(structural_components) / len(structural_components) if structural_components else 0.0
    overall_conf = round(max(0.0, min(overall_conf * 0.55 + structural_signal * 0.45, 1.0)), 2)

    reasons: list[str] = []
    if analyzed_questions == 0:
        reasons.append("No per-question evidence extracted; confidence is limited.")
    else:
        if coverage_ratio < 0.5:
            reasons.append("Low concrete evidence coverage reduced confidence.")
        elif coverage_ratio >= 0.75:
            reasons.append("High evidence coverage increased confidence.")

        if low_conf_q >= max(2, analyzed_questions // 2):
            reasons.append("Multiple low-confidence answers reduced certainty.")
        elif high_conf_q >= max(2, analyzed_questions // 2):
            reasons.append("Several answers contained high-confidence evidence.")
        if core_topics > 0 and validated_ratio < 0.5:
            reasons.append("Low validated-topic coverage reduced confidence.")
        elif core_topics > 0 and validated_ratio >= 0.7:
            reasons.append("Validated-topic coverage improved confidence.")
        if strong_answer_ratio < 0.35:
            reasons.append("Too few strong answers lowered confidence.")
        elif strong_answer_ratio >= 0.6:
            reasons.append("High share of strong answers improved confidence.")
        if case_depth_ratio < 0.45:
            reasons.append("Case depth was shallow, lowering confidence.")
        elif case_depth_ratio >= 0.7:
            reasons.append("Case depth improved confidence.")

    if avg_ai is not None and avg_ai >= 0.6:
        reasons.append("High AI-likelihood signal lowered confidence.")
    elif avg_ai is not None and avg_ai <= 0.2 and analyzed_questions > 0:
        reasons.append("Low AI-likelihood signal improved confidence.")

    if not reasons:
        reasons.append("Confidence derived from mixed evidence quality signals.")

    evidence_coverage = {
        "questions_analyzed": analyzed_questions,
        "high_confidence_questions": high_conf_q,
        "low_confidence_questions": low_conf_q,
        "concrete_evidence_ratio": coverage_ratio,
        "validated_topics": validated_topics,
        "validated_topics_ratio": round(validated_ratio, 2),
        "strong_answers_count": strong_answers_count,
        "strong_answer_ratio": round(strong_answer_ratio, 2),
        "case_depth_ratio": round(case_depth_ratio, 2),
        "avg_ai_likelihood": avg_ai,
    }

    return {
        "overall_confidence": overall_conf,
        "confidence_verdict": _confidence_verdict_band(overall_conf),
        "competency_confidence": competency_confidence,
        "confidence_reasons": reasons[:4],
        "evidence_coverage": evidence_coverage,
    }


def _aggregate_skills(
    per_question: list[dict],
    message_history: list[dict] | None = None,
) -> list[dict]:
    """Aggregate skill tags with strict candidate-evidence gating."""
    proficiency_order = ["beginner", "intermediate", "advanced", "expert"]
    generic_terms = {
        "api",
        "rest",
        "soap",
        "backend",
        "frontend",
        "web",
        "software",
        "development",
        "programming",
        "database",
        "databases",
        "sql",
        "architecture",
        "system",
        "systems",
        "service",
        "services",
        "support",
        "testing",
        "test",
    }
    action_markers = (
        "использ",
        "настро",
        "оптимиз",
        "проектир",
        "реализ",
        "внедр",
        "build",
        "built",
        "use",
        "used",
        "design",
        "designed",
        "configure",
        "configured",
        "optimiz",
        "implemented",
        "deployed",
        "debug",
        "troubleshoot",
    )
    context_markers = (
        "production",
        "prod",
        "проект",
        "проекте",
        "проекта",
        "нагруз",
        "latency",
        "throughput",
        "инцид",
        "метрик",
        "slo",
        "results",
        "результат",
        "опыт",
        "years",
    )

    def _normalize_skill_name(name: str) -> str:
        normalized = re.sub(r"\s+", " ", (name or "").strip().lower())
        return normalized.strip(".,:;!?/\\-")

    def _is_noise_skill(name: str) -> bool:
        if not name or len(name) < 2 or len(name) > 48:
            return True
        if name.isdigit():
            return True
        if len(name.split()) > 4:
            return True
        return name in generic_terms

    def _keep_unconfirmed_mention(name: str) -> bool:
        return bool(_FRONTEND_CORE_EVIDENCE_RE.search(name))

    candidate_answers = [
        str(msg.get("content", "") or "")
        for msg in (message_history or [])
        if str(msg.get("role", "")) == "candidate" and str(msg.get("content", "")).strip()
    ]
    candidate_corpus = " ".join(candidate_answers).lower()
    candidate_tech_mentions = set()
    for answer in candidate_answers:
        candidate_tech_mentions.update(extract_mentioned_technologies(answer))

    def _skill_candidate_evidence(skill: str) -> tuple[bool, str | None]:
        if not candidate_answers:
            # Backward-compatible fallback for cases where we only have pass1.
            return False, None
        pattern = re.compile(rf"\b{re.escape(skill)}\b")
        fallback_window: str | None = None
        for answer in candidate_answers:
            answer_lower = answer.lower()
            for match in pattern.finditer(answer_lower):
                start = max(0, match.start() - 80)
                end = min(len(answer_lower), match.end() + 80)
                window = answer_lower[start:end]
                fallback_window = fallback_window or answer[max(0, match.start() - 80):min(len(answer), match.end() + 80)].strip()
                has_action = any(marker in window for marker in action_markers)
                has_context = any(marker in window for marker in context_markers) or bool(re.search(r"\d", window))
                if has_action and has_context:
                    return True, fallback_window

        if skill in candidate_tech_mentions:
            # Extracted mention exists but without local action context.
            return False, fallback_window

        matches = list(pattern.finditer(candidate_corpus))
        if not matches:
            return False, None
        for match in matches:
            start = max(0, match.start() - 80)
            end = min(len(candidate_corpus), match.end() + 80)
            window = candidate_corpus[start:end]
            if any(marker in window for marker in action_markers) and (
                any(marker in window for marker in context_markers) or bool(re.search(r"\d", window))
            ):
                return True, candidate_corpus[start:end].strip()
        return False, fallback_window

    skill_map: dict[str, dict] = {}
    for q in per_question:
        question_confidence = _question_evidence_confidence(q)
        if question_confidence < 0.6:
            continue
        for sm in q.get("skills_mentioned", []):
            name = _normalize_skill_name(str(sm.get("skill", "")))
            if _is_noise_skill(name):
                continue
            has_evidence, evidence_summary = _skill_candidate_evidence(name)
            if not has_evidence and not candidate_answers:
                question_evidence = str(q.get("evidence") or "").strip()
                evidence_lower = question_evidence.lower()
                if name in evidence_lower and any(marker in evidence_lower for marker in action_markers):
                    has_evidence = True
                    evidence_summary = question_evidence[:220]
            if candidate_answers and not has_evidence and not _keep_unconfirmed_mention(name):
                continue
            prof = str(sm.get("proficiency", "intermediate")).lower()
            if prof not in proficiency_order:
                prof = "intermediate"
            status = "confirmed" if has_evidence and question_confidence >= 0.75 else "mentioned"
            if status != "confirmed" and prof == "beginner":
                status = "development"
            if name in skill_map:
                skill_map[name]["mentions_count"] += 1
                skill_map[name]["confidence_sum"] += question_confidence
                if status == "confirmed":
                    skill_map[name]["status"] = "confirmed"
                elif skill_map[name]["status"] != "confirmed" and status == "development":
                    skill_map[name]["status"] = "development"
                if evidence_summary and not skill_map[name].get("evidence"):
                    skill_map[name]["evidence"] = evidence_summary
                if proficiency_order.index(prof) > proficiency_order.index(skill_map[name]["proficiency"]):
                    skill_map[name]["proficiency"] = prof
            else:
                skill_map[name] = {
                    "skill": name,
                    "proficiency": prof,
                    "mentions_count": 1,
                    "confidence_sum": question_confidence,
                    "status": status,
                    "evidence": evidence_summary if status == "confirmed" else None,
                }

    filtered: list[dict] = []
    for data in skill_map.values():
        avg_confidence = data["confidence_sum"] / data["mentions_count"]
        # Single low-confidence non-evidence mention is often noisy extraction.
        if data["status"] != "confirmed" and data["mentions_count"] == 1 and avg_confidence < 0.75:
            continue
        if avg_confidence < 0.65:
            continue
        filtered.append(
            {
                "skill": data["skill"],
                "proficiency": data["proficiency"],
                "mentions_count": data["mentions_count"],
                "status": data["status"],
                "evidence": data.get("evidence"),
            }
        )

    return sorted(filtered, key=lambda x: x["mentions_count"], reverse=True)


def _detect_role_mismatch(
    *,
    target_role: str,
    message_history: list[dict] | None,
    per_question_analysis: list[dict],
) -> dict[str, Any]:
    """Detect likely role mismatch from evidence, currently focused on Frontend interviews."""
    if target_role != "frontend_engineer":
        return {
            "detected": False,
            "mismatch_type": None,
            "confidence": 0.0,
            "support_incident_evidence": [],
            "frontend_core_evidence_count": 0,
            "frontend_weak_checks": 0,
            "notes": [],
        }

    candidate_answers = [
        str(msg.get("content", "") or "")
        for msg in (message_history or [])
        if str(msg.get("role", "")) == "candidate" and str(msg.get("content", "")).strip()
    ]
    support_evidence: list[str] = []
    for answer in candidate_answers:
        if _SUPPORT_INCIDENT_RE.search(answer):
            support_evidence.append(answer[:240])

    frontend_core_evidence_count = 0
    frontend_weak_checks = 0
    for item in per_question_analysis or []:
        targeted = " ".join(str(value) for value in item.get("targeted_competencies", [])).lower()
        evidence = str(item.get("evidence") or "")
        answer_quality = _to_float(item.get("answer_quality"), 0.0)
        depth = str(item.get("depth") or "surface").lower()
        specificity = str(item.get("specificity") or "low").lower()
        is_frontend_core = bool(
            _FRONTEND_CORE_COMPETENCY_RE.search(targeted)
            or _FRONTEND_CORE_EVIDENCE_RE.search(evidence)
        )
        if not is_frontend_core:
            continue
        has_frontend_evidence = (
            bool(_FRONTEND_CORE_EVIDENCE_RE.search(evidence))
            and answer_quality >= 6.5
            and depth in {"adequate", "strong", "expert"}
            and specificity in {"medium", "high"}
        )
        if has_frontend_evidence:
            frontend_core_evidence_count += 1
        elif answer_quality <= 5.0 or depth in {"surface", "none"} or specificity == "low":
            frontend_weak_checks += 1

    support_signal_count = len(support_evidence)
    detected = support_signal_count >= 1 and frontend_core_evidence_count == 0 and frontend_weak_checks >= 2
    confidence = 0.0
    if detected:
        confidence = min(0.95, 0.55 + support_signal_count * 0.1 + frontend_weak_checks * 0.08)
    return {
        "detected": detected,
        "mismatch_type": "support_incident_vs_frontend" if detected else None,
        "confidence": round(confidence, 2),
        "support_incident_evidence": support_evidence[:3],
        "frontend_core_evidence_count": frontend_core_evidence_count,
        "frontend_weak_checks": frontend_weak_checks,
        "notes": [
            "Candidate evidence fits support/incident diagnostics more than frontend development."
        ]
        if detected
        else [],
    }


def _apply_role_mismatch_caps(
    *,
    target_role: str,
    competency_scores: list[dict],
    role_mismatch: dict[str, Any],
) -> list[str]:
    if target_role != "frontend_engineer" or not bool(role_mismatch.get("detected")):
        return []
    penalties: list[str] = []
    for item in competency_scores:
        competency = str(item.get("competency") or "")
        category = str(item.get("category") or "")
        if category in {"technical_core", "technical_breadth"} and _FRONTEND_CORE_COMPETENCY_RE.search(competency):
            old_score = _to_float(item.get("score"), 0.0)
            capped = min(old_score, 4.0)
            if capped < old_score:
                item["score"] = capped
                item["reasoning"] = (
                    f"{str(item.get('reasoning') or '').strip()} "
                    "Role mismatch cap: support/incident answers did not confirm frontend-core delivery evidence."
                ).strip()
                penalties.append(f"role_mismatch_cap:{competency}:{old_score}->{capped}")
    return penalties


def _compute_cheat_risk(
    signals: dict | None,
    per_question_analysis: list[dict] | None = None,
) -> tuple[float, list[str]]:
    """Compute cheat_risk_score (0.0–1.0) and list of flags from behavioral signals + AI likelihood."""
    flags: list[str] = []
    score = 0.0

    # ── Behavioral signals ────────────────────────────────────────────────────
    if signals:
        paste_count: int = signals.get("paste_count", 0)
        tab_switches: int = signals.get("tab_switches", 0)
        face_away_pct: float | None = signals.get("face_away_pct")
        speech_activity_pct: float | None = signals.get("speech_activity_pct")
        silence_pct: float | None = signals.get("silence_pct")
        long_silence_count: int = _to_int(signals.get("long_silence_count"), 0)
        speech_segment_count: int = _to_int(signals.get("speech_segment_count"), 0)
        response_times: list[dict] = signals.get("response_times", [])

        if paste_count >= 3:
            flags.append(f"High paste activity ({paste_count} pastes)")
            score += 0.3
        elif paste_count >= 1:
            flags.append(f"Paste activity detected ({paste_count} pastes)")
            score += 0.15

        if tab_switches >= 5:
            flags.append(f"Frequent tab/window switching ({tab_switches} switches)")
            score += 0.3
        elif tab_switches >= 2:
            flags.append(f"Tab/window switching ({tab_switches} switches)")
            score += 0.15

        if face_away_pct is not None and face_away_pct >= 0.4:
            flags.append(f"Face not visible {int(face_away_pct * 100)}% of the time")
            score += 0.3
        elif face_away_pct is not None and face_away_pct >= 0.2:
            flags.append(f"Face away {int(face_away_pct * 100)}% of the time")
            score += 0.1

        # Very fast answers (<10s) combined with paste events → suspicious
        if response_times and paste_count >= 1:
            fast = [rt for rt in response_times if rt.get("seconds", 999) < 10]
            if len(fast) >= 2:
                flags.append(f"{len(fast)} answers submitted under 10 seconds with paste activity")
                score += 0.2

        if speech_activity_pct is not None and _to_float(speech_activity_pct) <= 0.05 and paste_count >= 1:
            flags.append(
                f"Low speech activity ({int(_to_float(speech_activity_pct) * 100)}%) with paste activity"
            )
            score += 0.1

        if long_silence_count >= 2 and tab_switches >= 2:
            flags.append(
                f"Long silence periods ({long_silence_count}) with tab/window switching"
            )
            score += 0.1

        if (
            silence_pct is not None
            and _to_float(silence_pct) >= 0.9
            and speech_segment_count <= 1
            and paste_count >= 2
        ):
            flags.append("Mostly silent response capture with repeated paste activity")
            score += 0.1

    # ── AI-generated text detection (from Pass 1 per-question analysis) ───────
    if per_question_analysis:
        ai_scores = [
            q.get("ai_likelihood", 0.0)
            for q in per_question_analysis
            if q.get("ai_likelihood") is not None
        ]
        if ai_scores:
            avg_ai = sum(ai_scores) / len(ai_scores)
            high_ai = [s for s in ai_scores if s >= 0.7]

            if avg_ai >= 0.7:
                flags.append(f"High AI-generated text probability across answers (avg {avg_ai:.0%})")
                score += 0.4
            elif avg_ai >= 0.5:
                flags.append(f"Moderate AI-generated text probability (avg {avg_ai:.0%})")
                score += 0.2

            if len(high_ai) >= 3:
                flags.append(f"{len(high_ai)} answers show strong AI-writing patterns")
                score += 0.15

    return round(min(score, 1.0), 2), flags


def _compute_response_times(message_timestamps: list[dict] | None) -> dict:
    """Compute response time analytics from message timestamps."""
    if not message_timestamps:
        return {}
    times = []
    for i, msg in enumerate(message_timestamps):
        if msg.get("role") == "candidate" and i > 0:
            prev = message_timestamps[i - 1]
            if prev.get("role") == "assistant" and prev.get("created_at") and msg.get("created_at"):
                try:
                    t1 = datetime.fromisoformat(str(prev["created_at"]))
                    t2 = datetime.fromisoformat(str(msg["created_at"]))
                    diff = (t2 - t1).total_seconds()
                    if 0 < diff < 3600:  # sanity check
                        times.append(round(diff, 1))
                except (ValueError, TypeError):
                    pass
    if not times:
        return {}
    return {
        "avg_response_time_seconds": round(sum(times) / len(times), 1),
        "per_question_times": times,
    }


def _build_fallback_question_analysis(
    *,
    message_history: list[dict],
    target_role: str,
    interview_meta: dict | None,
    report_language: str,
) -> list[dict]:
    topic_plan = list((interview_meta or {}).get("topic_plan", []) or [])
    topic_reuse_flags = list((interview_meta or {}).get("topic_reuse_flags", []) or [])
    topic_relevance_failures = list((interview_meta or {}).get("topic_relevance_failures", []) or [])
    role_competencies = get_competencies(target_role)
    fallback_names = [comp.name for comp in role_competencies]
    action_markers = (
        "спроект",
        "проектировал",
        "оптимиз",
        "настро",
        "анализ",
        "внедр",
        "реализ",
        "использовал",
        "debug",
        "diagnos",
        "designed",
        "optimized",
        "implemented",
        "tuned",
        "configured",
        "investigated",
        "rolled",
        "measured",
    )
    concrete_markers = (
        "индекс",
        "query plan",
        "explain",
        "latency",
        "throughput",
        "partition",
        "consumer",
        "outbox",
        "replication",
        "retry",
        "idempot",
        "cache",
        "transaction",
        "docker",
        "ci/cd",
        "rollback",
        "slo",
        "metric",
        "p95",
        "p99",
    )

    per_q: list[dict] = []
    q_num = 0
    for msg in message_history:
        if msg["role"] == "assistant":
            q_num += 1
            continue
        if msg["role"] != "candidate":
            continue

        answer = str(msg.get("content", "") or "")
        answer_class, _ = classify_answer(answer)
        words = len(answer.split())
        techs = sorted(extract_mentioned_technologies(answer))
        has_numbers = bool(re.search(r"\d+", answer))
        lowered = answer.lower()
        has_actions = any(token in lowered for token in action_markers)
        has_concrete_markers = any(token in lowered for token in concrete_markers)
        has_tradeoff = any(
            token in lowered
            for token in ("trade-off", "tradeoff", "компром", "потому что", "why", "because", "latency", "throughput")
        )
        target = topic_plan[q_num - 1] if 0 < q_num <= len(topic_plan) else {}
        competencies = list(target.get("competencies", []) or []) or [fallback_names[min(max(q_num - 1, 0), len(fallback_names) - 1)]]
        target_tech = str(target.get("verification_target") or "").lower()
        target_hit = bool(target_tech and target_tech in {tech.lower() for tech in techs})
        concrete_signal = bool(techs or has_tradeoff or has_numbers or has_concrete_markers)
        practical_signal = bool(has_actions and concrete_signal)
        reused_signal = bool(0 < q_num <= len(topic_reuse_flags) and topic_reuse_flags[q_num - 1])
        relevance_failure = int(topic_relevance_failures[q_num - 1]) if 0 < q_num <= len(topic_relevance_failures) else 0

        if answer_class == "strong":
            answer_quality = 8.6 if practical_signal and (has_tradeoff or has_numbers) else 8.1
            specificity = "high" if words >= 18 and concrete_signal else "medium"
            depth = "expert" if words >= 32 and practical_signal else "strong"
            red_flags: list[str] = []
        elif answer_class == "partial":
            if words >= 18 and (practical_signal or target_hit):
                answer_quality = 7.2 if has_tradeoff or has_numbers else 6.9
                specificity = "high" if practical_signal and words >= 22 else "medium"
                depth = "strong" if practical_signal else "adequate"
            else:
                answer_quality = 6.3 if words >= 14 else 5.8
                specificity = "medium" if words >= 10 else "low"
                depth = "adequate" if words >= 14 else "surface"
            red_flags = []
        elif answer_class == "generic":
            if words >= 16 and (practical_signal or target_hit):
                answer_quality = 7.3 if practical_signal and (has_tradeoff or has_concrete_markers or has_numbers) else 6.9
                specificity = "medium"
                depth = "strong" if practical_signal else "adequate"
                red_flags = []
            else:
                answer_quality = 4.2
                specificity = "low"
                depth = "surface"
                red_flags = [
                    "answer generic — no real-world example"
                    if report_language == "ru"
                    else "answer generic — no real-world example"
                ]
        elif answer_class == "evasive":
            answer_quality = 3.0
            specificity = "low"
            depth = "surface"
            red_flags = [
                "evasive — question avoided"
                if report_language == "ru"
                else "evasive — question avoided"
            ]
        else:
            answer_quality = 2.5
            specificity = "low"
            depth = "none"
            red_flags = [
                "candidate explicitly lacks hands-on experience"
                if report_language == "en"
                else "кандидат честно указал отсутствие практического опыта"
            ]

        if target_hit:
            answer_quality = min(8.8, answer_quality + 0.3)
        if reused_signal and not target_hit:
            answer_quality = max(3.0, answer_quality - 0.7)
            red_flags = [*red_flags, "answer repeated across topics"]
        if relevance_failure > 0 and not target_hit and not practical_signal:
            answer_quality = max(3.0, answer_quality - 0.5)
        if words < 10 and answer_quality > 3.0:
            answer_quality = 3.0
            specificity = "low"
            depth = "surface"

        if report_language == "ru":
            evidence = answer[:220] if answer else "Недостаточно данных из ответа"
        else:
            evidence = answer[:220] if answer else "Insufficient answer evidence"

        per_q.append(
            {
                "question_number": q_num,
                "targeted_competencies": competencies,
                "answer_quality": round(answer_quality, 1),
                "evidence": evidence,
                "skills_mentioned": [
                    {
                        "skill": tech,
                        "proficiency": (
                            "expert"
                            if answer_quality >= 8.2
                            else "advanced"
                            if answer_quality >= 7.0
                            else "intermediate"
                        ),
                    }
                    for tech in techs
                ],
                "red_flags": red_flags,
                "specificity": specificity,
                "depth": depth,
                "ai_likelihood": 0.05 if answer_class in {"strong", "partial"} else 0.1,
                "block": str(target.get("block") or "").strip() or None,
                "tier": str(target.get("tier") or "").strip() or None,
                "lead_question": str(target.get("lead_question") or "").strip() or None,
                "allowed_probes": _to_str_list(target.get("allowed_probes")),
                "scored_metrics": _to_str_list(target.get("scored_metrics")),
                "why_asked": _topic_why_asked(target.get("block"), report_language),
                "what_was_scored": _topic_scoring_focus(_to_str_list(target.get("scored_metrics")), report_language),
            }
        )

    return per_q


def _build_fallback_competency_scores(
    *,
    target_role: str,
    summary_model: dict,
    interview_meta: dict | None,
    report_language: str,
    per_question_analysis: list[dict],
) -> list[dict]:
    topic_plan = list((interview_meta or {}).get("topic_plan", []) or [])
    topic_outcomes = list(summary_model.get("topic_outcomes", []) or [])
    outcome_by_slot = {int(item.get("slot", 0) or 0): item for item in topic_outcomes}
    question_by_slot = {int(item.get("question_number", 0) or 0): item for item in per_question_analysis}
    role_competencies = get_competencies(target_role)
    comp_map = {comp.name: comp for comp in role_competencies}
    category_scores: dict[str, list[float]] = {}

    comp_scores: list[dict] = []
    for idx, topic in enumerate(topic_plan, start=1):
        outcome_item = outcome_by_slot.get(idx, {})
        question_item = question_by_slot.get(idx, {})
        outcome = str(outcome_item.get("outcome", "partial"))
        signal = str(outcome_item.get("signal", "partial"))
        answer_quality = _to_float(question_item.get("answer_quality"), 3.5)
        specificity = str(question_item.get("specificity", "low")).lower()
        depth = str(question_item.get("depth", "surface")).lower()
        for comp_name in topic.get("competencies", []) or []:
            comp = comp_map.get(comp_name)
            if not comp:
                continue

            if outcome == "validated":
                score = max(
                    answer_quality + 0.2,
                    8.4 if signal == "strong" or depth in {"strong", "expert"} else 7.6,
                )
                if specificity == "high":
                    score += 0.2
            elif outcome == "partial":
                score = min(max(answer_quality, 4.2), 7.2)
                if depth in {"strong", "expert"}:
                    score = max(score, 7.1)
                if specificity == "high":
                    score = max(score, 6.5)
            elif outcome == "unverified_claim":
                score = min(answer_quality, 4.8)
            elif outcome == "evasive":
                score = min(answer_quality, 4.0)
            elif outcome == "honest_gap":
                score = min(answer_quality, 3.8)
            else:
                score = answer_quality

            label = str(outcome_item.get("label") or comp_name)
            if report_language == "ru":
                evidence = f"Сигнал по теме «{label}»: {outcome}"
                reasoning = f"Балл {score}: рассчитан из качества сигнала по теме."
            else:
                evidence = f"Signal for topic '{label}': {outcome}"
                reasoning = f"Score {score}: derived from topic-level evidence quality."

            comp_scores.append(
                {
                    "competency": comp.name,
                    "category": comp.category,
                    "score": round(score, 1),
                    "weight": comp.weight,
                    "evidence": evidence,
                    "reasoning": reasoning,
                }
            )
            category_scores.setdefault(comp.category, []).append(round(score, 1))

    seen = {item["competency"] for item in comp_scores}
    category_fallbacks = {
        category: min(round(sum(scores) / len(scores), 1), 5.2)
        for category, scores in category_scores.items()
        if scores
    }
    for comp in role_competencies:
        if comp.name in seen:
            continue
        comp_scores.append(
            {
                "competency": comp.name,
                "category": comp.category,
                "score": category_fallbacks.get(comp.category, 4.5),
                "weight": comp.weight,
                "evidence": "Insufficient direct answer evidence",
                "reasoning": "No direct candidate answer mapped to this competency.",
            }
        )
    return comp_scores


# ---------------------------------------------------------------------------
# LLM implementation (Gemini) — two-pass assessment
# ---------------------------------------------------------------------------

class LLMAssessor:
    """Generates structured assessment reports via configured LLM provider (two-pass)."""

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    @property
    def provider_name(self) -> str:
        return getattr(self._provider, "name", "unknown")

    async def _create_completion_with_model_fallback(self, *, model_override: str | None = None, **kwargs):
        resolved_model = resolve_llm_runtime_model(model_override)
        logger.info(
            "ai_model_call component=assessor provider=%s model=%s",
            self.provider_name,
            resolved_model,
        )
        response = await self._provider.chat_completion(
            messages=kwargs.get("messages", []),
            model=resolved_model,
            temperature=float(kwargs.get("temperature", 0.2)),
            max_tokens=int(kwargs.get("max_tokens", 1024)),
            response_format=kwargs.get("response_format"),
            extra_body={
                key: value
                for key, value in kwargs.items()
                if key
                not in {"messages", "model", "temperature", "max_tokens", "response_format"}
            },
        )
        record_ai_success(
            component="assessor",
            provider=self.provider_name,
            model=response.actual_model_used,
            note=("fallback_models_used" if response.fallback_used else None),
        )
        return response

    @staticmethod
    def _extract_tool_json_arguments(raw_response: Any) -> str | None:
        try:
            message = raw_response.choices[0].message
            tool_calls = getattr(message, "tool_calls", None)
            if tool_calls:
                return str(tool_calls[0].function.arguments or "").strip()
        except Exception:
            return None
        return None

    @staticmethod
    def _extract_json_object_text(raw_text: str) -> str:
        text = str(raw_text or "").strip()
        if not text:
            return ""
        if "```" in text:
            text = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE).replace("```", "").strip()
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return text[start:end + 1]
        return text

    def _load_structured_payload(self, provider_result: Any) -> dict[str, Any]:
        raw_response = getattr(provider_result, "raw_response", None)
        tool_json = self._extract_tool_json_arguments(raw_response)
        candidate = tool_json or self._extract_json_object_text(getattr(provider_result, "text", ""))
        if not candidate:
            raise ValueError("empty structured payload")
        payload = json.loads(candidate)
        if not isinstance(payload, dict):
            raise ValueError("structured payload is not an object")
        return payload

    async def assess(
        self,
        target_role: str,
        message_history: list[dict],
        message_timestamps: list[dict] | None = None,
        behavioral_signals: dict | None = None,
        language: str = "ru",
        interview_meta: dict | None = None,
        model_override: str | None = None,
        runtime_settings: dict | None = None,
    ) -> AssessmentResult:
        # Try running assessment on Go service first
        assessment_service_url = os.getenv("ASSESSMENT_SERVICE_URL", "http://assessment-service:8080")
        try:
            logger.info("Attempting assessment via Go assessment-service...")
            async with httpx.AsyncClient(timeout=180.0) as client:
                resp = await client.post(
                    f"{assessment_service_url}/v1/assess",
                    json={
                        "target_role": target_role,
                        "message_history": message_history,
                        "language": language,
                        "model_override": model_override,
                        "runtime_settings": runtime_settings or {},
                    }
                )
                if resp.status_code == 200:
                    data = resp.json()
                    logger.info("Go assessment-service returned successful evaluation!")
                    
                    # Construct AssessmentResult from Go data
                    go_res = AssessmentResult(
                        overall_score=data["overall_score"],
                        hard_skills_score=data["hard_skills_score"],
                        soft_skills_score=data["soft_skills_score"],
                        communication_score=data["communication_score"],
                        strengths=data.get("strengths") or [],
                        weaknesses=data.get("weaknesses") or [],
                        recommendations=data.get("recommendations") or [],
                        hiring_recommendation=data["hiring_recommendation"],
                        interview_summary=data.get("interview_summary"),
                        model_version=data.get("model_version", "gpt-5.4-mini"),
                        competency_scores=data.get("competency_scores") or [],
                        per_question_analysis=data.get("per_question_analysis") or [],
                        skill_tags=data.get("skill_tags") or [],
                        red_flags=data.get("red_flags") or [],
                        response_consistency=data.get("response_consistency"),
                        problem_solving_score=data.get("problem_solving_score"),
                        full_report_json=data
                    )
                    return go_res
                else:
                    logger.warning(f"Go assessment-service returned status {resp.status_code}, falling back to Python assessor")
        except Exception as e:
            logger.exception(f"Go assessment-service failed: {e}. Falling back to Python assessor.")

        report_language = _normalized_report_language(language)
        role_label = _role_label(target_role, report_language)
        competencies = get_competencies(target_role)

        # Build transcript
        transcript_lines = []
        q_num = 0
        for msg in message_history:
            if msg["role"] == "assistant":
                q_num += 1
                transcript_lines.append(f"[Q{q_num}] Интервьюер: {msg['content']}")
            elif msg["role"] == "candidate":
                transcript_lines.append(f"[A{q_num}] Кандидат: {msg['content']}")
        transcript = "\n\n".join(transcript_lines)

        # Build competency reference
        comp_ref = "\n".join(
            f"- {c.name} ({c.category}, вес {c.weight}): {c.description}"
            for c in competencies
        )

        # Pass 1: Per-question evidence extraction
        pass1_data, resolved_model = await self._pass1_question_analysis(
            role_label,
            transcript,
            comp_ref,
            report_language,
            model_override=model_override,
            runtime_settings=runtime_settings,
        )
        topic_plan = list((interview_meta or {}).get("topic_plan", []) or [])
        pass1_data = _enrich_per_question_analysis_with_topic_plan(
            pass1_data,
            topic_plan,
            report_language=report_language,
        )
        summary_model = _build_summary_model(target_role, report_language, interview_meta, pass1_data)

        # Pass 2: Competency scoring (message_history needed for word-count penalization)
        result = await self._pass2_competency_scoring(
            role_label,
            transcript,
            comp_ref,
            pass1_data,
            target_role,
            message_history,
            report_language,
            summary_model=summary_model,
            interview_meta=interview_meta,
            model_override=model_override,
            runtime_settings=runtime_settings,
        )
        result.model_version = resolved_model

        adjusted_aggregates, summary_penalties = _apply_summary_penalties(
            {
                "overall_score": result.overall_score,
                "hard_skills_score": result.hard_skills_score,
                "soft_skills_score": result.soft_skills_score,
                "communication_score": result.communication_score,
                "problem_solving_score": result.problem_solving_score,
            },
            summary_model,
            {"overall_confidence": result.overall_confidence},
        )
        result.overall_score = adjusted_aggregates["overall_score"]
        result.hard_skills_score = adjusted_aggregates["hard_skills_score"]
        result.soft_skills_score = adjusted_aggregates["soft_skills_score"]
        result.communication_score = adjusted_aggregates["communication_score"]
        result.problem_solving_score = adjusted_aggregates["problem_solving_score"]
        result.full_report_json["summary_model"] = summary_model
        result.full_report_json["interview_meta"] = interview_meta or {}
        system_design_evaluation = _build_system_design_evaluation(
            interview_meta,
            result.per_question_analysis,
        )
        if system_design_evaluation:
            result.full_report_json["system_design_evaluation"] = system_design_evaluation
        behavioral_interview_evaluation = _build_behavioral_interview_evaluation(
            interview_meta,
            result.per_question_analysis,
            message_history,
            report_language,
        )
        if behavioral_interview_evaluation:
            result.full_report_json["behavioral_interview_evaluation"] = behavioral_interview_evaluation
        coding_task_evaluation = _build_coding_task_evaluation(
            interview_meta,
            result.per_question_analysis,
            message_history,
            report_language,
        )
        if coding_task_evaluation:
            result.full_report_json["coding_task_evaluation"] = coding_task_evaluation
        sql_live_evaluation = _build_sql_live_evaluation(
            interview_meta,
            result.per_question_analysis,
            message_history,
            report_language,
        )
        if sql_live_evaluation:
            result.full_report_json["sql_live_evaluation"] = sql_live_evaluation
        written_communication_evaluation = _build_written_communication_evaluation(
            interview_meta,
            result.per_question_analysis,
            message_history,
            report_language,
        )
        if written_communication_evaluation:
            result.full_report_json["written_communication_evaluation"] = written_communication_evaluation
        result.full_report_json["aggregates"] = adjusted_aggregates
        result.full_report_json["score_penalties"] = result.full_report_json.get("score_penalties", []) + summary_penalties
        result.full_report_json["calibrated_scoring"] = _build_calibrated_scoring(
            per_question_analysis=result.per_question_analysis,
            summary_model=summary_model,
            report_language=report_language,
            aggregates_pre_penalty=result.full_report_json.get("aggregates_pre_penalty", adjusted_aggregates),
            aggregates_final=adjusted_aggregates,
            penalties=list(result.full_report_json.get("score_penalties", []) or []),
        )
        final_recommendation, gate_reasons = _apply_recommendation_gates(
            llm_rec=result.hiring_recommendation,
            overall_score=result.overall_score,
            summary_model=summary_model,
            answer_metrics={
                "short_answer_ratio": _to_float(result.full_report_json.get("answer_metrics", {}).get("short_answer_ratio"), 0.0),
                "avg_answer_quality": _to_float(result.full_report_json.get("answer_quality_score"), 5.0),
            },
            confidence_metrics={
                "overall_confidence": result.overall_confidence,
            },
            competency_scores=result.competency_scores,
        )
        result.hiring_recommendation = final_recommendation
        result.full_report_json["hiring_recommendation"] = final_recommendation
        result.full_report_json["recommendation_gate_reasons"] = gate_reasons
        strengths, weaknesses, recommendations = _build_outcome_feedback(summary_model, report_language)
        result.strengths = _prefer_outcome_feedback(result.strengths, strengths)
        result.weaknesses = _prefer_outcome_feedback(result.weaknesses, weaknesses)
        result.recommendations = _prefer_outcome_feedback(result.recommendations, recommendations)
        result.full_report_json["strengths"] = result.strengths
        result.full_report_json["weaknesses"] = result.weaknesses
        result.full_report_json["recommendations"] = result.recommendations
        result.full_report_json["explainability_report"] = _build_explainability_report(
            target_role=target_role,
            report_language=report_language,
            summary_model=summary_model,
            per_question_analysis=result.per_question_analysis,
            strengths=result.strengths,
            weaknesses=result.weaknesses,
            recommendations=result.recommendations,
            hiring_recommendation=result.hiring_recommendation,
            overall_score=result.overall_score,
            overall_confidence=result.overall_confidence,
            calibrated_scoring=result.full_report_json.get("calibrated_scoring", {}),
            penalties=list(result.full_report_json.get("score_penalties", []) or []),
        )
        result.interview_summary = _build_interview_summary_text(
            target_role,
            report_language,
            summary_model,
            result.overall_score,
        )

        # Response time analytics
        response_times = _compute_response_times(message_timestamps)
        if response_times:
            result.full_report_json["response_times"] = response_times

        # Cheat risk: behavioral signals + AI-likelihood from Pass 1
        cheat_risk, cheat_flags = _compute_cheat_risk(behavioral_signals, result.per_question_analysis)
        result.cheat_risk_score = cheat_risk
        result.cheat_flags = cheat_flags
        if cheat_flags:
            result.full_report_json["cheat_risk"] = {"score": cheat_risk, "flags": cheat_flags}

        return result

    async def _pass1_question_analysis(
        self,
        role_label: str,
        transcript: str,
        comp_ref: str,
        report_language: str,
        model_override: str | None = None,
        runtime_settings: dict | None = None,
    ) -> tuple[list[dict], str]:
        """Pass 1: Extract per-question evidence, skills, red flags."""
        output_language = "русском" if report_language == "ru" else "English"
        system = (
            f"Ты — строгий старший интервьюер, оценивающий кандидата на позицию «{role_label}».\n"
            "Твоя задача — объективно зафиксировать ФАКТЫ из ответов, не давать кандидату преимущество сомнения.\n\n"
            "## Матрица компетенций\n"
            f"{comp_ref}\n\n"
            "## Задача\n"
            "Для КАЖДОЙ пары вопрос-ответ определи:\n"
            "1. Какие компетенции из матрицы этот вопрос оценивает\n"
            "2. Качество ответа (1-10) — ТОЛЬКО по фактическому содержанию\n"
            "3. Конкретные доказательства из ответа (прямые цитаты или специфические факты)\n"
            "4. Технологии/навыки с ЛИЧНЫМ опытом использования\n"
            "5. Красные флаги (противоречия, уход от вопроса, повторения, фабрикации)\n"
            "6. Конкретность (high/medium/low) и глубина (expert/strong/adequate/surface/none)\n"
            "7. Вероятность AI-генерации (ai_likelihood 0.0-1.0)\n"
            "8. communication_star_structured (boolean): структурирован ли ответ по STAR (Ситуация, Задача, Действие, Результат) или другой четкой логической схеме?\n"
            "9. communication_style: подробное описание ясности, лаконичности речи, избыточного использования «воды» или сумбурного изложения.\n"
            "10. problem_solving_approach: метод решения задач:\n"
            "    - 'first_principles' (первопринципное мышление: декомпозиция, поиск первопричины, анализ trade-offs и ограничений, понимание внутренних механизмов),\n"
            "    - 'structured_decomposition' (последовательный структурированный разбор),\n"
            "    - 'trial_and_error' (метод проб и ошибок, хаотичный поиск решения),\n"
            "    - 'superficial_heuristics' (заученные шаблоны, поверхностная зубрежка),\n"
            "    - 'none' (неприменимо).\n"
            "11. problem_solving_evidence: цитата или описание, подтверждающее выбранный метод решения задач.\n"
            "12. leadership_ownership: уровень ответственности и командного взаимодействия:\n"
            "    - 'strong_ownership' (проактивность, принятие личной ответственности за результаты и сбои),\n"
            "    - 'collaborative' (акцент на командной работе, выравнивании ожиданий и обмене опытом),\n"
            "    - 'passive_execution' (пассивное исполнение задач сверху без понимания цели),\n"
            "    - 'blame_shifting' (перекладывание ответственности на коллег, стек, руководство или обстоятельства),\n"
            "    - 'none' (неприменимо).\n\n"
            "## ЖЁСТКИЕ ПРАВИЛА ОЦЕНКИ ANSWER_QUALITY — ОБЯЗАТЕЛЬНЫ\n\n"
            "КОРОТКИЙ ОТВЕТ (<10 слов):\n"
            "- answer_quality ОБЯЗАН быть ≤ 3\n"
            "- depth = 'surface' или 'none'\n"
            "- specificity = 'low'\n"
            "- добавь в red_flags: 'answer too short'\n\n"
            "ОБЩИЙ ОТВЕТ (нет конкретного примера, нет реального проекта):\n"
            "- answer_quality ОБЯЗАН быть ≤ 5\n"
            "- specificity = 'low'\n"
            "- добавь в red_flags: 'answer generic — no real-world example'\n\n"
            "НЕТ ОБЪЯСНЕНИЯ 'КАК' И 'ПОЧЕМУ':\n"
            "- depth = 'surface' (максимум 'adequate' если есть хоть что-то)\n"
            "- answer_quality снижается на 1-2 пункта\n\n"
            "КОНКРЕТНЫЙ ПРАКТИЧЕСКИЙ ОТВЕТ БЕЗ ЦИФР:\n"
            "- если кандидат ясно описал, что именно делал, как работало решение и какие trade-offs учитывал,\n"
            "  такой ответ МОЖЕТ получить 7-8 даже без численных метрик\n"
            "- не штрафуй сильный практический ответ только за отсутствие процентов или p95\n\n"
            "УКЛОНЧИВЫЙ ОТВЕТ (не отвечает на вопрос):\n"
            "- answer_quality ОБЯЗАН быть ≤ 3\n"
            "- добавь в red_flags: 'evasive — question avoided'\n\n"
            "ПОВТОРЯЮЩИЙСЯ ОТВЕТ (то же самое что в предыдущих вопросах):\n"
            "- добавь в red_flags: 'answer repeated'\n"
            "- answer_quality снижается на 1-2 пункта\n\n"
            "АБСОЛЮТНЫЕ ЗАПРЕТЫ:\n"
            "- НЕ давай answer_quality > 3 для ответов короче 10 слов\n"
            "- НЕ давай answer_quality > 5 для ответов без единого конкретного примера\n"
            "- НЕ давай answer_quality > 8 без конкретного механизма, личного вклада или trade-off рассуждения\n"
            "- НЕ записывай в skills_mentioned широкие термины (api, backend, database) без личного опыта\n"
            "- Для Frontend: слова React/Angular/setState/DevTools/CSS/Grid сами по себе НЕ подтверждают навык. Нужен пример личной разработки, отладки или изменения UI с проверкой результата.\n"
            "- Для Frontend: сопровождение мобильного приложения, Grafana/логи/incident management учитывай как support/incident diagnostics, а НЕ как frontend development.\n"
            "- Практический блок без кода/артефакта/конкретного решения НЕ засчитывай как практический технический навык.\n\n"
            "Шкала answer_quality: 1-3 = нет ответа/слишком коротко/уклонение, "
            "4-5 = поверхностно/без примеров, 5-6 = рабочие знания с примерами, "
            "7-8 = конкретика + trade-offs + результаты, 9-10 = экспертное мышление.\n"
            "Большинство ответов реальных кандидатов: 4-6. Не завышай.\n\n"
            "AI-генерация признаки: буллет-пойнты без просьбы, фразы 'Certainly/Great question/In conclusion', "
            "идеальное покрытие всех аспектов без личных примеров, академический тон, "
            "ответ на незаданные вопросы. Живой человек: личные примеры, неполные мысли, "
            "специфические детали, неформальный язык.\n\n"
            f"ВАЖНО: все свободные текстовые поля ответа (`evidence`, `red_flags`, `communication_style`, `problem_solving_evidence`) верни на {output_language}. "
            "Enum-значения (`specificity`, `depth`, `proficiency`, `problem_solving_approach`, `leadership_ownership`) оставь в допустимом формате schema."
        )

        try:
            response = await self._create_completion_with_model_fallback(
                model_override=model_override,
                runtime_settings=runtime_settings,
                max_tokens=settings.ASSESSMENT_MAX_OUTPUT_TOKENS,
                temperature=settings.ASSESSMENT_TEMPERATURE,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"Транскрипт:\n\n{transcript}"},
                ],
                tools=[_QUESTION_ANALYSIS_TOOL],
                tool_choice={"type": "function", "function": {"name": "submit_question_analysis"}},
            )
            data = self._load_structured_payload(response)
            resolved_model = str(getattr(response, "actual_model_used", "") or resolve_llm_runtime_model(model_override))
            return data.get("questions", []), resolved_model
        except Exception:
            logger.exception("Pass 1 (question analysis) failed, continuing with empty analysis")
            if runtime_settings is not None:
                return [], runtime_settings_from_payload(runtime_settings, role="assessor").model
            return [], resolve_llm_runtime_model(model_override)

    async def _pass2_competency_scoring(
        self,
        role_label: str,
        transcript: str,
        comp_ref: str,
        pass1_data: list[dict],
        target_role: str,
        message_history: list[dict] | None = None,
        report_language: str = "ru",
        summary_model: dict[str, Any] | None = None,
        interview_meta: dict[str, Any] | None = None,
        model_override: str | None = None,
        runtime_settings: dict | None = None,
    ) -> AssessmentResult:
        """Pass 2: Score each competency using Pass 1 evidence + BARS calibration."""
        pass1_summary = json.dumps(pass1_data, ensure_ascii=False, indent=2) if pass1_data else "Анализ вопросов недоступен."

        # Determine which categories are present for targeted BARS anchors
        from app.ai.competencies import get_competencies as _get_comps
        categories_present = list({c.category for c in _get_comps(target_role)})
        calibration_block = build_calibration_prompt(categories_present)
        output_language = "русском" if report_language == "ru" else "English"

        system = (
            f"Ты — строгий старший интервьюер, оценивающий кандидата на позицию «{role_label}».\n"
            "Ты оцениваешь как скептик: любое утверждение без доказательства не засчитывается.\n\n"
            "## Матрица компетенций\n"
            f"{comp_ref}\n\n"
            f"{calibration_block}\n\n"
            "## Задача\n"
            "На основе транскрипта и анализа вопросов (Pass 1):\n"
            "1. Выставь балл (1-10) для КАЖДОЙ компетенции, строго следуя BARS выше\n"
            "2. evidence: ОБЯЗАТЕЛЬНО содержит прямую цитату или конкретный факт из транскрипта\n"
            "3. reasoning: объясняет ПОЧЕМУ именно этот балл (не просто пересказ ответа)\n"
            "4. 3-5 strengths и 2-4 weaknesses с конкретными примерами из ответов\n"
            "5. response_consistency (0-10): насколько ответы не противоречат друг другу\n"
            "6. red_flags с severity для каждого выявленного сигнала\n"
            "7. hiring_recommendation: strong_yes (≥8.5), yes (7.0–8.4), maybe (5.5–6.9), no (<5.5)\n\n"
            "## ЖЁСТКИЕ ПРАВИЛА SCORING — НЕЛЬЗЯ НАРУШАТЬ\n\n"
            "НЕТ ДОКАЗАТЕЛЬСТВ = НИЗКИЙ БАЛЛ:\n"
            "- Если не можешь процитировать конкретный пример из транскрипта → score ≤ 4\n"
            "- evidence = пересказ/общие слова → score ≤ 5\n"
            "- Каждый score выше 5 ТРЕБУЕТ реальной цитаты с конкретикой\n\n"
            "ЖЁСТКИЕ ПОТОЛКИ:\n"
            "- Score > 7: требует метрик, trade-offs И прямых цитат\n"
            "- Score > 6: требует хотя бы одного реального примера с объяснением КАК/ПОЧЕМУ\n"
            "- Score > 5: требует упоминания конкретной технологии с личным опытом\n"
            "- Score > 4: требует хотя бы базового понимания своими словами\n\n"
            "ПРАВИЛО КРИТИЧЕСКОЙ СЛАБОСТИ:\n"
            "- Если ≥1 компетенция scored ≤ 4 → overall взвешенное среднее ДОЛЖНО быть ≤ 6\n"
            "- Если ≥2 компетенции scored ≤ 3 → overall ДОЛЖНО быть ≤ 5\n"
            "- hiring_recommendation 'yes' или 'strong_yes' ЗАПРЕЩЕНО если любая ключевая компетенция ≤ 4\n\n"
            "PHILOSOPHY:\n"
            "- Слабые кандидаты: 3-5. Средние: 5-6. Хорошие: 7-8. Исключительные: 9-10.\n"
            "- При сомнении — снижай. Цена false-positive выше чем false-negative.\n"
            "- Не давай credit за намерения — только за доказанные знания и опыт.\n\n"
            "## ROLE MISMATCH И FRONTEND-SPECIFIC ПРАВИЛА\n\n"
            "- Если целевая роль Frontend, а ответы в основном про support/incident/monitoring/Grafana/logs/операционное сопровождение, отметь role mismatch.\n"
            "- После 1–2 слабых frontend-core проверок НЕ выдавай высокий frontend score за support answers.\n"
            "- UI Framework Mastery, JavaScript/TypeScript, CSS, Accessibility и Testing не могут быть >4 без доказанного личного frontend-примера.\n"
            "- Фраза «React/Angular», «Реактангуляр», «setState», «DevTools» без примера = mentioned/no evidence, не confirmed skill.\n"
            "- «Я добавил grid» без деталей разметки, responsive-поведения, ограничений или проверки результата = слабый CSS evidence, не сильный CSS skill.\n"
            "- Incident diagnostics можно учитывать отдельно в problem_solving/debugging, но не как подтверждение frontend-core.\n"
            "- Практическое задание без кода или конкретного письменного решения не повышает technical_core.\n\n"
            "## ОЦЕНКА МЯГКИХ НАВЫКОВ, КОММУНИКАЦИИ И РЕШЕНИЯ ЗАДАЧ (Pass 2)\n\n"
            "При выставлении оценок по компетенциям категорий 'communication', 'problem_solving' и 'behavioral', опирайся на анализ вопросов (Pass 1) и следуй строгим критериям:\n\n"
            "1. КОММУНИКАЦИЯ (competencies in 'communication' category):\n"
            "- Оценка 7+: Требует, чтобы кандидат структурировал большинство ответов по методу STAR (Situation, Task, Action, Result) или другой ясной логической схеме (проверить поле communication_star_structured = true в Pass 1). Речь должна быть ясной, структурированной и лаконичной, с фокусом на главном.\n"
            "- Оценка 5-6: Кандидат излагает мысли понятно, но требует наводящих вопросов для структурирования, допускает незначительную «воду» или сумбурность.\n"
            "- Оценка ≤ 4: Кандидат уходит от ответов, излагает мысли хаотично, речь перегружена «водой» или jargon без адаптации под слушателя.\n\n"
            "2. РЕШЕНИЕ ЗАДАЧ (competencies in 'problem_solving' category):\n"
            "- Оценка 7+: Требует явных доказательств мышления от первых принципов (first_principles) или системной декомпозиции (structured_decomposition) в ответах. Кандидат должен четко описывать формулирование гипотез, изоляцию переменных, анализ ограничений и trade-offs.\n"
            "- Оценка 5-6: Кандидат решает проблемы по готовым инструкциям или методом проб и ошибок (trial_and_error), но понимает базовые принципы.\n"
            "- Оценка ≤ 4: Кандидат полагается исключительно на заученные шаблоны и поверхностную зубрежку (superficial_heuristics) без понимания сути процессов, либо не может описать подход к диагностике.\n\n"
            "3. ПОВЕДЕНЧЕСКИЕ НАВЫКИ И ЛИДЕРСТВО (competencies in 'behavioral' category):\n"
            "- Оценка 7+: Требует высокого уровня личной ответственности (strong_ownership - проактивное решение проблем, принятие ответственности за результаты и ошибки, выводы на будущее) или сильного командного взаимодействия (collaborative - координация, менторство, конструктивное разрешение конфликтов).\n"
            "- Оценка 5-6: Кандидат демонстрирует стабильное выполнение задач в качестве пассивного исполнителя (passive_execution), без проактивности или глубокого понимания бизнес-целей.\n"
            "- Оценка ≤ 3: Замечено перекладывание ответственности (blame_shifting) на коллег, технологии, внешние обстоятельства или руководство.\n\n"
            f"ВАЖНО: все свободные текстовые поля (`evidence`, `reasoning`, `strengths`, `weaknesses`, "
            f"`recommendations`, `interview_summary`, `red_flags.flag`, `red_flags.evidence`) верни на {output_language}. "
            "Enum-значения и числовые поля не переводить."
        )

        user_content = (
            f"## Транскрипт\n{transcript}\n\n"
            f"## Анализ вопросов (Pass 1)\n{pass1_summary}"
        )

        try:
            response = await self._create_completion_with_model_fallback(
                model_override=model_override,
                runtime_settings=runtime_settings,
                max_tokens=settings.ASSESSMENT_MAX_OUTPUT_TOKENS,
                temperature=settings.ASSESSMENT_TEMPERATURE,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
                tools=[_COMPETENCY_ASSESSMENT_TOOL],
                tool_choice={"type": "function", "function": {"name": "submit_competency_assessment"}},
            )
            data: dict = self._load_structured_payload(response)
            resolved_model = str(getattr(response, "actual_model_used", "") or resolve_llm_runtime_model(model_override))
        except Exception:
            logger.exception("Pass 2 (competency scoring) failed, falling back to legacy assessment")
            try:
                return await self._legacy_assess(
                    target_role,
                    transcript,
                    report_language,
                    model_override=model_override,
                    runtime_settings=runtime_settings,
                )
            except Exception as exc:
                logger.exception("Legacy assessment failed")
                raise RuntimeError("AI assessment failed completely") from exc

        comp_scores = data.get("competency_scores", [])
        role_mismatch = _detect_role_mismatch(
            target_role=target_role,
            message_history=message_history,
            per_question_analysis=pass1_data,
        )
        role_mismatch_penalties = _apply_role_mismatch_caps(
            target_role=target_role,
            competency_scores=comp_scores,
            role_mismatch=role_mismatch,
        )
        raw_aggregates = _compute_aggregates(comp_scores, target_role)

        # v2-strict: compute answer quality metrics and apply hard score penalties
        answer_metrics = _compute_answer_metrics(pass1_data, message_history or [])
        response_consistency = data.get("response_consistency")
        aggregates, penalties = _apply_score_penalties(
            raw_aggregates,
            answer_metrics,
            comp_scores,
            _to_float(response_consistency) if response_consistency is not None else None,
        )

        # Merge LLM red flags with Python-generated red flags
        llm_red_flags = data.get("red_flags", [])
        generated_flags = [
            {"flag": f, "evidence": "auto-detected by scoring engine", "severity": "medium"}
            for f in answer_metrics["generated_red_flags"]
        ]
        if bool(role_mismatch.get("detected")):
            generated_flags.append(
                {
                    "flag": "role mismatch: support/incident profile vs frontend role",
                    "evidence": "; ".join(role_mismatch.get("support_incident_evidence") or [])
                    or "support/incident evidence without confirmed frontend-core delivery",
                    "severity": "high",
                }
            )
        all_red_flags = llm_red_flags + generated_flags

        # Clamp hiring_recommendation to match penalized overall score
        overall = aggregates["overall_score"]
        llm_rec = data.get("hiring_recommendation", "maybe")
        if bool(role_mismatch.get("detected")) and target_role == "frontend_engineer" and llm_rec in {"yes", "strong_yes"}:
            hiring_rec = "maybe" if overall >= 5.0 else "no"
        elif overall <= 5.0 and llm_rec in ("yes", "strong_yes"):
            hiring_rec = "no"
        elif overall <= 6.9 and llm_rec == "strong_yes":
            hiring_rec = "maybe"
        else:
            hiring_rec = llm_rec

        skill_tags = _aggregate_skills(pass1_data, message_history=message_history)
        summary_model_safe = summary_model if isinstance(summary_model, dict) else {}
        interview_meta_safe = interview_meta if isinstance(interview_meta, dict) else {}
        confidence_metrics = _compute_confidence_metrics(
            comp_scores,
            pass1_data,
            summary_model=summary_model_safe,
            interview_meta=interview_meta_safe,
        )

        full_json = {
            "competency_scores": comp_scores,
            "per_question_analysis": pass1_data,
            "skill_tags": skill_tags,
            "red_flags": all_red_flags,
            "response_consistency": response_consistency,
            "aggregates": aggregates,
            "overall_confidence": confidence_metrics["overall_confidence"],
            "confidence_verdict": confidence_metrics["confidence_verdict"],
            "competency_confidence": confidence_metrics["competency_confidence"],
            "confidence_reasons": confidence_metrics["confidence_reasons"],
            "evidence_coverage": confidence_metrics["evidence_coverage"],
            "decision_policy_version": _DECISION_POLICY_VERSION,
            "aggregates_pre_penalty": raw_aggregates,
            # v2-strict fields
            "answer_quality_score": answer_metrics["answer_quality_score"],
            "depth_score": answer_metrics["depth_score"],
            "consistency_score": response_consistency,
            "score_penalties": [*penalties, *role_mismatch_penalties],
            "role_mismatch": role_mismatch,
            "role_mismatch_penalties": role_mismatch_penalties,
            "answer_metrics": {
                "avg_word_count": answer_metrics["avg_word_count"],
                "short_answer_ratio": answer_metrics["short_answer_ratio"],
                "low_specificity_ratio": answer_metrics["low_specificity_ratio"],
            },
        }

        return AssessmentResult(
            overall_score=aggregates["overall_score"],
            hard_skills_score=aggregates["hard_skills_score"],
            soft_skills_score=aggregates["soft_skills_score"],
            communication_score=aggregates["communication_score"],
            problem_solving_score=aggregates["problem_solving_score"],
            strengths=data.get("strengths", []),
            weaknesses=data.get("weaknesses", []),
            recommendations=data.get("recommendations", []),
            hiring_recommendation=hiring_rec,
            interview_summary=data.get("interview_summary"),
            model_version=resolved_model,
            full_report_json=full_json,
            competency_scores=comp_scores,
            per_question_analysis=pass1_data,
            skill_tags=skill_tags,
            red_flags=all_red_flags,
            response_consistency=response_consistency,
            overall_confidence=confidence_metrics["overall_confidence"],
            competency_confidence=confidence_metrics["competency_confidence"],
            confidence_reasons=confidence_metrics["confidence_reasons"],
            evidence_coverage=confidence_metrics["evidence_coverage"],
            decision_policy_version=_DECISION_POLICY_VERSION,
            answer_quality_score=answer_metrics["answer_quality_score"],
            depth_score=answer_metrics["depth_score"],
            consistency_score=_to_float(response_consistency),
            score_penalties=[*penalties, *role_mismatch_penalties],
        )

    async def _legacy_assess(
        self,
        target_role: str,
        transcript: str,
        report_language: str = "ru",
        model_override: str | None = None,
        runtime_settings: dict | None = None,
    ) -> AssessmentResult:
        """Fallback single-pass assessment (backward compat)."""
        role_label = _role_label(target_role, report_language)
        system = (
            f"Ты — эксперт по оценке кандидатов на позицию «{role_label}».\n"
            f"Объективно оцени кандидата. Будь конкретным. Все текстовые поля верни на "
            f"{'русском' if report_language == 'ru' else 'English'}."
        )

        response = await self._create_completion_with_model_fallback(
            model_override=model_override,
            runtime_settings=runtime_settings,
            max_tokens=settings.ASSESSMENT_MAX_OUTPUT_TOKENS,
            temperature=settings.ASSESSMENT_TEMPERATURE,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"Транскрипт собеседования:\n\n{transcript}"},
            ],
            tools=[_ASSESSMENT_TOOL],
            tool_choice={"type": "function", "function": {"name": "submit_assessment"}},
        )

        data: dict = self._load_structured_payload(response)
        resolved_model = str(getattr(response, "actual_model_used", "") or resolve_llm_runtime_model(model_override))
        confidence_metrics = _compute_confidence_metrics([], [])
        data["overall_confidence"] = confidence_metrics["overall_confidence"]
        data["confidence_verdict"] = confidence_metrics["confidence_verdict"]
        data["competency_confidence"] = confidence_metrics["competency_confidence"]
        data["confidence_reasons"] = confidence_metrics["confidence_reasons"]
        data["evidence_coverage"] = confidence_metrics["evidence_coverage"]
        data["decision_policy_version"] = _DECISION_POLICY_VERSION

        return AssessmentResult(
            overall_score=float(data["overall_score"]),
            hard_skills_score=float(data["hard_skills_score"]),
            soft_skills_score=float(data["soft_skills_score"]),
            communication_score=float(data["communication_score"]),
            strengths=data["strengths"],
            weaknesses=data["weaknesses"],
            recommendations=data["recommendations"],
            hiring_recommendation=data["hiring_recommendation"],
            interview_summary=data.get("interview_summary"),
            model_version=resolved_model,
            full_report_json=data,
            overall_confidence=confidence_metrics["overall_confidence"],
            competency_confidence=confidence_metrics["competency_confidence"],
            confidence_reasons=confidence_metrics["confidence_reasons"],
            evidence_coverage=confidence_metrics["evidence_coverage"],
            decision_policy_version=_DECISION_POLICY_VERSION,
        )


# ---------------------------------------------------------------------------
# Disabled Fallback (no API key)
# ---------------------------------------------------------------------------

class DisabledAssessor:
    async def assess(
        self,
        target_role: str,
        message_history: list[dict],
        message_timestamps: list[dict] | None = None,
        behavioral_signals: dict | None = None,
        language: str = "ru",
        interview_meta: dict | None = None,
        model_override: str | None = None,
    ) -> AssessmentResult:
        raise RuntimeError("AI assessor is not configured")


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

try:
    _provider = get_llm_provider(settings)
except Exception:
    _provider = None

if _provider:
    assessor = LLMAssessor(provider=_provider)
else:
    assessor = DisabledAssessor()  # type: ignore[assignment]
