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


def _normalized_report_language(language: str | None) -> str:
    return "en" if (language or "").lower().startswith("en") else "ru"


def _role_label(target_role: str, language: str | None) -> str:
    normalized = _normalized_report_language(language)
    if normalized == "en":
        return _ROLE_LABELS_EN.get(target_role, target_role.replace("_", " ").title())
    return _ROLE_LABELS.get(target_role, target_role.replace("_", " "))

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


def _aggregate_skills(per_question: list[dict]) -> list[dict]:
    """Aggregate skill tags from per-question analysis with evidence gating."""
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

    skill_map: dict[str, dict] = {}
    for q in per_question:
        question_confidence = _question_evidence_confidence(q)
        if question_confidence < 0.6:
            continue
        for sm in q.get("skills_mentioned", []):
            name = _normalize_skill_name(str(sm.get("skill", "")))
            if _is_noise_skill(name):
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
            "УКЛОНЧИВЫЙ ОТВЕТ (не отвечает на вопрос):\n"
            "- answer_quality ОБЯЗАН быть ≤ 3\n"
            "- добавь в red_flags: 'evasive — question avoided'\n\n"
            "ПОВТОРЯЮЩИЙСЯ ОТВЕТ (то же самое что в предыдущих вопросах):\n"
            "- добавь в red_flags: 'answer repeated'\n"
            "- answer_quality снижается на 1-2 пункта\n\n"
            "АБСОЛЮТНЫЕ ЗАПРЕТЫ:\n"
            "- НЕ давай answer_quality > 3 для ответов короче 10 слов\n"
            "- НЕ давай answer_quality > 5 для ответов без единого конкретного примера\n"
            "- НЕ давай answer_quality > 7 без прямой цитаты с trade-off рассуждением\n"
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
            return await self._legacy_assess(target_role, transcript, report_language)

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

        skill_tags = _aggregate_skills(pass1_data)
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
    ) -> AssessmentResult:
        report_language = _normalized_report_language(language)
        candidate_msgs = [m for m in message_history if m["role"] == "candidate"]
        response_count = len(candidate_msgs)
        base = min(4.5 + response_count * 0.45, 8.5)

        competencies = get_competencies(target_role)
        comp_scores = []
        for comp in competencies:
            # Vary score slightly per competency for realistic mock
            import random
            score = round(min(max(base + random.uniform(-1.0, 1.0), 1.0), 10.0), 1)
            comp_scores.append({
                "competency": comp.name,
                "category": comp.category,
                "score": score,
                "weight": comp.weight,
                "evidence": (
                    f"Тестовое подтверждение по компетенции «{comp.name}»"
                    if report_language == "ru"
                    else f"Mock evidence for {comp.name}"
                ),
                "reasoning": (
                    f"Балл {score}: основано на {response_count} ответах"
                    if report_language == "ru"
                    else f"Score {score}: based on {response_count} responses"
                ),
            })

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

        per_q = []
        q_num = 0
        for msg in message_history:
            if msg["role"] == "assistant":
                q_num += 1
            elif msg["role"] == "candidate":
                per_q.append({
                    "question_number": q_num,
                    "targeted_competencies": [competencies[min(q_num - 1, len(competencies) - 1)].name],
                    "answer_quality": round(base, 1),
                    "evidence": "Тестовое подтверждение из ответа" if report_language == "ru" else "Mock evidence from response",
                    "skills_mentioned": [],
                    "red_flags": [],
                    "specificity": "medium",
                    "depth": "adequate",
                    "ai_likelihood": 0.0,
                })

        role_label = _role_label(target_role, report_language)
        confidence_metrics = _compute_confidence_metrics(comp_scores, per_q)
        full_json = {
            "competency_scores": comp_scores,
            "per_question_analysis": per_q,
            "skill_tags": [],
            "red_flags": [],
            "response_consistency": round(base, 1),
            "aggregates": aggregates,
            "overall_confidence": confidence_metrics["overall_confidence"],
            "competency_confidence": confidence_metrics["competency_confidence"],
            "confidence_reasons": confidence_metrics["confidence_reasons"],
            "evidence_coverage": confidence_metrics["evidence_coverage"],
            "decision_policy_version": _DECISION_POLICY_VERSION,
            "mock": True,
        }

        cheat_risk, cheat_flags = _compute_cheat_risk(behavioral_signals, per_q)

        return AssessmentResult(
            overall_score=overall,
            hard_skills_score=aggregates["hard_skills_score"],
            soft_skills_score=aggregates["soft_skills_score"],
            communication_score=aggregates["communication_score"],
            problem_solving_score=aggregates["problem_solving_score"],
            strengths=["Завершил полное структурированное собеседование"],
            weaknesses=["Ответы могут включать более конкретные метрики"],
            recommendations=["Используйте формат STAR для ответов"],
            hiring_recommendation=recommendation,
            interview_summary=(
                f"Кандидат прошёл собеседование из {response_count} вопросов на позицию {role_label}. "
                f"Общий балл: {overall}/10."
                if report_language == "ru"
                else f"The candidate completed an interview with {response_count} questions for the {role_label} role. "
                     f"Overall score: {overall}/10."
            ),
            model_version="mock-v1",
            full_report_json=full_json,
            competency_scores=comp_scores,
            per_question_analysis=per_q,
            skill_tags=[],
            red_flags=[],
            response_consistency=round(base, 1),
            cheat_risk_score=cheat_risk,
            cheat_flags=cheat_flags,
            overall_confidence=confidence_metrics["overall_confidence"],
            competency_confidence=confidence_metrics["competency_confidence"],
            confidence_reasons=confidence_metrics["confidence_reasons"],
            evidence_coverage=confidence_metrics["evidence_coverage"],
            decision_policy_version=_DECISION_POLICY_VERSION,
        )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

if settings.GROQ_API_KEY:
    assessor = LLMAssessor(client=AsyncGroq(api_key=settings.GROQ_API_KEY))
else:
    assessor = MockAssessor()  # type: ignore[assignment]
