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
- set strict `CSRF_TRUSTED_ORIGINS` (or leave empty to inherit `CORS_ORIGINS`)
- set `AUTH_ALLOW_BEARER=false`
- run behind HTTPS only
- set `ALLOW_MOCK_AI=false`
- rotate any default/example secrets

Startup will fail outside local/test when security-critical settings are unsafe
(`SECRET_KEY`, `AUTH_ALLOW_BEARER`, secure cookie settings, wildcard CORS/CSRF).

---

## Current Security Controls

- Cookie-first auth with `HttpOnly` session cookie.
- Cookie-auth write endpoints enforce trusted `Origin/Referer` CSRF checks.
- Backward-compatible Bearer auth can be disabled via `AUTH_ALLOW_BEARER=false` outside local/test.
- API responses include baseline hardening headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`; plus HSTS when secure cookies are enabled).
- Non-local environments enforce per-endpoint rate limiting on login/interview/voice endpoints.
- Security audit logs are emitted for failed auth, CSRF denials, and rate-limit blocks.
- Candidate privacy visibility + approval flow for company access.
- Company-scoped access enforcement for private reports and interview replays.
- Employee invite start is bound to authenticated candidate email.
- Recording upload is restricted by MIME type and max size.
- Candidate login/register redirects are path-only sanitized.

---

## Known Security Debt

- API-level Bearer compatibility still exists as a runtime toggle.
  - Risk: leaving `AUTH_ALLOW_BEARER=true` in hardened environments.
  - Target state: keep it disabled by policy in all non-local environments.
- Python dependency baseline file is retained for emergency exceptions:
  - [`backend/pip_audit_baseline.txt`](backend/pip_audit_baseline.txt)
  - Current state: empty (no accepted Python vulnerability exceptions).

---

## Minimum Security Checks per Release

```bash
docker compose exec -T backend alembic upgrade head
docker compose exec -T frontend npm run lint
docker compose exec -T frontend npm run build
cd backend && python3 -m pytest -v
npm --prefix frontend audit --audit-level=high
pip-audit -r backend/requirements.txt
```

For high-risk changes (auth/privacy/company access), add targeted suites:

```bash
cd backend && python3 -m pytest tests/test_auth.py tests/test_candidate_privacy.py tests/test_company_collaboration_roles.py tests/test_employee_assessments.py -v
```
