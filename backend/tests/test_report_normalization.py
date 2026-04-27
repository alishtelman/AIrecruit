import uuid
from datetime import datetime

from app.schemas.report import AssessmentReportResponse


def test_report_response_dedupes_repeated_lists():
    payload = {
        "id": uuid.uuid4(),
        "interview_id": uuid.uuid4(),
        "candidate_id": uuid.uuid4(),
        "overall_score": 7.0,
        "hard_skills_score": 7.0,
        "soft_skills_score": 6.0,
        "communication_score": 6.0,
        "problem_solving_score": 7.0,
        "strengths": ["Clear examples", " clear   examples ", "Systems thinking"],
        "weaknesses": ["Needs metrics", "needs metrics"],
        "recommendations": ["Add STAR examples", "Add STAR examples"],
        "hiring_recommendation": "yes",
        "interview_summary": None,
        "model_version": "mock",
        "created_at": datetime.utcnow(),
        "red_flags": [
            {"flag": "generic answer", "evidence": "same", "severity": "medium"},
            {"flag": " Generic answer ", "evidence": "same again", "severity": "medium"},
        ],
        "skill_tags": [
            {"skill": "Python", "proficiency": "intermediate", "mentions_count": 2},
            {"skill": " python ", "proficiency": "advanced", "mentions_count": 1},
            {"skill": "SQL", "proficiency": "intermediate", "mentions_count": 1},
        ],
    }

    report = AssessmentReportResponse.model_validate(payload)

    assert report.strengths == ["Clear examples", "Systems thinking"]
    assert report.weaknesses == ["Needs metrics"]
    assert report.recommendations == ["Add STAR examples"]
    assert [flag.flag for flag in report.red_flags or []] == ["generic answer"]
    assert [tag.skill for tag in report.skill_tags or []] == ["Python", "SQL"]
