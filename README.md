# AIRecruit

AIRecruit is a FastAPI + Next.js recruiting platform where candidates pass structured AI interviews and companies work with scored, replayable interview evidence.

## What Changed Recently (March-April 2026)

- Adaptive interview engine with per-topic follow-ups, claim verification, and depth escalation.
- Interview runtime state persisted in DB (`followup_depth`, `interview_state`) to avoid repeated generic questioning.
- Low-signal guardrails hardened: nonsense/noise answers are detected, interviews can end earlier on persistently weak signal, and generated questions are forced to stay short/single-question.
- Company hiring workspace expanded with shortlists, notes, activity log, analytics, and role-based collaboration.
- Candidate privacy model expanded (`private`, `marketplace`, `direct_link`, `request_only`) with access request approvals.
- Frontend internationalization added with `next-intl` (`en` + `ru`) and unified workspace UI refresh.
- Voice stack stabilized: Groq core AI, optional ElevenLabs TTS provider with backend fallback chain.
- Company assessment campaigns now support ordered `module_plan` flows with adaptive interview plus staged `system_design`, `coding_task`, and `sql_live` modules.
- Invite landing pages now expose branding, current-module preview metadata, and resume/start or resume-in-progress behavior for internal and external campaigns.
- Role-aware task profiles now drive coding task and SQL live modules via scenario title, stack focus, preferred language, and workspace hints.
- Coding task and SQL live runtimes persist draft workspace artifacts and feed module-aware summaries into the final report payload.
- Company settings now expose AI workspace controls for proctoring policy plus interviewer and assessor model preferences.
- Company report view can now surface proctoring timeline evidence alongside replayable interview content.
- A separate platform admin workspace landed on `origin/main`; verified notes, routes, and bootstrap details live in [`docs/platform-admin.md`](docs/platform-admin.md).

---

## Product Capabilities

### Candidate side

1. Register/login, upload resume, manage salary and privacy visibility.
2. Start direct AI interviews or resume company invite flows for internal/external assessment campaigns.
3. Interview flow supports auto-start screen/camera/mic capture attempts, persistent camera self-preview, voice input, and TTS playback.
4. Complete adaptive interview plus staged module flows such as system design, coding task, and SQL live.
5. Use saved task workspaces for coding and SQL modules while keeping reasoning and trade-offs in the answer stream.
6. Receive structured reports with competency scores, confidence metadata, skill tags, and module-specific summaries.
7. Publish profile via marketplace/direct link or require explicit company approval.

### Company side

1. Browse/search candidates with filters and salary ranges.
2. Use shortlists, notes, and activity log for team hiring workflow.
3. Access report + interview replay within access scope/privacy rules.
4. Track outcomes and analytics (overview, funnel, salary).
5. Invite members with roles (`admin`, `recruiter`, `viewer`).
6. Run internal/external assessment campaigns with branding, deadlines, expiry, and ordered module plans.
7. Attach role-aware coding task / SQL live task profiles and preview them before sending invite links.
8. Review proctoring timeline evidence and manage workspace-level AI runtime preferences.

### Platform admin side

Verified on `origin/main` in [`docs/platform-admin.md`](docs/platform-admin.md):

1. Sign in as `platform_admin` through `/admin/login`.
2. Open `/admin/dashboard` for platform-wide metrics across users, companies, interviews, and reports.
3. Inspect runtime flags such as environment, mock-AI mode, rate limiting, and platform-admin bootstrap status.
4. Review recent users, companies, interviews, and reports from a single cross-company workspace.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, FastAPI, SQLAlchemy async, Alembic |
| Media service | Go sidecar for STT/TTS provider calls |
| Resume service | Go sidecar for resume upload validation, storage, and text extraction |
| Sandbox service | Go sidecar for coding-task runner orchestration |
| Report worker | Go worker for report-generation polling/orchestration |
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

services/media/
  cmd/media-service/ Go STT/TTS provider sidecar

services/resume/
  cmd/resume-service/ Go resume upload/storage sidecar

services/report-worker/
  cmd/report-worker/ Go report generation worker loop

services/sandbox/
  cmd/sandbox-service/ Go coding-task sandbox runner

frontend/src/
  app/               Next.js app routes
  components/        shared UI components
  hooks/             auth/media/voice hooks
  lib/               API client + shared TS types
  i18n/              routing/request/navigation adapters

frontend/messages/
  en.json
  ru.json

docs/
  admin-overview.md       verified contract for /admin/dashboard and /api/v1/admin/overview
  access-roles.md         role matrix across candidate, company, and platform scopes
  assessment-campaigns.md  modular assessment flow, task profiles, AI settings
  platform-admin.md        verified platform admin workspace note for origin/main
  platform-admin-operator-runbook.md safe local sync and smoke-check for platform admin
  runtime-config-matrix.md runtime flags across local/test vs production-like modes
  workspace-routes.md      frontend route families across candidate, company, invite, and admin
  prd/                     roadmap/backlog artifacts
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

## Modular Assessment Campaigns

Assessment campaigns now extend the interview engine into ordered, role-aware module plans.

- `company_assessments.module_plan` stores the ordered flow, while `current_module_index` tracks which module is active.
- The first module must currently be `adaptive_interview`; after that the runtime can continue with `system_design`, `coding_task`, or `sql_live`.
- `coding_task` and `sql_live` modules carry scenario metadata such as `scenario_id`, `scenario_title`, `stack_focus`, `preferred_language`, and `workspace_hint`.
- Candidate invite pages expose `current_module_preview`, `active_interview_id`, and `can_start_current_module` so the same link can start or resume a campaign safely.
- Candidate interview responses now expose `module_session`, and final report payloads can include `system_design_summary`, `coding_task_summary`, and `sql_live_summary`.
- Task modules persist draft workspace artifacts via dedicated interview endpoints, so the company-side report can include implementation/query evidence.

Detailed operational notes and example payloads live in [`docs/assessment-campaigns.md`](docs/assessment-campaigns.md).

---

## Key Database Notes

Main entities:

- `users`, `candidates`, `companies`, `company_members`
- `resumes`, `interviews`, `interview_messages`, `assessment_reports`
- `company_assessments`, `interview_templates`
- collaboration/marketplace entities (shortlists, notes, activities, access requests, outcomes)
- assessment module state via `company_assessments.module_plan` and `company_assessments.current_module_index`

Recent interview-state fields:

- `interviews.followup_depth` (int)
- `interviews.interview_state` (json)
- task-module workspace artifacts and module context are persisted inside `interviews.interview_state`

Assessment report includes confidence + policy metadata (`overall_confidence`, `competency_confidence`, `decision_policy_version`, etc.) and can now include `module_session`, `system_design_summary`, `coding_task_summary`, and `sql_live_summary`.

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
- `GET /interviews/{interview_id}/coding-artifact`
- `PUT /interviews/{interview_id}/coding-artifact`
- `POST /interviews/{interview_id}/finish`
- `GET /interviews/{interview_id}`
- `GET /interviews/{interview_id}/report-status`
- `POST /interviews/{interview_id}/report-retry`

`SendMessageResponse` now includes:

- `is_followup: bool`
- `question_type: str`
- `module_session: InterviewModuleSession | null`

`InterviewDetail`, `FinishInterviewResponse`, and `InterviewReportStatusResponse` also expose:

- `assessment_progress`
- `module_session`

### Reports

- `GET /reports/{report_id}` (candidate scope)

Candidate/company report payloads can also include:

- `module_session`
- `system_design_summary`
- `coding_task_summary`
- `sql_live_summary`

### Platform admin

Verified on `origin/main` in [`docs/platform-admin.md`](docs/platform-admin.md):

- `GET /admin/overview`

### Company workspace

- `GET /company/candidates`
- `GET /company/candidates/{candidate_id}`
- `POST /company/candidates/{candidate_id}/outcome`
- `GET /company/candidates/{candidate_id}/outcome`
- `GET /company/reports/{report_id}`
- `GET /company/reports/{report_id}/proctoring-timeline`
- `GET /company/interviews/{interview_id}/replay`
- `GET /company/settings/ai`
- `PUT /company/settings/ai`

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
- `GET /company/assessment-module-profiles`
- `POST /company/assessments`
- `DELETE /company/assessments/{assessment_id}`

`POST /company/assessments` accepts campaign metadata such as:

- `assessment_type`
- `module_plan`
- `deadline_at`
- `expires_at`
- `branding_name`
- `branding_logo_url`

Share-link access:

- `GET /company/share-links/{share_token}`
- `POST /company/share-links/{share_token}/request-access`

### Employee invite flow

- `GET /employee/invite/{token}`
- `POST /employee/invite/{token}/start`

Invite info now includes:

- `module_plan`
- `current_module_preview`
- `active_interview_id`
- `can_start_current_module`

### Voice APIs

- `POST /tts` (provider-based TTS)
- `POST /stt` (Groq Whisper STT)

---

## Security Baseline

- Cookie-first auth (`HttpOnly`, `SameSite`) for frontend transport; Bearer transport is toggleable via `AUTH_ALLOW_BEARER`.
- Production guards fail startup on insecure `SECRET_KEY`, insecure cookie config, or wildcard CORS/CSRF origins.
- Company-scoped private report/replay access.
- Candidate privacy/access approval enforcement.
- Recording upload MIME + size restrictions.
- Safe path-only redirects on candidate auth pages.
- CORS allowlist via `CORS_ORIGINS`.
- Cookie-auth write routes require trusted `Origin/Referer` (CSRF guard).
- Critical endpoint rate limiting (`/auth/login`, `/interviews/start`, `/interviews/{id}/message`, `/tts`, `/stt`) in non-local environments.
- Security audit logging for auth/CSRF/rate-limit denials.

See also:

- [`SECURITY.md`](SECURITY.md)
- [`security_best_practices_report.md`](security_best_practices_report.md)

---

## Environment Variables

Use `.env.example` as baseline.

For computed runtime behavior and local/test vs production-like differences, see [`docs/runtime-config-matrix.md`](docs/runtime-config-matrix.md).

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
- `AUTH_ALLOW_BEARER` (must be `false` outside local/test)
- `CSRF_TRUSTED_ORIGINS` (defaults to `CORS_ORIGINS` when empty)
- `ACCESS_TOKEN_EXPIRE_MINUTES`

Platform admin bootstrap:

- `PLATFORM_ADMIN_EMAIL`
- `PLATFORM_ADMIN_PASSWORD`
- `PLATFORM_ADMIN_BOOTSTRAP`

Rate limiting:

- `RATE_LIMIT_ENABLED` (enforced only outside local/test)
- `RATE_LIMIT_LOGIN_PER_MINUTE`
- `RATE_LIMIT_INTERVIEW_START_PER_MINUTE`
- `RATE_LIMIT_INTERVIEW_MESSAGE_PER_MINUTE`
- `RATE_LIMIT_TTS_PER_MINUTE`
- `RATE_LIMIT_STT_PER_MINUTE`

AI:

- `GROQ_API_KEY`
- `ALLOW_MOCK_AI` (dev/test fallback behavior)
- `TTS_PROVIDER` (`groq` or `elevenlabs`)
- `TTS_FALLBACK_PROVIDER`
- `MEDIA_SERVICE_URL` (optional Go media sidecar URL; compose sets this for backend)
- `RESUME_SERVICE_URL` (optional Go resume sidecar URL; compose sets this for backend)
- `SANDBOX_SERVICE_URL` (optional Go sandbox sidecar URL for coding-task and SQL live checks; compose sets this for backend)
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
- `REPORT_WORKER_MODE` (`embedded` or `external`)
- `INTERNAL_WORKER_TOKEN` (required when `REPORT_WORKER_MODE=external`)

The Go report worker is opt-in for local development to avoid accidentally processing old report backlog:

```bash
REPORT_WORKER_MODE=external docker compose --profile workers up -d report-worker
```

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

Platform admin note:

- after updating to `origin/main` at or after `20096ce`, the verified local/test bootstrap defaults are documented in [`docs/platform-admin.md`](docs/platform-admin.md)
- if the local app still shows `404` on `/admin/login`, check whether the checkout and containers are still behind `origin/main`; the practical runbook is in [`docs/platform-admin-operator-runbook.md`](docs/platform-admin-operator-runbook.md)

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
