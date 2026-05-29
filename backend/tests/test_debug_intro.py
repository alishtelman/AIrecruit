"""Debug: trace intro phase progression with internal state."""
import asyncio
import io
import pytest
from httpx import AsyncClient
from tests.conftest import auth_headers


@pytest.mark.asyncio
async def test_debug_intro_phase(client: AsyncClient, candidate_token: str):
    pdf = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"
    await client.post(
        "/api/v1/candidate/resume/upload",
        headers=auth_headers(candidate_token),
        files={"file": ("r.pdf", io.BytesIO(pdf), "application/pdf")},
    )
    s = await client.post(
        "/api/v1/interviews/start",
        headers=auth_headers(candidate_token),
        json={"target_role": "backend_engineer", "language": "ru"},
    )
    assert s.status_code == 201
    data = s.json()
    iid = data["interview_id"]
    print(f"\nSTART: q={data['question_count']} phase={data['interview_stage']['phase_key']}")

    msg = (
        "Я backend-инженер с 7 годами опыта в highload-системах. "
        "Проектировал REST и gRPC API, оптимизировал PostgreSQL (EXPLAIN ANALYZE, индексы), "
        "руководил миграцией монолита на event-driven архитектуру с Kafka, "
        "вёл post-mortem инцидентов в production-среде."
    )
    for i in range(8):
        r = await client.post(
            f"/api/v1/interviews/{iid}/message",
            headers=auth_headers(candidate_token),
            json={"message": msg},
        )
        assert r.status_code == 200, r.text
        rd = r.json()
        # Try to get internal state
        state_resp = await client.get(
            f"/api/v1/interviews/{iid}/state",
            headers=auth_headers(candidate_token),
        )
        v2 = {}
        if state_resp.status_code == 200:
            raw = state_resp.json()
            v2 = raw.get("interview_state_v2") or raw.get("state_v2") or {}
        attempts = v2.get("attempts_on_current_step", "?")
        scored = v2.get("resume_scored_turns", "?")
        phase_v2 = v2.get("phase", "?")
        print(
            f"T{i+1}: q={rd['question_count']} followup={rd['is_followup']} "
            f"type={rd['question_type']} phase={rd['interview_stage']['phase_key']} "
            f"| v2.phase={phase_v2} v2.attempts={attempts} v2.scored={scored}"
        )
        if rd["question_count"] >= 2:
            print("ADVANCED PAST INTRO!")
            break
    else:
        print("NEVER ADVANCED — checking hard followup cap bypass")
