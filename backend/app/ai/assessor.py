"""
AI Assessor module — two-pass scientific assessment pipeline.

Pass 1: Per-question evidence extraction (answer quality, skills, red flags).
Pass 2: Competency scoring with evidence aggregation.

Singleton `assessor` is an LLMAssessor (Groq) when GROQ_API_KEY is set,
otherwise falls back to MockAssessor.
"""
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime

from groq import AsyncGroq

from app.ai.calibration import build_calibration_prompt
from app.ai.competencies import get_competencies, get_category_weights
from app.core.config import settings

logger = logging.getLogger(__name__)

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


def _aggregate_skills(per_question: list[dict]) -> list[dict]:
    """Aggregate skill_tags from per-question analysis, deduplicated."""
    skill_map: dict[str, dict] = {}
    for q in per_question:
        for sm in q.get("skills_mentioned", []):
            name = sm.get("skill", "").strip().lower()
            if not name:
                continue
            prof = sm.get("proficiency", "intermediate")
            if name in skill_map:
                skill_map[name]["mentions_count"] += 1
                # Keep higher proficiency
                prof_order = ["beginner", "intermediate", "advanced", "expert"]
                if prof_order.index(prof) > prof_order.index(skill_map[name]["proficiency"]):
                    skill_map[name]["proficiency"] = prof
            else:
                skill_map[name] = {"skill": name, "proficiency": prof, "mentions_count": 1}
    return sorted(skill_map.values(), key=lambda x: x["mentions_count"], reverse=True)


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
    ) -> AssessmentResult:
        role_label = _ROLE_LABELS.get(target_role, target_role.replace("_", " "))
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
            role_label, transcript, comp_ref
        )

        # Pass 2: Competency scoring
        result = await self._pass2_competency_scoring(
            role_label, transcript, comp_ref, pass1_data, target_role
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
    ) -> list[dict]:
        """Pass 1: Extract per-question evidence, skills, red flags."""
        system = (
            f"Ты — эксперт по оценке кандидатов на позицию «{role_label}».\n"
            "Ты получаешь транскрипт структурированного собеседования.\n\n"
            "## Матрица компетенций\n"
            f"{comp_ref}\n\n"
            "## Задача\n"
            "Для КАЖДОЙ пары вопрос-ответ определи:\n"
            "1. Какие компетенции из матрицы этот вопрос оценивает\n"
            "2. Качество ответа (1-10) с учётом глубины и конкретности\n"
            "3. Конкретные доказательства из ответа (цитаты, примеры)\n"
            "4. Упомянутые технологии/навыки с уровнем владения\n"
            "5. Красные флаги (противоречия, фабрикации, уход от вопроса)\n"
            "6. Конкретность (high/medium/low) и глубина (expert/strong/adequate/surface/none)\n"
            "7. Вероятность AI-генерации (ai_likelihood 0.0-1.0):\n"
            "   Признаки AI: буллет-пойнты без просьбы, фразы 'Certainly/Great question/In conclusion',\n"
            "   идеальное покрытие всех аспектов без личных примеров, академический тон в диалоге,\n"
            "   ответ на незаданные вопросы, слишком правильная структура intro→body→conclusion.\n"
            "   Признаки живого человека: личные примеры ('я делал X'), неполные мысли, паузы,\n"
            "   специфические детали, неформальный язык.\n\n"
            "Будь объективным. Оценивай только по фактическому содержанию ответов.\n"
            "Шкала answer_quality (1-10): 1-4 = нет/поверхностный ответ, 5-6 = рабочие знания без глубины, "
            "7-8 = конкретные примеры + trade-offs, 9-10 = экспертное мышление. "
            "Большинство ответов попадают в диапазон 4-7. Не завышай оценки без цитат."
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
    ) -> AssessmentResult:
        """Pass 2: Score each competency using Pass 1 evidence + BARS calibration."""
        pass1_summary = json.dumps(pass1_data, ensure_ascii=False, indent=2) if pass1_data else "Анализ вопросов недоступен."

        # Determine which categories are present for targeted BARS anchors
        from app.ai.competencies import get_competencies as _get_comps
        categories_present = list({c.category for c in _get_comps(target_role)})
        calibration_block = build_calibration_prompt(categories_present)

        system = (
            f"Ты — эксперт по оценке кандидатов на позицию «{role_label}».\n\n"
            "## Матрица компетенций\n"
            f"{comp_ref}\n\n"
            f"{calibration_block}\n\n"
            "## Задача\n"
            "На основе транскрипта и анализа вопросов (Pass 1):\n"
            "1. Выставь балл (1-10) для КАЖДОЙ компетенции из матрицы, строго следуя BARS выше\n"
            "2. Для каждой оценки: укажи конкретные цитаты из транскрипта как evidence\n"
            "3. reasoning должен объяснять ПОЧЕМУ это именно такой балл по шкале BARS\n"
            "4. Определи 3-5 strengths и 2-4 weaknesses с конкретными примерами из ответов\n"
            "5. Оцени response_consistency (0-10): противоречат ли ответы друг другу\n"
            "6. Выпиши red_flags с severity если есть\n"
            "7. hiring_recommendation: strong_yes (≥8.5), yes (7.0–8.4), maybe (5.5–6.9), no (<5.5)\n\n"
            "ВАЖНО: hiring_recommendation должна соответствовать взвешенному среднему по компетенциям.\n"
            "ВАЖНО: Не давай оценку выше 7 без конкретных цитат с trade-off рассуждением.\n"
            "ВАЖНО: Не давай оценку ниже 5 без конкретного примера неправильного понимания."
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
            return await self._legacy_assess(target_role, transcript)

        comp_scores = data.get("competency_scores", [])
        aggregates = _compute_aggregates(comp_scores, target_role)
        skill_tags = _aggregate_skills(pass1_data)

        full_json = {
            "competency_scores": comp_scores,
            "per_question_analysis": pass1_data,
            "skill_tags": skill_tags,
            "red_flags": data.get("red_flags", []),
            "response_consistency": data.get("response_consistency"),
            "aggregates": aggregates,
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
            hiring_recommendation=data.get("hiring_recommendation", "maybe"),
            interview_summary=data.get("interview_summary"),
            model_version="llama-3.3-70b-versatile",
            full_report_json=full_json,
            competency_scores=comp_scores,
            per_question_analysis=pass1_data,
            skill_tags=skill_tags,
            red_flags=data.get("red_flags", []),
            response_consistency=data.get("response_consistency"),
        )

    async def _legacy_assess(self, target_role: str, transcript: str) -> AssessmentResult:
        """Fallback single-pass assessment (backward compat)."""
        role_label = _ROLE_LABELS.get(target_role, target_role.replace("_", " "))
        system = (
            f"Ты — эксперт по оценке кандидатов на позицию «{role_label}».\n"
            "Объективно оцени кандидата. Будь конкретным."
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
    ) -> AssessmentResult:
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
                "evidence": f"Mock evidence for {comp.name}",
                "reasoning": f"Score {score}: based on {response_count} responses",
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
                    "evidence": "Mock evidence from response",
                    "skills_mentioned": [],
                    "red_flags": [],
                    "specificity": "medium",
                    "depth": "adequate",
                    "ai_likelihood": 0.0,
                })

        role_label = target_role.replace("_", " ")
        full_json = {
            "competency_scores": comp_scores,
            "per_question_analysis": per_q,
            "skill_tags": [],
            "red_flags": [],
            "response_consistency": round(base, 1),
            "aggregates": aggregates,
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
        )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

if settings.GROQ_API_KEY:
    assessor = LLMAssessor(client=AsyncGroq(api_key=settings.GROQ_API_KEY))
else:
    assessor = MockAssessor()  # type: ignore[assignment]
