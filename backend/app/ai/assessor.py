"""
AI Assessor module — two-pass scientific assessment pipeline.

Pass 1: Per-question evidence extraction (answer quality, skills, red flags).
Pass 2: Competency scoring with evidence aggregation.

Singleton `assessor` is an LLMAssessor (Groq) when GROQ_API_KEY is set,
otherwise falls back to MockAssessor.
"""
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

from groq import AsyncGroq

from app.ai.calibration import build_calibration_prompt
from app.ai.competencies import get_competencies, get_category_weights
from app.ai.interviewer import classify_answer, extract_mentioned_technologies
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
                        },
                        "required": [
                            "question_number", "targeted_competencies",
                            "answer_quality", "evidence", "skills_mentioned",
                            "red_flags", "specificity", "depth", "ai_likelihood",
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

        topic_outcomes.append(
            {
                "slot": idx + 1,
                "label": _topic_label(topic, idx + 1),
                "signal": signal or "unknown",
                "outcome": outcome,
                "verification_target": topic.get("verification_target"),
                "evidence_hint": _slot_evidence_hint(slot_questions),
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

    recommendation_rank = {"no": 0, "maybe": 1, "yes": 2, "strong_yes": 3}
    max_allowed = "strong_yes"

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

    if overall_confidence < 0.45:
        max_allowed = min((max_allowed, "maybe"), key=lambda item: recommendation_rank[item])
        reasons.append("low overall confidence limits recommendation")

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
    implementation_code_excerpt = _extract_code_excerpt(answers_by_stage.get("implementation", []))

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

        stage_answers = answers_by_stage.get(stage_key, [])
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
    implementation_answers = answers_by_stage.get("implementation", [])
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
    ]

    if overall_score is not None and coverage_score is not None:
        overall_score = round((overall_score * 0.85) + (coverage_score * 0.15), 1)

    return {
        "module_title": str(interview_meta.get("module_title") or "").strip() or None,
        "scenario_id": scenario_id,
        "scenario_title": str(interview_meta.get("module_scenario_title") or "").strip() or None,
        "scenario_prompt": str(interview_meta.get("module_scenario_prompt") or "").strip() or None,
        "stage_count": len(stages),
        "overall_score": overall_score,
        "rubric_scores": rubric_scores,
        "stages": stages,
        "implementation_excerpt": implementation_code_excerpt,
        "has_code_submission": has_code_submission,
        "code_signal_score": code_signal_score,
        "coverage_score": coverage_score,
        "coverage_checks": coverage_checks,
    }


def _apply_score_penalties(
    aggregates: dict[str, float],
    answer_metrics: dict,
    competency_scores: list[dict],
) -> tuple[dict[str, float], list[str]]:
    """Apply deterministic hard caps on scores to prevent inflation.

    Rules (applied after LLM scoring):
    - Short answers (>30% < 10 words)   → cap all scores at 6
    - Generic answers (>50% low specificity) → cap at 6
    - Weak answers (avg quality < 4.5)  → cap at 5
    - ≥1 competency scored ≤ 4          → cap overall at 6
    - ≥2 competencies scored ≤ 3        → cap overall at 5
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


def _compute_confidence_metrics(
    competency_scores: list[dict],
    per_question_analysis: list[dict],
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
        evidence_bonus = min(evidence_len / 240.0, 1.0) * 0.15
        score = max(0.0, min(base + evidence_bonus, 1.0))
        competency_confidence[name] = round(score, 2)

        weight = max(_to_float(cs.get("weight"), 0.0), 0.0) or 1.0
        weighted_sum += score * weight
        total_weight += weight

    if total_weight > 0:
        overall_conf = weighted_sum / total_weight
    elif question_confidences:
        overall_conf = sum(question_confidences) / len(question_confidences)
    else:
        overall_conf = 0.0
    overall_conf = round(max(0.0, min(overall_conf, 1.0)), 2)

    analyzed_questions = len(per_question_analysis)
    high_conf_q = sum(1 for c in question_confidences if c >= 0.7)
    low_conf_q = sum(1 for c in question_confidences if c < 0.5)
    avg_ai = round(sum(ai_scores) / len(ai_scores), 2) if ai_scores else None
    coverage_ratio = (
        round(concrete_evidence_count / analyzed_questions, 2)
        if analyzed_questions
        else 0.0
    )

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
        "avg_ai_likelihood": avg_ai,
    }

    return {
        "overall_confidence": overall_conf,
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

    candidate_answers = [
        str(msg.get("content", "") or "")
        for msg in (message_history or [])
        if str(msg.get("role", "")) == "candidate" and str(msg.get("content", "")).strip()
    ]
    candidate_corpus = " ".join(candidate_answers).lower()
    candidate_tech_mentions = set()
    for answer in candidate_answers:
        candidate_tech_mentions.update(extract_mentioned_technologies(answer))

    def _skill_has_candidate_evidence(skill: str) -> bool:
        if not candidate_answers:
            # Backward-compatible fallback for cases where we only have pass1.
            return True
        pattern = re.compile(rf"\b{re.escape(skill)}\b")
        for answer in candidate_answers:
            answer_lower = answer.lower()
            for match in pattern.finditer(answer_lower):
                start = max(0, match.start() - 80)
                end = min(len(answer_lower), match.end() + 80)
                window = answer_lower[start:end]
                if any(marker in window for marker in action_markers):
                    return True
                if any(marker in window for marker in context_markers):
                    return True
                if re.search(r"\d", window):
                    return True

        if skill in candidate_tech_mentions:
            # Extracted mention exists but without local action context.
            # Require repeated explicit mentions to avoid false-positive single hits.
            return sum(1 for answer in candidate_answers if pattern.search(answer.lower())) >= 2

        matches = list(pattern.finditer(candidate_corpus))
        if not matches:
            return False
        if len(matches) >= 2:
            return True
        for match in matches:
            start = max(0, match.start() - 80)
            end = min(len(candidate_corpus), match.end() + 80)
            window = candidate_corpus[start:end]
            if any(marker in window for marker in action_markers):
                return True
        return False

    skill_map: dict[str, dict] = {}
    for q in per_question:
        question_confidence = _question_evidence_confidence(q)
        if question_confidence < 0.6:
            continue
        for sm in q.get("skills_mentioned", []):
            name = _normalize_skill_name(str(sm.get("skill", "")))
            if _is_noise_skill(name):
                continue
            if not _skill_has_candidate_evidence(name):
                continue
            prof = str(sm.get("proficiency", "intermediate")).lower()
            if prof not in proficiency_order:
                prof = "intermediate"
            if name in skill_map:
                skill_map[name]["mentions_count"] += 1
                skill_map[name]["confidence_sum"] += question_confidence
                if proficiency_order.index(prof) > proficiency_order.index(skill_map[name]["proficiency"]):
                    skill_map[name]["proficiency"] = prof
            else:
                skill_map[name] = {
                    "skill": name,
                    "proficiency": prof,
                    "mentions_count": 1,
                    "confidence_sum": question_confidence,
                }

    filtered: list[dict] = []
    for data in skill_map.values():
        avg_confidence = data["confidence_sum"] / data["mentions_count"]
        # Single low-confidence mention is often noisy extraction.
        if data["mentions_count"] == 1 and avg_confidence < 0.75:
            continue
        if avg_confidence < 0.65:
            continue
        filtered.append(
            {
                "skill": data["skill"],
                "proficiency": data["proficiency"],
                "mentions_count": data["mentions_count"],
            }
        )

    return sorted(filtered, key=lambda x: x["mentions_count"], reverse=True)


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


def _build_mock_question_analysis(
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
            }
        )

    return per_q


def _build_mock_competency_scores(
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
        answer_quality = _to_float(question_item.get("answer_quality"), 5.0)
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
                score = max(6.0, min(answer_quality, 7.4))
                if depth in {"strong", "expert"}:
                    score = max(score, 7.1)
                if specificity == "high":
                    score = max(score, 6.9)
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
        category: round(sum(scores) / len(scores), 1)
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
                "score": category_fallbacks.get(comp.category, 5.0),
                "weight": comp.weight,
                "evidence": "Fallback topic coverage",
                "reasoning": "No direct topic mapping available.",
            }
        )
    return comp_scores


# ---------------------------------------------------------------------------
# LLM implementation (Groq) — two-pass assessment
# ---------------------------------------------------------------------------

class LLMAssessor:
    """Generates structured assessment reports via Groq API (two-pass)."""

    def __init__(self, client: AsyncGroq) -> None:
        self._client = client

    async def assess(
        self,
        target_role: str,
        message_history: list[dict],
        message_timestamps: list[dict] | None = None,
        behavioral_signals: dict | None = None,
        language: str = "ru",
        interview_meta: dict | None = None,
    ) -> AssessmentResult:
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
        pass1_data = await self._pass1_question_analysis(
            role_label, transcript, comp_ref, report_language
        )

        # Pass 2: Competency scoring (message_history needed for word-count penalization)
        result = await self._pass2_competency_scoring(
            role_label, transcript, comp_ref, pass1_data, target_role, message_history, report_language
        )

        summary_model = _build_summary_model(target_role, report_language, interview_meta, pass1_data)
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
        coding_task_evaluation = _build_coding_task_evaluation(
            interview_meta,
            result.per_question_analysis,
            message_history,
            report_language,
        )
        if coding_task_evaluation:
            result.full_report_json["coding_task_evaluation"] = coding_task_evaluation
        result.full_report_json["aggregates"] = adjusted_aggregates
        result.full_report_json["score_penalties"] = result.full_report_json.get("score_penalties", []) + summary_penalties
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
    ) -> list[dict]:
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
            "7. Вероятность AI-генерации (ai_likelihood 0.0-1.0)\n\n"
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
            "- НЕ записывай в skills_mentioned широкие термины (api, backend, database) без личного опыта\n\n"
            "Шкала answer_quality: 1-3 = нет ответа/слишком коротко/уклонение, "
            "4-5 = поверхностно/без примеров, 5-6 = рабочие знания с примерами, "
            "7-8 = конкретика + trade-offs + результаты, 9-10 = экспертное мышление.\n"
            "Большинство ответов реальных кандидатов: 4-6. Не завышай.\n\n"
            "AI-генерация признаки: буллет-пойнты без просьбы, фразы 'Certainly/Great question/In conclusion', "
            "идеальное покрытие всех аспектов без личных примеров, академический тон, "
            "ответ на незаданные вопросы. Живой человек: личные примеры, неполные мысли, "
            "специфические детали, неформальный язык.\n\n"
            f"ВАЖНО: все свободные текстовые поля ответа (`evidence`, `red_flags`) верни на {output_language}. "
            "Enum-значения (`specificity`, `depth`, `proficiency`) оставь в допустимом формате schema."
        )

        try:
            response = await self._client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                max_tokens=2048,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"Транскрипт:\n\n{transcript}"},
                ],
                tools=[_QUESTION_ANALYSIS_TOOL],
                tool_choice={"type": "function", "function": {"name": "submit_question_analysis"}},
            )
            tool_call = response.choices[0].message.tool_calls[0]
            data = json.loads(tool_call.function.arguments)
            return data.get("questions", [])
        except Exception:
            logger.exception("Pass 1 (question analysis) failed, continuing with empty analysis")
            return []

    async def _pass2_competency_scoring(
        self,
        role_label: str,
        transcript: str,
        comp_ref: str,
        pass1_data: list[dict],
        target_role: str,
        message_history: list[dict] | None = None,
        report_language: str = "ru",
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
            f"ВАЖНО: все свободные текстовые поля (`evidence`, `reasoning`, `strengths`, `weaknesses`, "
            f"`recommendations`, `interview_summary`, `red_flags.flag`, `red_flags.evidence`) верни на {output_language}. "
            "Enum-значения и числовые поля не переводить."
        )

        user_content = (
            f"## Транскрипт\n{transcript}\n\n"
            f"## Анализ вопросов (Pass 1)\n{pass1_summary}"
        )

        try:
            response = await self._client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                max_tokens=2048,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
                tools=[_COMPETENCY_ASSESSMENT_TOOL],
                tool_choice={"type": "function", "function": {"name": "submit_competency_assessment"}},
            )
            tool_call = response.choices[0].message.tool_calls[0]
            data: dict = json.loads(tool_call.function.arguments)
        except Exception:
            logger.exception("Pass 2 (competency scoring) failed, falling back to legacy assessment")
            try:
                return await self._legacy_assess(target_role, transcript, report_language)
            except Exception:
                logger.exception("Legacy assessment failed, falling back to deterministic mock assessment")
                return await MockAssessor().assess(
                    target_role=target_role,
                    message_history=message_history or [],
                    message_timestamps=None,
                    behavioral_signals=None,
                    language=report_language,
                    interview_meta=None,
                )

        comp_scores = data.get("competency_scores", [])
        aggregates = _compute_aggregates(comp_scores, target_role)

        # v2-strict: compute answer quality metrics and apply hard score penalties
        answer_metrics = _compute_answer_metrics(pass1_data, message_history or [])
        aggregates, penalties = _apply_score_penalties(aggregates, answer_metrics, comp_scores)

        # Merge LLM red flags with Python-generated red flags
        llm_red_flags = data.get("red_flags", [])
        generated_flags = [
            {"flag": f, "evidence": "auto-detected by scoring engine", "severity": "medium"}
            for f in answer_metrics["generated_red_flags"]
        ]
        all_red_flags = llm_red_flags + generated_flags

        # Clamp hiring_recommendation to match penalized overall score
        overall = aggregates["overall_score"]
        llm_rec = data.get("hiring_recommendation", "maybe")
        if overall <= 5.0 and llm_rec in ("yes", "strong_yes"):
            hiring_rec = "no"
        elif overall <= 6.9 and llm_rec == "strong_yes":
            hiring_rec = "maybe"
        else:
            hiring_rec = llm_rec

        skill_tags = _aggregate_skills(pass1_data, message_history=message_history)
        confidence_metrics = _compute_confidence_metrics(comp_scores, pass1_data)
        response_consistency = data.get("response_consistency")

        full_json = {
            "competency_scores": comp_scores,
            "per_question_analysis": pass1_data,
            "skill_tags": skill_tags,
            "red_flags": all_red_flags,
            "response_consistency": response_consistency,
            "aggregates": aggregates,
            "overall_confidence": confidence_metrics["overall_confidence"],
            "competency_confidence": confidence_metrics["competency_confidence"],
            "confidence_reasons": confidence_metrics["confidence_reasons"],
            "evidence_coverage": confidence_metrics["evidence_coverage"],
            "decision_policy_version": _DECISION_POLICY_VERSION,
            # v2-strict fields
            "answer_quality_score": answer_metrics["answer_quality_score"],
            "depth_score": answer_metrics["depth_score"],
            "consistency_score": response_consistency,
            "score_penalties": penalties,
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
            model_version="llama-3.3-70b-versatile",
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
            score_penalties=penalties,
        )

    async def _legacy_assess(self, target_role: str, transcript: str, report_language: str = "ru") -> AssessmentResult:
        """Fallback single-pass assessment (backward compat)."""
        role_label = _role_label(target_role, report_language)
        system = (
            f"Ты — эксперт по оценке кандидатов на позицию «{role_label}».\n"
            f"Объективно оцени кандидата. Будь конкретным. Все текстовые поля верни на "
            f"{'русском' if report_language == 'ru' else 'English'}."
        )

        response = await self._client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=1024,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"Транскрипт собеседования:\n\n{transcript}"},
            ],
            tools=[_ASSESSMENT_TOOL],
            tool_choice={"type": "function", "function": {"name": "submit_assessment"}},
        )

        tool_call = response.choices[0].message.tool_calls[0]
        data: dict = json.loads(tool_call.function.arguments)
        confidence_metrics = _compute_confidence_metrics([], [])
        data["overall_confidence"] = confidence_metrics["overall_confidence"]
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
            model_version="llama-3.3-70b-versatile",
            full_report_json=data,
            overall_confidence=confidence_metrics["overall_confidence"],
            competency_confidence=confidence_metrics["competency_confidence"],
            confidence_reasons=confidence_metrics["confidence_reasons"],
            evidence_coverage=confidence_metrics["evidence_coverage"],
            decision_policy_version=_DECISION_POLICY_VERSION,
        )


# ---------------------------------------------------------------------------
# Mock fallback (no API key)
# ---------------------------------------------------------------------------

class MockAssessor:
    async def assess(
        self,
        target_role: str,
        message_history: list[dict],
        message_timestamps: list[dict] | None = None,
        behavioral_signals: dict | None = None,
        language: str = "ru",
        interview_meta: dict | None = None,
    ) -> AssessmentResult:
        report_language = _normalized_report_language(language)
        per_q = _build_mock_question_analysis(
            message_history=message_history,
            target_role=target_role,
            interview_meta=interview_meta,
            report_language=report_language,
        )
        summary_model = _build_summary_model(target_role, report_language, interview_meta, per_q)
        comp_scores = _build_mock_competency_scores(
            target_role=target_role,
            summary_model=summary_model,
            interview_meta=interview_meta,
            report_language=report_language,
            per_question_analysis=per_q,
        )
        aggregates = _compute_aggregates(comp_scores, target_role)
        overall = aggregates["overall_score"]

        if overall >= 8.5:
            recommendation = "strong_yes"
        elif overall >= 7.0:
            recommendation = "yes"
        elif overall >= 5.5:
            recommendation = "maybe"
        else:
            recommendation = "no"

        response_count = len([m for m in message_history if m["role"] == "candidate"])

        confidence_metrics = _compute_confidence_metrics(comp_scores, per_q)
        answer_metrics = _compute_answer_metrics(per_q, message_history or [])
        adjusted_aggregates, summary_penalties = _apply_summary_penalties(
            aggregates,
            summary_model,
            confidence_metrics,
        )
        overall = adjusted_aggregates["overall_score"]
        strengths, weaknesses, recommendations = _build_outcome_feedback(summary_model, report_language)
        strengths = _prefer_outcome_feedback(
            ["Завершил полное структурированное собеседование"] if report_language == "ru" else ["Completed the full structured interview"],
            strengths,
        )
        weaknesses = _prefer_outcome_feedback(
            ["Ответы могут включать более конкретные метрики"] if report_language == "ru" else ["Answers may include more concrete metrics"],
            weaknesses,
        )
        recommendations = _prefer_outcome_feedback(
            ["Используйте формат STAR для ответов"] if report_language == "ru" else ["Use the STAR format for answers"],
            recommendations,
        )
        recommendation, gate_reasons = _apply_recommendation_gates(
            llm_rec=recommendation,
            overall_score=overall,
            summary_model=summary_model,
            answer_metrics=answer_metrics,
            confidence_metrics=confidence_metrics,
            competency_scores=comp_scores,
        )
        full_json = {
            "competency_scores": comp_scores,
            "per_question_analysis": per_q,
            "skill_tags": _aggregate_skills(per_q, message_history=message_history),
            "red_flags": [],
            "response_consistency": round(min(9.0, max(3.0, overall + 0.4)), 1),
            "aggregates": adjusted_aggregates,
            "overall_confidence": confidence_metrics["overall_confidence"],
            "competency_confidence": confidence_metrics["competency_confidence"],
            "confidence_reasons": confidence_metrics["confidence_reasons"],
            "evidence_coverage": confidence_metrics["evidence_coverage"],
            "decision_policy_version": _DECISION_POLICY_VERSION,
            "summary_model": summary_model,
            "hiring_recommendation": recommendation,
            "recommendation_gate_reasons": gate_reasons,
            "score_penalties": summary_penalties,
            "interview_meta": interview_meta or {},
            "answer_quality_score": answer_metrics["answer_quality_score"],
            "depth_score": answer_metrics["depth_score"],
            "mock": True,
        }
        system_design_evaluation = _build_system_design_evaluation(interview_meta, per_q)
        if system_design_evaluation:
            full_json["system_design_evaluation"] = system_design_evaluation
        coding_task_evaluation = _build_coding_task_evaluation(
            interview_meta,
            per_q,
            message_history,
            report_language,
        )
        if coding_task_evaluation:
            full_json["coding_task_evaluation"] = coding_task_evaluation

        cheat_risk, cheat_flags = _compute_cheat_risk(behavioral_signals, per_q)

        return AssessmentResult(
            overall_score=overall,
            hard_skills_score=adjusted_aggregates["hard_skills_score"],
            soft_skills_score=adjusted_aggregates["soft_skills_score"],
            communication_score=adjusted_aggregates["communication_score"],
            problem_solving_score=adjusted_aggregates["problem_solving_score"],
            strengths=strengths or [],
            weaknesses=weaknesses or [],
            recommendations=recommendations or [],
            hiring_recommendation=recommendation,
            interview_summary=_build_interview_summary_text(
                target_role,
                report_language,
                summary_model,
                overall,
            ),
            model_version="mock-v2-evidence-aware",
            full_report_json=full_json,
            competency_scores=comp_scores,
            per_question_analysis=per_q,
            skill_tags=full_json["skill_tags"],
            red_flags=[],
            response_consistency=full_json["response_consistency"],
            cheat_risk_score=cheat_risk,
            cheat_flags=cheat_flags,
            overall_confidence=confidence_metrics["overall_confidence"],
            competency_confidence=confidence_metrics["competency_confidence"],
            confidence_reasons=confidence_metrics["confidence_reasons"],
            evidence_coverage=confidence_metrics["evidence_coverage"],
            decision_policy_version=_DECISION_POLICY_VERSION,
        )


class DisabledAssessor:
    async def assess(
        self,
        target_role: str,
        message_history: list[dict],
        message_timestamps: list[dict] | None = None,
        behavioral_signals: dict | None = None,
        language: str = "ru",
        interview_meta: dict | None = None,
    ) -> AssessmentResult:
        raise RuntimeError("AI assessor is not configured")


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

if settings.GROQ_API_KEY:
    assessor = LLMAssessor(client=AsyncGroq(api_key=settings.GROQ_API_KEY))
elif settings.allow_mock_ai:
    assessor = MockAssessor()  # type: ignore[assignment]
else:
    assessor = DisabledAssessor()  # type: ignore[assignment]
