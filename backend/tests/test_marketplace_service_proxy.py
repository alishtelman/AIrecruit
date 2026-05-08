import uuid
from datetime import datetime

import httpx
import pytest

from app.schemas.company import CandidateListItemResponse
from app.services import company_service


def _candidate_payload(candidate_id: uuid.UUID, report_id: uuid.UUID) -> dict:
    return {
        "candidate_id": str(candidate_id),
        "full_name": "Go Candidate",
        "email": "candidate@example.com",
        "target_role": "backend_engineer",
        "overall_score": 8.5,
        "hiring_recommendation": "yes",
        "interview_summary": "Strong Go candidate",
        "report_id": str(report_id),
        "completed_at": datetime.utcnow().isoformat(),
        "salary_min": None,
        "salary_max": None,
        "salary_currency": "USD",
        "hire_outcome": None,
        "skill_tags": [{"skill": "Go", "proficiency": "advanced"}],
        "shortlists": [],
        "cheat_risk_score": None,
        "red_flag_count": 0,
    }


@pytest.mark.asyncio
async def test_list_verified_candidates_uses_marketplace_service(monkeypatch):
    candidate_id = uuid.uuid4()
    report_id = uuid.uuid4()
    company_id = uuid.uuid4()
    captured = {}

    class _FakeResponse:
        is_success = True
        status_code = 200

        def json(self):
            return [_candidate_payload(candidate_id, report_id)]

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            captured["base_url"] = kwargs.get("base_url")
            captured["timeout"] = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, path, *, json):  # noqa: A002, ANN001
            captured["path"] = path
            captured["payload"] = json
            return _FakeResponse()

    async def _unexpected_python_snapshot(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("Python marketplace snapshot should not be used")

    monkeypatch.setattr("app.services.company_service.settings.MARKETPLACE_SERVICE_URL", "http://marketplace-service:8080")
    monkeypatch.setattr("app.services.company_service.httpx.AsyncClient", _FakeClient)
    monkeypatch.setattr("app.services.company_service._load_marketplace_snapshot", _unexpected_python_snapshot)

    result = await company_service.list_verified_candidates(
        None,  # type: ignore[arg-type]
        company_id=company_id,
        q="Go Candidate",
        skills=["go"],
        sort="latest",
    )

    assert len(result) == 1
    assert result[0].candidate_id == candidate_id
    assert result[0].report_id == report_id
    assert captured["base_url"] == "http://marketplace-service:8080"
    assert captured["timeout"] == 10.0
    assert captured["path"] == "/v1/company-candidates/search"
    assert captured["payload"]["company_id"] == str(company_id)
    assert captured["payload"]["q"] == "Go Candidate"
    assert captured["payload"]["skills"] == ["go"]
    assert captured["payload"]["sort"] == "latest"


@pytest.mark.asyncio
async def test_list_verified_candidates_falls_back_when_marketplace_service_unavailable(monkeypatch):
    candidate_id = uuid.uuid4()
    report_id = uuid.uuid4()

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, path, *, json):  # noqa: A002, ANN001
            raise httpx.ConnectError("unavailable")

    async def _fake_python_snapshot(*args, **kwargs):  # noqa: ANN002, ANN003
        return [CandidateListItemResponse.model_validate(_candidate_payload(candidate_id, report_id))]

    monkeypatch.setattr("app.services.company_service.settings.MARKETPLACE_SERVICE_URL", "http://marketplace-service:8080")
    monkeypatch.setattr("app.services.company_service.httpx.AsyncClient", _FakeClient)
    monkeypatch.setattr("app.services.company_service._load_marketplace_snapshot", _fake_python_snapshot)

    result = await company_service.list_verified_candidates(
        None,  # type: ignore[arg-type]
        company_id=uuid.uuid4(),
    )

    assert len(result) == 1
    assert result[0].candidate_id == candidate_id
