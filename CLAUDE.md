# CLAUDE.md

This file provides guidance to Claude Code when working in this repository.

## Stack

- Backend: Python 3.11, FastAPI, SQLAlchemy 2.0 async, Alembic, PostgreSQL 16
- Frontend: Next.js 14.2, TypeScript, Tailwind CSS, next-intl
- Infra: Docker Compose

## Daily Commands

Run from repo root unless noted.

```bash
# Start services
docker compose up -d --build

# Status / logs
docker compose ps
docker compose logs backend -f
docker compose logs frontend -f

# DB migrations
docker compose exec backend alembic upgrade head
docker compose exec backend alembic revision --autogenerate -m "description"

# Frontend checks
docker compose exec frontend npm run lint
docker compose exec frontend npm run build
```

## Tests

Backend tests (run against live backend with docker compose up):

```bash
cd backend && python3 -m pytest -v
cd backend && python3 -m pytest tests/test_interview_flow.py -v
```

Current main backend suites:

- `test_auth.py`
- `test_interview_flow.py`
- `test_templates.py`
- `test_candidate_privacy.py`
- `test_company_collaboration_roles.py`
- `test_company_search_shortlists.py`
- `test_employee_assessments.py`
- `test_ai_quality_controls.py`
- `test_tts.py`

## Interview Engine Notes

The interview flow is stateful and adaptive.

- `interviews.question_count` tracks core topic progression.
- `interviews.followup_depth` and `interviews.interview_state` track probing behavior.
- `SendMessageResponse` includes `is_followup` and `question_type`.
- `question_type` can be `main`, `followup`, `verification`, `claim_verification`, `deep_technical`, `edge_cases`.

Key files:

- `backend/app/services/interview_service.py`
- `backend/app/ai/interviewer.py`
- `backend/app/ai/resume_profile.py`
- `backend/app/ai/competencies.py`
- `backend/app/ai/assessor.py`
- `backend/app/ai/calibration.py`

## Frontend Notes

- API calls must go through `frontend/src/lib/api.ts`.
- Shared interfaces live in `frontend/src/lib/types.ts`.
- Localization uses `next-intl`:
  - `frontend/messages/en.json`
  - `frontend/messages/ru.json`
  - `frontend/src/i18n/*`
- Locale is cookie-driven (`NEXT_LOCALE`) without locale URL prefix.

## Security Notes

- Auth is cookie-first (`HttpOnly`) with temporary Bearer compatibility.
- In non-local environments, insecure/default `SECRET_KEY` causes startup failure.
- Keep `ALLOW_MOCK_AI=false` in production.
- Recording uploads are MIME + size constrained.

## Code Rules

FastAPI:

- routers are thin; business logic in services
- raise domain errors in services, map to HTTP in routers

SQLAlchemy async:

- always async session patterns (`await session.execute`, etc.)
- do not mix sync and async DB usage

Alembic:

- generate migrations from container environment
- run `upgrade head` before testing schema-related changes

Next.js:

- do not bypass shared API client layer
- keep TS types in `lib/types.ts`

## Core Principles

- Make the smallest safe change.
- Preserve current architecture and compatibility unless explicitly changing contracts.
- Avoid unrelated refactors.
- Avoid touching secrets and generated artifacts unless required.
