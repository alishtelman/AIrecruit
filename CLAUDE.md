# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Stack
- Backend: Python 3.11, FastAPI, SQLAlchemy 2.0 async, Alembic, PostgreSQL 16 (asyncpg)
- Frontend: Next.js 14.2, TypeScript, Tailwind CSS
- Infrastructure: Docker Compose

## Daily commands
All run from repo root unless noted.

```bash
# Start
docker compose up --build

# Container status
docker compose ps

# Backend logs
docker compose logs backend -f

# Apply migrations
docker compose exec backend alembic upgrade head

# Create migration after model changes
docker compose exec backend alembic revision --autogenerate -m "description"

# Frontend lint
docker compose exec frontend npm run lint

# Frontend build
docker compose exec frontend npm run build
```

## Backend tests
Tests run against the live backend at `http://localhost:8001`. Requires `docker compose up`.

```bash
# Run all tests (from repo root)
cd backend && python3 -m pytest -v

# Run specific test file
cd backend && python3 -m pytest tests/test_auth.py -v
```

20 integration tests: auth (7), interview flow (7), templates (6).

## Assessment system

Scientific competency-based assessment. Two LLM passes per interview:
- **Pass 1** — per-question evidence extraction (answer quality, skills, red flags)
- **Pass 2** — competency scoring with weighted aggregation → 5 score dimensions

**5 score dimensions** (replacing old hard/soft/communication):
- `overall_score` — weighted sum of all competencies
- `hard_skills_score` — technical_core + technical_breadth
- `soft_skills_score` — behavioral
- `communication_score` — communication
- `problem_solving_score` — problem_solving (new)

**Key files:**
- `backend/app/ai/competencies.py` — role competency matrices (8 roles × 10 competencies, pure data)
- `backend/app/ai/assessor.py` — two-pass LLM assessment pipeline
- `backend/app/models/skill.py` — `candidate_skills` table (queryable skill index)

**New DB columns on `assessment_reports`** (all nullable, backward-compat):
`problem_solving_score`, `competency_scores` (JSON), `per_question_analysis` (JSON),
`skill_tags` (JSON), `red_flags` (JSON), `response_consistency` (Float)

**Adding a new role:** add entry to `ROLE_COMPETENCIES` dict in `ai/competencies.py`
and a mock question list in `ai/interviewer.py`.

## Structure

```
backend/app/
  api/v1/       — thin FastAPI routers (no DB logic)
  services/     — all business logic
  ai/           — Groq LLM interviewer (adaptive, resume-aware) + assessor
  models/       — SQLAlchemy ORM models
  schemas/      — Pydantic DTOs
  core/         — config, database setup, JWT/bcrypt

frontend/src/
  app/(candidate)/  — candidate pages
  app/(company)/    — company pages
  lib/api.ts        — HTTP client with Bearer middleware
  lib/types.ts      — TypeScript interfaces
  hooks/useAuth.ts  — auth state
```

Key files: `backend/app/services/interview_service.py` (state machine + competency planning), `backend/app/core/config.py`, `backend/app/api/v1/deps.py` (JWT dep), `backend/app/ai/competencies.py` (competency matrices).

## Code rules

**FastAPI**
- Routers delegate to services; no SQLAlchemy queries in routers.
- Raise domain exceptions in services; translate to HTTP responses in routers.

**SQLAlchemy async**
- Always use `async with session` / `await session.execute(...)`.
- Never mix sync and async session usage.

**Alembic**
- Always use `--autogenerate` from inside the container.
- Run `upgrade head` before testing any schema change.

**Next.js**
- API calls go through `frontend/src/lib/api.ts` only — never fetch directly.
- TypeScript interfaces live in `frontend/src/lib/types.ts`.

## Tool rules

**Serena** — use for codebase navigation: finding definitions, call paths, symbol search. Prefer over grep for code structure questions.

**Context7** — use only for external library/framework documentation. Do not use for reading project code.

**playwright-cli skill** — use for all UI flow checks and regression testing. Do not default to Playwright MCP.

## Core principles
- Make the smallest safe change that solves the task.
- Prefer existing project patterns over new abstractions.
- Do not rewrite unrelated code.
- Do not add dependencies unless clearly justified.
- Before editing, identify the smallest relevant set of files.
- Preserve backward compatibility unless the task explicitly allows breaking changes.
- Never read or print secrets. Avoid touching `.env`, lockfiles, and generated files unless required.
- Be concise. Reference exact files and commands when reporting changes.
