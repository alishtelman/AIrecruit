"""
AI Assessor module.

Singleton `assessor` is an LLMAssessor (Groq) when GROQ_API_KEY is set,
otherwise falls back to MockAssessor.
"""
import json
from dataclasses import dataclass, field

from groq import AsyncGroq

from app.core.config import settings

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

_ASSESSMENT_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_assessment",
        "description": "Отправить структурированную оценку кандидата по итогам собеседования.",
        "parameters": {
            "type": "object",
            "properties": {
                "overall_score": {
                    "type": "number",
                    "description": "Общий балл от 0 до 10",
                },
                "hard_skills_score": {
                    "type": "number",
                    "description": "Оценка технических навыков от 0 до 10",
                },
                "soft_skills_score": {
                    "type": "number",
                    "description": "Оценка soft skills от 0 до 10",
                },
                "communication_score": {
                    "type": "number",
                    "description": "Оценка коммуникативных навыков от 0 до 10",
                },
                "strengths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "3–5 сильных сторон кандидата",
                },
                "weaknesses": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "2–4 зоны роста кандидата",
                },
                "recommendations": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "2–4 конкретные рекомендации по развитию",
                },
                "hiring_recommendation": {
                    "type": "string",
                    "enum": ["strong_yes", "yes", "maybe", "no"],
                    "description": "Рекомендация по найму",
                },
                "interview_summary": {
                    "type": "string",
                    "description": "Краткое резюме собеседования (2–3 предложения)",
                },
            },
            "required": [
                "overall_score",
                "hard_skills_score",
                "soft_skills_score",
                "communication_score",
                "strengths",
                "weaknesses",
                "recommendations",
                "hiring_recommendation",
                "interview_summary",
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


# ---------------------------------------------------------------------------
# LLM implementation (Groq)
# ---------------------------------------------------------------------------

class LLMAssessor:
    """Generates structured assessment reports via Groq API."""

    def __init__(self, client: AsyncGroq) -> None:
        self._client = client

    async def assess(
        self,
        target_role: str,
        message_history: list[dict],
    ) -> AssessmentResult:
        role_label = _ROLE_LABELS.get(target_role, target_role.replace("_", " "))

        system = (
            f"Ты — эксперт по оценке кандидатов на позицию «{role_label}».\n"
            "Ты получаешь полный транскрипт структурированного собеседования.\n"
            "Объективно оцени кандидата по критериям:\n"
            "- hard_skills_score: технические знания и навыки (0–10)\n"
            "- soft_skills_score: командная работа, лидерство, решение проблем (0–10)\n"
            "- communication_score: ясность, структура, убедительность ответов (0–10)\n"
            "- overall_score: взвешенная итоговая оценка (0–10)\n\n"
            "Критерии рекомендации:\n"
            "- strong_yes: 8.5–10\n"
            "- yes: 7.0–8.4\n"
            "- maybe: 5.5–6.9\n"
            "- no: ниже 5.5\n\n"
            "Основывай оценку только на ответах кандидата. Будь объективным и конкретным."
        )

        transcript_lines = []
        for msg in message_history:
            if msg["role"] == "assistant":
                transcript_lines.append(f"Интервьюер: {msg['content']}")
            elif msg["role"] == "candidate":
                transcript_lines.append(f"Кандидат: {msg['content']}")
        transcript = "\n\n".join(transcript_lines)

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
    ) -> AssessmentResult:
        candidate_msgs = [m for m in message_history if m["role"] == "candidate"]
        response_count = len(candidate_msgs)
        base = min(4.5 + response_count * 0.45, 8.5)
        overall = round(base, 1)
        hard = round(max(base - 0.5, 0), 1)
        soft = round(min(base + 0.3, 10.0), 1)
        comm = round(max(base - 0.2, 0), 1)
        if overall >= 8.0:
            recommendation = "strong_yes"
        elif overall >= 6.5:
            recommendation = "yes"
        elif overall >= 5.0:
            recommendation = "maybe"
        else:
            recommendation = "no"
        role_label = target_role.replace("_", " ")
        return AssessmentResult(
            overall_score=overall,
            hard_skills_score=hard,
            soft_skills_score=soft,
            communication_score=comm,
            strengths=["Завершил полное структурированное собеседование"],
            weaknesses=["Ответы могут включать более конкретные метрики"],
            recommendations=["Используйте формат STAR для ответов"],
            hiring_recommendation=recommendation,
            interview_summary=(
                f"Кандидат прошёл собеседование из {response_count} вопросов на позицию {role_label}. "
                f"Общий балл: {overall}/10."
            ),
            model_version="mock-v1",
            full_report_json={"mock": True, "target_role": target_role},
        )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

if settings.GROQ_API_KEY:
    assessor = LLMAssessor(client=AsyncGroq(api_key=settings.GROQ_API_KEY))
else:
    assessor = MockAssessor()  # type: ignore[assignment]
