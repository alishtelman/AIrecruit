"""
AI Assessor module.

Current implementation: mock scoring based on interview engagement.
Phase 5 replacement: swap MockAssessor with LLMAssessor that calls Claude API
with the full interview transcript and returns a structured JSON report.
The public interface (assess + AssessmentResult) stays the same.
"""
from dataclasses import dataclass, field


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
    interview_summary: str | None  # short blurb for candidate marketplace card
    model_version: str
    full_report_json: dict


class MockAssessor:
    """
    Generates a deterministic mock report.
    Scoring is based only on how many answers the candidate gave (engagement proxy).

    TO REPLACE IN PHASE 5:
    - Build a system prompt with role-specific evaluation rubric
    - Pass the full interview transcript (all assistant + candidate messages)
    - Ask Claude to return a structured JSON matching AssessmentResult fields
    - Parse and validate the response with Pydantic
    """

    async def assess(
        self,
        target_role: str,
        message_history: list[dict],
    ) -> AssessmentResult:
        candidate_msgs = [m for m in message_history if m["role"] == "candidate"]
        response_count = len(candidate_msgs)

        # Simple mock: more responses → higher engagement → higher score
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
            strengths=[
                "Completed the full structured interview",
                "Demonstrated willingness to share relevant experience",
            ],
            weaknesses=[
                "Responses could include more specific metrics and outcomes",
                f"Consider preparing deeper examples for {role_label} domain questions",
            ],
            recommendations=[
                "Use the STAR format (Situation, Task, Action, Result) for all answers",
                f"Strengthen technical depth in core {role_label} competencies",
            ],
            hiring_recommendation=recommendation,
            interview_summary=(
                f"Candidate completed a {response_count}-question {role_label} interview. "
                f"Overall score: {overall}/10. Recommendation: {recommendation.replace('_', ' ')}."
            ),
            model_version="mock-v1",
            full_report_json={
                "mock": True,
                "target_role": target_role,
                "response_count": response_count,
                "note": "Replace with real LLM assessment in Phase 5",
            },
        )


# Module-level singleton — replace with LLMAssessor(client=anthropic_client) in Phase 5
assessor = MockAssessor()
