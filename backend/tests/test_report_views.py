import uuid
from datetime import datetime
from types import SimpleNamespace

from app.schemas.report import build_report_view


def _report():
    return SimpleNamespace(
        id=uuid.uuid4(),
        interview_id=uuid.uuid4(),
        candidate_id=uuid.uuid4(),
        overall_score=6.4,
        hard_skills_score=5.8,
        soft_skills_score=7.0,
        communication_score=6.7,
        problem_solving_score=6.1,
        strengths=["У тебя хорошо получилось описать коммуникацию с бизнесом."],
        weaknesses=["Стоит подтянуть самостоятельную frontend-разработку на React."],
        recommendations=["Собрать маленький React-проект и объяснить state management."],
        hiring_recommendation="maybe",
        interview_summary="Текущий опыт ближе к сопровождению и диагностике инцидентов, чем к самостоятельной frontend-разработке.",
        model_version="test-model",
        created_at=datetime.utcnow(),
        competency_scores=[
            {
                "competency": "Frontend Development",
                "category": "technical_core",
                "score": 5.5,
                "weight": 0.5,
                "evidence": "Candidate could not provide a concrete React implementation example.",
                "reasoning": "Mentioned tools but lacked hands-on evidence.",
            }
        ],
        per_question_analysis=[
            {
                "question_number": 1,
                "targeted_competencies": ["Frontend Development"],
                "answer_quality": 5.0,
                "evidence": "React was mentioned without implementation evidence.",
                "skills_mentioned": [{"skill": "react", "proficiency": "beginner"}],
                "red_flags": ["unverified_claim"],
                "specificity": "low",
                "depth": "surface",
                "ai_likelihood": 0.2,
            }
        ],
        skill_tags=[
            {"skill": "incident diagnostics", "proficiency": "intermediate", "mentions_count": 1, "status": "confirmed", "evidence": "Described diagnosing incidents with metrics."},
            {"skill": "react", "proficiency": "beginner", "mentions_count": 1, "status": "mentioned", "evidence": None},
        ],
        red_flags=[{"flag": "unverified_claim", "evidence": "React mentioned without evidence.", "severity": "medium"}],
        response_consistency=0.7,
        overall_confidence=0.62,
        competency_confidence={"Frontend Development": 0.55},
        confidence_reasons=["limited direct evidence"],
        evidence_coverage={"strong_answers_count": 1},
        decision_policy_version="policy-v1",
        cheat_risk_score=0.3,
        cheat_flags=["ai_generation_probability_medium"],
        full_report_json={
            "signal_reliability": {"level": "medium", "basis": "voice_transcript_quality"},
            "voice_section": {"signal_reliability": {"level": "medium"}},
            "explainability_report": {"debug": True},
            "role_mismatch": {
                "detected": True,
                "mismatch_type": "support_incident_vs_frontend",
                "notes": ["Candidate evidence fits support/incident diagnostics more than frontend development."],
            },
        },
    )


def test_candidate_report_hides_internal_debug_blocks():
    report = build_report_view(_report(), "candidate")
    payload = report.model_dump()

    assert payload["report_view"] == "candidate"
    assert payload["candidate_report"]["headline"]
    assert payload["red_flags"] is None
    assert payload["per_question_analysis"] is None
    assert payload["overall_confidence"] is None
    assert payload["internal_debug_report"] is None
    assert "AI-generation probability" not in str(payload["candidate_report"])


def test_company_report_contains_risk_and_evidence():
    report = build_report_view(_report(), "company")

    assert report.report_view == "company"
    assert report.company_report is not None
    assert report.company_report.key_risks
    assert report.company_report.evidence_items
    assert report.company_report.role_mismatch_notes
    assert report.company_report.per_question_analysis
    assert report.internal_debug_report is None


def test_candidate_report_softens_role_mismatch_language():
    report = build_report_view(_report(), "candidate")

    assert report.candidate_report is not None
    assert "ближе к сопровождению" in str(report.candidate_report.human_summary)
    assert "support_incident_vs_frontend" not in str(report.model_dump())


def test_internal_report_contains_reliability_and_debug():
    report = build_report_view(_report(), "internal")

    assert report.report_view == "internal"
    assert report.internal_debug_report is not None
    assert report.internal_debug_report.signal_reliability == {"level": "medium", "basis": "voice_transcript_quality"}
    assert report.internal_debug_report.ai_generation_probability == 0.2
    assert report.internal_debug_report.raw_flags
    assert report.internal_debug_report.confidence["overall_confidence"] is not None
    assert report.internal_debug_report.confidence["confidence_reasons"]
