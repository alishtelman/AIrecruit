import os
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.resume import Resume
from app.models.interview import Interview
from app.models.report import AssessmentReport
from tests.conftest import auth_headers

@pytest.mark.asyncio
async def test_go_candidate_resume_endpoints(
    client: AsyncClient,
    candidate_token: str,
):
    # 1. Test GET /stats before anything
    stats_resp = await client.get("/api/v1/candidate/stats", headers=auth_headers(candidate_token))
    assert stats_resp.status_code == 200, stats_resp.text
    stats = stats_resp.json()
    assert stats["has_resume"] is False
    assert stats["interview_count"] == 0

    # 2. Test GET /resume text (should be 404)
    text_resp = await client.get("/api/v1/candidate/resume/text", headers=auth_headers(candidate_token))
    assert text_resp.status_code == 404

    # 3. Create dummy resume PDF with parsable content
    resume_content = b"%PDF-1.4\n1 0 obj\n(Hello this is resume text)\nendobj\n"
    
    # 4. Upload resume
    upload_resp = await client.post(
        "/api/v1/candidate/resume/upload",
        headers=auth_headers(candidate_token),
        files={"file": ("test_resume.pdf", resume_content, "application/pdf")},
    )
    assert upload_resp.status_code == 200, upload_resp.text
    upload_data = upload_resp.json()
    assert upload_data["file_name"] == "test_resume.pdf"
    assert upload_data["is_active"] is True
    resume_id = upload_data["resume_id"]

    # 5. Get resume active
    get_resp = await client.get("/api/v1/candidate/resume", headers=auth_headers(candidate_token))
    assert get_resp.status_code == 200
    get_data = get_resp.json()
    assert get_data["resume_id"] == resume_id
    assert get_data["file_name"] == "test_resume.pdf"

    # 6. Get stats after upload
    stats_after_resp = await client.get("/api/v1/candidate/stats", headers=auth_headers(candidate_token))
    assert stats_after_resp.status_code == 200
    assert stats_after_resp.json()["has_resume"] is True

    # 7. Get resume text
    text_after_resp = await client.get("/api/v1/candidate/resume/text", headers=auth_headers(candidate_token))
    assert text_after_resp.status_code == 200
    text_data = text_after_resp.json()
    assert text_data["resume_id"] == resume_id
    assert text_data["file_name"] == "test_resume.pdf"
    assert "Hello this is resume text" in text_data["raw_text"]
