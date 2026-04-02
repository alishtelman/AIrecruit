# Security Policy

## Reporting a Vulnerability

Do not post exploit details in public issues.

Please contact the repository owner/maintainer privately and include:

- affected component and endpoint/path
- reproducible steps
- impact (confidentiality, integrity, availability)
- optional mitigation proposal

Allow reasonable validation/remediation time before disclosure.

---

## Supported Baseline

The active `main` branch is the supported security baseline.

---

## Production Requirements (Mandatory)

Before exposing the system publicly:

- set `APP_ENV=production`
- set a strong `SECRET_KEY` (32+ random chars)
- set `SESSION_COOKIE_SECURE=true`
- set strict `CORS_ORIGINS` (no wildcard)
- run behind HTTPS only
- set `ALLOW_MOCK_AI=false`
- rotate any default/example secrets

Startup will fail outside local/test when `SECRET_KEY` is insecure.

---

## Current Security Controls

- Cookie-first auth with `HttpOnly` session cookie.
- Backward-compatible Bearer auth still accepted during migration.
- Candidate privacy visibility + approval flow for company access.
- Company-scoped access enforcement for private reports and interview replays.
- Employee invite start is bound to authenticated candidate email.
- Recording upload is restricted by MIME type and max size.
- Candidate login/register redirects are path-only sanitized.

---

## Known Security Debt

- Bearer-token compatibility remains in frontend/localStorage for migration safety.
  - Risk: XSS can expose localStorage token.
  - Target state: cookie-only auth transport + CSRF hardening for sensitive write actions.
- Dependency vulnerability triage should continue in CI on each release.

---

## Minimum Security Checks per Release

```bash
docker compose exec -T backend alembic upgrade head
docker compose exec -T frontend npm run lint
docker compose exec -T frontend npm run build
cd backend && python3 -m pytest -v
```

For high-risk changes (auth/privacy/company access), add targeted suites:

```bash
cd backend && python3 -m pytest tests/test_auth.py tests/test_candidate_privacy.py tests/test_company_collaboration_roles.py tests/test_employee_assessments.py -v
```
