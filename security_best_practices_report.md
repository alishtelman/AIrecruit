# Security Review and Remediation Status

Review date: March 18, 2026

## Executive Summary

I reviewed the FastAPI backend, Next.js frontend, Docker runtime, and the employee assessment flow.

- 12 findings were identified during the audit.
- 10 findings are remediated in this branch.
- 2 findings remain open and should be prioritized next: JWT storage in `localStorage` and fail-fast protection for an insecure default `SECRET_KEY`.

## Remediated In This Branch

### F-01 Fixed: Employee assessment invite hijack

- Severity: Critical
- Location:
  - `backend/app/api/v1/employee.py`
  - `backend/app/services/assessment_invite_service.py`
- Remediation:
  - Employee assessment start now compares the authenticated candidate email with `assessment.employee_email`.
  - Mismatches are rejected with `403`.
  - The flow now passes the `Candidate` ORM object correctly into `start_interview(...)`.

### F-02 Fixed: Cross-company replay access

- Severity: Critical
- Location:
  - `backend/app/api/v1/company.py`
  - `backend/app/services/interview_service.py`
- Remediation:
  - Replay access is scoped by `company_id`.
  - Private employee assessment replays are now visible only to the owning company.

### F-03 Fixed: Private employee assessments leaking into the shared marketplace

- Severity: High
- Location:
  - `backend/app/services/company_service.py`
- Remediation:
  - Company candidate browsing now excludes interviews linked to `company_assessment_id`.
  - Private employee assessments no longer surface in the shared company candidate database.

### F-04 Fixed: Candidate completion emails sent to every company

- Severity: High
- Location:
  - `backend/app/services/interview_service.py`
- Remediation:
  - Completion notifications are no longer broadcast globally.
  - Notifications are limited to the company that owns the private employee assessment.

### F-05 Fixed: Broken employee assessment start flow

- Severity: High
- Type: Functional bug
- Location:
  - `backend/app/services/assessment_invite_service.py`
  - `backend/app/services/interview_service.py`
- Remediation:
  - `start_interview(...)` is now called with `candidate=...` instead of an unsupported `candidate_id=...`.
  - Regression coverage was added in `backend/tests/test_employee_assessments.py`.

### F-06 Fixed: Company report page calling a candidate-only API

- Severity: High
- Type: Functional bug
- Location:
  - `frontend/src/app/(company)/company/reports/[id]/page.tsx`
  - `backend/app/api/v1/company.py`
- Remediation:
  - Added `GET /api/v1/company/reports/{report_id}` for company-scoped report access.
  - The company report page now uses the company endpoint instead of the candidate-only report API.

### F-07 Fixed: Frontend pinned to a vulnerable Next.js patchline

- Severity: High
- Location:
  - `frontend/package.json`
  - `frontend/package-lock.json`
- Remediation:
  - Upgraded `next` and `eslint-config-next` from `14.2.14` to `14.2.35`.
  - Revalidated the app with `npm run lint` and `npm run build`.

### F-09 Fixed: Overly permissive CORS

- Severity: Medium
- Location:
  - `backend/app/core/config.py`
  - `backend/app/main.py`
- Remediation:
  - Replaced wildcard origins with a config-driven allowlist via `CORS_ORIGINS`.
  - Error responses no longer reflect arbitrary origins unless they are explicitly allowed.

### F-11 Fixed: Interview recording upload lacked file type and size validation

- Severity: Medium
- Location:
  - `backend/app/services/interview_service.py`
  - `.env.example`
- Remediation:
  - Recording uploads now accept only `video/webm` and `video/mp4`.
  - Upload size is capped through `MAX_RECORDING_SIZE_MB`.

### F-12 Fixed: Open redirect on candidate login/register

- Severity: Medium
- Location:
  - `frontend/src/app/(candidate)/candidate/login/page.tsx`
  - `frontend/src/app/(candidate)/candidate/register/page.tsx`
  - `frontend/src/lib/safeRedirect.ts`
- Remediation:
  - Redirect destinations are now sanitized to path-only, same-origin values.
  - Employee invite redirects still work, but external redirect targets are rejected.

## Remaining Findings

### F-08 Open: JWTs stored in `localStorage`

- Severity: Medium
- Location:
  - `frontend/src/lib/auth.ts`
- Risk:
  - Any XSS or malicious browser extension can exfiltrate bearer tokens directly from browser storage.
- Recommended next step:
  - Move auth transport to `HttpOnly` cookies and add CSRF protection.

### F-10 Open: Insecure built-in JWT secret default

- Severity: Medium
- Location:
  - `backend/app/core/config.py`
- Risk:
  - A deployment that keeps the default `SECRET_KEY` can allow forged JWTs.
- Recommended next step:
  - Fail fast on startup outside local development/test when `SECRET_KEY` is unchanged.

## Validation Performed

The following checks were executed on March 18, 2026:

```bash
git diff --check
python3 -m compileall backend/app backend/tests
docker compose exec -T backend alembic upgrade head
docker compose exec -T frontend npm run lint
docker compose exec -T frontend npm run build
cd backend && PYTHONPATH=/tmp/airecruit-testdeps-codex python3 -m pytest tests/test_employee_assessments.py -v
docker compose ps
curl -fsS http://localhost:8001/health
curl -I --max-time 20 http://localhost:3000
```

Observed results:

- `lint`, `build`, migrations, and targeted backend regression tests passed.
- The employee assessment regression suite passed with `3 passed`.
- Backend health returned `{"status":"ok","service":"ai-recruiting-backend"}`.
- Frontend root responded with `HTTP/1.1 200 OK`.

## Recommended Next Additions

1. Add `SECURITY.md` with disclosure policy and mandatory production settings.
2. Add CI for frontend lint/build, targeted backend tests, and dependency scanning.
3. Replace `localStorage` auth with `HttpOnly` cookies.
4. Enforce startup failure when `SECRET_KEY` is still insecure outside local development.
5. Triage and remove the 7 npm vulnerabilities reported during `npm install`.
