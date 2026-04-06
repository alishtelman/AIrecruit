# AIRecruit

AIRecruit is a FastAPI + Next.js recruiting platform where candidates pass structured AI interviews and companies work with scored, replayable interview evidence.

## What Changed Recently (March 2026)

- Adaptive interview engine with per-topic follow-ups, claim verification, and depth escalation.
- Interview runtime state persisted in DB (`followup_depth`, `interview_state`) to avoid repeated generic questioning.
- Low-signal guardrails hardened: nonsense/noise answers are detected, interviews can end earlier on persistently weak signal, and generated questions are forced to stay short/single-question.
- Company hiring workspace expanded with shortlists, notes, activity log, analytics, and role-based collaboration.
- Candidate privacy model expanded (`private`, `marketplace`, `direct_link`, `request_only`) with access request approvals.
- Frontend internationalization added with `next-intl` (`en` + `ru`) and unified workspace UI refresh.
- Voice stack stabilized: Groq core AI, optional ElevenLabs TTS provider with backend fallback chain.

---

## Product Capabilities

### Candidate side

1. Register/login, upload resume, manage salary and privacy visibility.
2. Start AI interview (role + optional template + language).
3. Interview flow supports auto-start screen/camera/mic capture attempts, persistent camera self-preview, voice input, and TTS playback.
4. Receive structured report with competency scores, confidence, and skill tags.
5. Publish profile via marketplace/direct link or require explicit company approval.

### Company side

1. Browse/search candidates with filters and salary ranges.
2. Use shortlists, notes, and activity log for team hiring workflow.
3. Access report + interview replay within access scope/privacy rules.
4. Track outcomes and analytics (overview, funnel, salary).
5. Invite members with roles (`admin`, `recruiter`, `viewer`).
6. Run internal/external assessment campaigns.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, FastAPI, SQLAlchemy async, Alembic |
| Database | PostgreSQL 16 |
| Frontend | Next.js 14.2, TypeScript, Tailwind CSS |
| i18n | `next-intl` (`en`, `ru`) |
| AI | Groq (interviewer + assessor + STT), optional ElevenLabs for TTS |
| Auth | HttpOnly cookie sessions + backward-compatible Bearer handling |
| Infra | Docker Compose |

---

## Repository Structure

```text
backend/app/
  api/v1/            REST routers
  services/          business logic
  ai/                interviewer, assessor, calibration, resume profiling
  models/            SQLAlchemy models
  schemas/           Pydantic DTOs
  core/              config, DB, security

backend/alembic/versions/
  ...                DB migrations

frontend/src/
  app/               Next.js app routes
  components/        shared UI components
  hooks/             auth/media/voice hooks
  lib/               API client + shared TS types
  i18n/              routing/request/navigation adapters

frontend/messages/
  en.json
  ru.json
```

---

## Adaptive Interview Engine

Interview flow is no longer a flat “8 independent turns.”

- Core topic count is controlled by `question_count` (still max 8 by default).
- Extra probing turns are controlled by `interview_state` and `followup_depth`.
- Engine classifies each answer (`strong`, `partial`, `generic`, `evasive`, `no_experience_honest`).
- Additional noise guard detects repetitive/non-informative answers and pushes earlier session cutoff when weak signal persists.
- Depending on answer quality/relevance, next question type may be:
  - `main`
  - `followup`
  - `verification`
  - `claim_verification`
  - `deep_technical`
  - `edge_cases`
- Assessment consumes both transcript and interview runtime metadata (`interview_meta`) to produce stricter recommendations and confidence outputs.
- Interviewer output is normalized to one concise question to avoid long monologue-like prompts in chat UI.

---

## Key Database Notes

Main entities:

- `users`, `candidates`, `companies`, `company_members`
- `resumes`, `interviews`, `interview_messages`, `assessment_reports`
- `company_assessments`, `interview_templates`
- collaboration/marketplace entities (shortlists, notes, activities, access requests, outcomes)

Recent interview-state fields:

- `interviews.followup_depth` (int)
- `interviews.interview_state` (json)

Assessment report includes confidence + policy metadata (`overall_confidence`, `competency_confidence`, `decision_policy_version`, etc.).

---

## API Overview

Base URL: `/api/v1`
Interactive docs: `http://localhost:8001/docs`

### Auth

- `POST /auth/candidate/register`
- `POST /auth/company/register`
- `POST /auth/login`
- `POST /auth/logout`
- `GET /auth/me`
- `GET /auth/me/candidate`
- `POST /auth/change-password`

### Candidate profile / privacy

- `GET /candidate/stats`
- `GET /candidate/resume`
- `GET /candidate/resume/text`
- `POST /candidate/resume/upload`
- `GET /candidate/salary`
- `PATCH /candidate/salary`
- `GET /candidate/salary/benchmark`
- `GET /candidate/privacy`
- `PATCH /candidate/privacy`
- `GET /candidate/access-requests`
- `POST /candidate/access-requests/{request_id}/approve`
- `POST /candidate/access-requests/{request_id}/deny`
- `GET /candidate/share/{share_token}`

### Interview runtime

- `GET /interviews/`
- `GET /interviews/templates/public`
- `POST /interviews/start`
- `POST /interviews/{interview_id}/message`
- `POST /interviews/{interview_id}/signals`
- `POST /interviews/{interview_id}/recording`
- `POST /interviews/{interview_id}/finish`
- `GET /interviews/{interview_id}`

`SendMessageResponse` now includes:

- `is_followup: bool`
- `question_type: str`

### Reports

- `GET /reports/{report_id}` (candidate scope)

### Company workspace

- `GET /company/candidates`
- `GET /company/candidates/{candidate_id}`
- `POST /company/candidates/{candidate_id}/outcome`
- `GET /company/candidates/{candidate_id}/outcome`
- `GET /company/reports/{report_id}`
- `GET /company/interviews/{interview_id}/replay`

Shortlists:

- `GET /company/shortlists`
- `POST /company/shortlists`
- `DELETE /company/shortlists/{shortlist_id}`
- `POST /company/shortlists/{shortlist_id}/candidates/{candidate_id}`
- `DELETE /company/shortlists/{shortlist_id}/candidates/{candidate_id}`

Collaboration:

- `GET /company/candidates/{candidate_id}/notes`
- `POST /company/candidates/{candidate_id}/notes`
- `GET /company/candidates/{candidate_id}/activity`
- `GET /company/members`
- `POST /company/members/invite`
- `DELETE /company/members/{user_id}`

Analytics:

- `GET /company/analytics/overview`
- `GET /company/analytics/funnel`
- `GET /company/analytics/salary`

Templates and campaigns:

- `GET /company/templates`
- `POST /company/templates`
- `DELETE /company/templates/{template_id}`
- `GET /company/assessments`
- `POST /company/assessments`
- `DELETE /company/assessments/{assessment_id}`

Share-link access:

- `GET /company/share-links/{share_token}`
- `POST /company/share-links/{share_token}/request-access`

### Employee invite flow

- `GET /employee/invite/{token}`
- `POST /employee/invite/{token}/start`

### Voice APIs

- `POST /tts` (provider-based TTS)
- `POST /stt` (Groq Whisper STT)

---

## Security Baseline

- Cookie-first auth (`HttpOnly`, `SameSite`) for frontend transport; backend still keeps Bearer compatibility for API/tests.
- Production guard: insecure `SECRET_KEY` fails startup outside local/test.
- Company-scoped private report/replay access.
- Candidate privacy/access approval enforcement.
- Recording upload MIME + size restrictions.
- Safe path-only redirects on candidate auth pages.
- CORS allowlist via `CORS_ORIGINS`.

See also:

- [`SECURITY.md`](SECURITY.md)
- [`security_best_practices_report.md`](security_best_practices_report.md)

---

## Environment Variables

Use `.env.example` as baseline.

Core:

- `APP_ENV` (`development` / `test` / `production`)
- `DATABASE_URL`
- `SECRET_KEY`
- `CORS_ORIGINS`
- `APP_URL`

Auth/session:

- `SESSION_COOKIE_NAME`
- `SESSION_COOKIE_SAMESITE`
- `SESSION_COOKIE_SECURE`
- `ACCESS_TOKEN_EXPIRE_MINUTES`

AI:

- `GROQ_API_KEY`
- `ALLOW_MOCK_AI` (dev/test fallback behavior)
- `TTS_PROVIDER` (`groq` or `elevenlabs`)
- `TTS_FALLBACK_PROVIDER`
- `ELEVENLABS_API_KEY`
- `ELEVENLABS_VOICE_ID`
- `ELEVENLABS_TTS_MODEL`
- `RESEND_API_KEY`
- `FROM_EMAIL`

Report pipeline:

- `REPORT_SYNC_GENERATION_TIMEOUT_SECONDS`
- `REPORT_ASSESSMENT_TIMEOUT_SECONDS`
- `REPORT_MAX_AUTO_RETRIES`
- `REPORT_RETRY_BASE_BACKOFF_SECONDS`
- `REPORT_RETRY_MAX_BACKOFF_SECONDS`
- `REPORT_LOCK_STALE_SECONDS`

Storage:

- `RESUME_STORAGE_DIR`
- `RECORDING_STORAGE_DIR`
- `MAX_RESUME_SIZE_MB`
- `MAX_RECORDING_SIZE_MB`

Frontend:

- `NEXT_PUBLIC_API_URL`

---

## Local Development

```bash
cp .env.example .env
docker compose up -d --build
docker compose exec backend alembic upgrade head
```

Useful checks:

```bash
docker compose ps
docker compose logs backend -f
docker compose logs frontend -f
docker compose exec frontend npm run lint
docker compose exec frontend npm run build
cd backend && python3 -m pytest -v
```

CI gates (`.github/workflows/ci.yml`) run on push/PR:

- frontend lint + build
- backend migration + compile + targeted suite
- dependency scan (`npm audit --audit-level=high`, `pip-audit`)
- Python dependency baseline allowlist is tracked in `backend/pip_audit_baseline.txt`

---

## Notes

- Frontend uses localized copy from `frontend/messages/en.json` and `frontend/messages/ru.json`.
- Locale is cookie-driven (`NEXT_LOCALE`) with middleware routing and no locale path prefix.
- For production, disable mock AI mode and run only with real provider keys.
