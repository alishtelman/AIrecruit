"""Tests for the Go-migrated behavioral signals and recording upload endpoints."""
import io
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.interview import Interview
from tests.conftest import auth_headers
from tests.test_employee_assessments import (
    _register_candidate,
    _register_company,
    _create_assessment,
    _upload_resume,
)


@pytest.mark.asyncio
async def test_go_proctoring_endpoints(client: AsyncClient):
    # 1. SETUP
    company_token = await _register_company(client, "Go Proctor Corp")
    employee_email = f"goproctor_{uuid.uuid4().hex[:8]}@example.com"
    
    assessment = await _create_assessment(client, company_token, employee_email, "Go Proctor Candidate")
    candidate_token = await _register_candidate(client, employee_email, "Go Proctor Candidate")
    await _upload_resume(client, candidate_token)

    start_resp = await client.post(
        f"/api/v1/employee/invite/{assessment['invite_token']}/start",
        headers=auth_headers(candidate_token),
        json={"language": "en"},
    )
    assert start_resp.status_code == 200, start_resp.text
    interview_id = start_resp.json()["interview_id"]

    # 2. TEST SIGNALS ENDPOINT
    signals_resp = await client.post(
        f"/api/v1/interviews/{interview_id}/signals",
        headers=auth_headers(candidate_token),
        json={
            "paste_count": 3,
            "tab_switches": 2,
            "face_away_pct": 0.35,
            "policy_mode": "strict_flagging",
            "events": [
                {
                    "event_type": "camera_stream_lost",
                    "severity": "info",
                    "occurred_at": "2026-05-17T15:43:00Z",
                    "source": "client",
                }
            ]
        },
    )
    assert signals_resp.status_code == 204

    # Verify signals are persisted and normalized correctly in the database
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Interview).where(Interview.id == uuid.UUID(interview_id)))
        interview = result.scalar_one()
        assert interview.behavioral_signals is not None
        signals_data = interview.behavioral_signals
        assert signals_data["paste_count"] == 3
        assert signals_data["tab_switches"] == 2
        assert signals_data["face_away_pct"] == 0.35
        assert signals_data["policy_mode"] == "strict_flagging"
        
        events = signals_data["events"]
        assert len(events) >= 3
        
        lost_event = next(e for e in events if e["event_type"] == "camera_stream_lost")
        assert lost_event["severity"] == "high"

    # 3. TEST RECORDING ENDPOINT
    fake_video = b"MOCK-WEBM-DATA"
    upload_resp = await client.post(
        f"/api/v1/interviews/{interview_id}/recording",
        headers=auth_headers(candidate_token),
        files={"file": ("recording.webm", io.BytesIO(fake_video), "video/webm")},
    )
    assert upload_resp.status_code == 204

    # Verify that recording_path is updated in the database
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Interview).where(Interview.id == uuid.UUID(interview_id)))
        interview = result.scalar_one()
        assert interview.recording_path is not None
        assert "recording.webm" in interview.recording_path or interview_id in interview.recording_path
