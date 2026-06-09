import pytest
import uuid
from datetime import datetime
from sqlalchemy import select

from app.models.user import User
from app.models.candidate import Candidate
from app.models.interview import Interview, InterviewMessage
from app.services.interview_service import add_candidate_message
from app.ai.providers.base import ProviderChatError
from app.core.config import settings

# Reuse db_session fixture from test_company_search_shortlists.py
from tests.test_company_search_shortlists import db_session

@pytest.mark.asyncio
async def test_openai_failure_propagates_and_records_error_trace(db_session, monkeypatch):
    # 1. Seed candidate and interview
    marker = uuid.uuid4().hex[:8]
    user = User(
        id=uuid.uuid4(),
        email=f"candidate_{marker}@example.com",
        hashed_password="unused",
        role="candidate",
    )
    candidate = Candidate(
        id=uuid.uuid4(),
        user_id=user.id,
        full_name="OpenAI Test Candidate",
    )
    interview = Interview(
        id=uuid.uuid4(),
        candidate_id=candidate.id,
        status="in_progress",
        target_role="qa_engineer",
        max_questions=5,
        question_count=1,
        interview_state={
            "turn_count": 1,
            "asked_question_texts": ["Кейс: деньги списались, но статус ошибки. Что проверите первым?"],
            "asked_topics": ["Bug Investigation"],
            "interview_state_v2": {
                "phase": "technical_case",
                "role": "qa_engineer",
                "language": "ru",
                "fallback_counter": 0,
                "decision_traces": [],
            }
        }
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(candidate)
    await db_session.flush()
    db_session.add(interview)
    await db_session.flush()
    # Add initial assistant message to match the start of the interview
    db_session.add(InterviewMessage(
        id=uuid.uuid4(),
        interview_id=interview.id,
        role="assistant",
        content="Кейс: деньги списались, но статус ошибки. Что проверите первым?",
    ))
    await db_session.commit()

    # 2. Mock strategist call to simulate OpenAI failure
    async def mock_decide_action(*args, **kwargs):
        raise ProviderChatError("OpenAI API key expired or timeout", code="openai_error")

    monkeypatch.setattr("app.services.interview_service.decide_next_interview_action", mock_decide_action)

    # 3. Call add_candidate_message and expect RuntimeError
    with pytest.raises(RuntimeError) as exc_info:
        await add_candidate_message(
            db_session,
            candidate,
            interview.id,
            "Я проверю логи платежного шлюза."
        )

    # Verify error message contains OpenAI failure details
    assert "AI generation failed" in str(exc_info.value)
    assert "OpenAI API key expired" in str(exc_info.value)

    # 4. Reload interview state from DB
    await db_session.close() # Close to clean session cache
    
    # Create fresh session to query DB
    async with db_session as session:
        reloaded_interview = await session.scalar(
            select(Interview).where(Interview.id == interview.id)
        )
        
        # Verify that candidate message was persisted
        messages = (await session.scalars(
            select(InterviewMessage)
            .where(InterviewMessage.interview_id == interview.id)
            .order_by(InterviewMessage.created_at.asc())
        )).all()
        
        assert len(messages) == 2
        assert messages[0].role == "assistant"
        assert messages[1].role == "candidate"
        assert messages[1].content == "Я проверю логи платежного шлюза."

        # Verify trace has source="error" and provider="openai"
        state = reloaded_interview.interview_state or {}
        state_v2 = state.get("interview_state_v2") or {}
        traces = state_v2.get("decision_traces") or []
        
        assert len(traces) == 1
        trace = traces[0]
        assert trace["source"] == "error"
        assert trace["final_question_source"] == "error"
        assert trace["provider"] == "openai"
        assert trace["ai_provider"] == "openai"
        assert "OpenAI API key expired" in trace["error"]
        assert trace["actual_model_used"] == "gpt-5.4-mini"
        assert state_v2.get("fallback_counter") == 1
