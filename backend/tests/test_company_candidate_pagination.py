import uuid
from datetime import datetime

import pytest

from app.schemas.company import CandidateListItemResponse
from app.services import company_service


def _candidate(name: str, score: float) -> CandidateListItemResponse:
    return CandidateListItemResponse(
        candidate_id=uuid.uuid4(),
        full_name=name,
        email=f"{name.lower()}@example.com",
        target_role="backend_engineer",
        overall_score=score,
        hiring_recommendation="yes",
        interview_summary="Strong candidate",
        report_id=uuid.uuid4(),
        completed_at=datetime.utcnow(),
    )


@pytest.mark.asyncio
async def test_list_verified_candidates_page_slices_results(monkeypatch: pytest.MonkeyPatch):
    candidates = [_candidate("Alice", 9.1), _candidate("Bob", 8.2), _candidate("Cara", 7.3)]

    async def fake_list_verified_candidates(*args, **kwargs):
        return candidates

    monkeypatch.setattr(company_service, "list_verified_candidates", fake_list_verified_candidates)

    result = await company_service.list_verified_candidates_page(
        db=None,
        company_id=uuid.uuid4(),
        page=2,
        page_size=2,
    )

    assert result.total == 3
    assert result.page == 2
    assert result.page_size == 2
    assert result.total_pages == 2
    assert [item.full_name for item in result.items] == ["Cara"]


@pytest.mark.asyncio
async def test_list_verified_candidates_page_clamps_past_last_page(monkeypatch: pytest.MonkeyPatch):
    candidates = [_candidate("Alice", 9.1)]

    async def fake_list_verified_candidates(*args, **kwargs):
        return candidates

    monkeypatch.setattr(company_service, "list_verified_candidates", fake_list_verified_candidates)

    result = await company_service.list_verified_candidates_page(
        db=None,
        company_id=uuid.uuid4(),
        page=99,
        page_size=10,
    )

    assert result.total == 1
    assert result.page == 1
    assert result.total_pages == 1
    assert [item.full_name for item in result.items] == ["Alice"]
