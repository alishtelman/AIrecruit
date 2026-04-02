# Security Review and Remediation Status

Last update: April 1, 2026
Original audit: March 18, 2026

---

## Executive Summary

The project has moved from an initial remediation branch state to an expanded production-oriented baseline on `main`.

- Most high/critical access-control issues from the March audit are remediated.
- Cookie-first authentication is now in place.
- Startup now fails in non-local environments with insecure `SECRET_KEY`.
- Remaining security debt is mostly migration/operational hardening, not broken access control.

---

## Closed Findings

### F-01 Closed: Employee assessment invite hijack risk

- `POST /api/v1/employee/invite/{token}/start` now validates authenticated candidate email against invite target.
- Email mismatch is rejected with `403`.

### F-02 Closed: Cross-company replay access

- Replay/report endpoints are scoped to the owning company for private assessments.

### F-03 Closed: Private employee assessments leaked into marketplace

- Private employee assessment records are excluded from shared marketplace browsing.

### F-04 Closed: Candidate completion emails sent globally

- Company notifications are now scoped to the owning company context.

### F-05 Closed: Employee assessment start flow call mismatch

- Service-level start flow call path fixed and covered by regression tests.

### F-06 Closed: Company report UI used candidate-only API

- Company-scoped report endpoint implemented and used by company UI.

### F-07 Closed: Next.js vulnerable patchline

- Frontend moved to patched Next.js line (`14.2.35`).

### F-09 Closed: Overly permissive CORS

- CORS is now allowlist-driven via `CORS_ORIGINS`.

### F-10 Closed: Insecure default `SECRET_KEY` in production

- Runtime validation now rejects insecure/default secret outside local/test (`APP_ENV` guard in config).

### F-11 Closed: Recording upload validation gaps

- Upload MIME restrictions and max-size enforcement are in place.

### F-12 Closed: Candidate auth open-redirect

- Redirect targets sanitized to path-only safe redirects.

---

## Remaining / Ongoing Findings

### R-01 Open (Medium): Transitional localStorage Bearer token compatibility

- Location: `frontend/src/lib/auth.ts`, `frontend/src/lib/api.ts`
- Current state:
  - cookie-first auth is implemented and preferred;
  - Bearer/localStorage path remains for backward compatibility.
- Risk:
  - XSS or malicious extension can read localStorage tokens.
- Recommended next step:
  - complete migration to cookie-only auth transport and remove localStorage token path;
  - enforce CSRF protection strategy for sensitive state-changing routes.

### R-02 Open (Medium): Dependency vulnerability lifecycle

- `npm`/Python dependency advisories require ongoing triage and patch cadence.
- Recommended next step:
  - add mandatory dependency scanning in CI and block release on critical/high findings.

---

## Security Controls Confirmed in Current Baseline

- HttpOnly cookie session auth with secure/samesite controls.
- Backward-compatible Bearer path retained temporarily (migration mode).
- Company/candidate privacy and access gating in marketplace + direct share flows.
- Invite-start identity binding for private assessments.
- Report/replay access control scoped to owning company.
- CORS allowlist configuration.
- `SECRET_KEY` fail-fast guard in non-local environments.
- Recording upload MIME and size restrictions.

---

## Recommended Next Additions

1. Finish cookie-only auth migration and remove localStorage bearer helper.
2. Add CSRF mitigation checklist and tests for sensitive write routes.
3. Add CI security gates:
   - frontend lint/build
   - targeted backend auth/privacy tests
   - dependency scanning (npm + pip)
4. Add release checklist step that validates `APP_ENV`, cookie security flags, and `ALLOW_MOCK_AI=false` in production.

---

## Validation Commands (Current Standard)

```bash
git diff --check
docker compose exec -T backend alembic upgrade head
docker compose exec -T frontend npm run lint
docker compose exec -T frontend npm run build
cd backend && python3 -m pytest tests/test_auth.py tests/test_candidate_privacy.py tests/test_company_collaboration_roles.py tests/test_employee_assessments.py -v
curl -fsS http://localhost:8001/health
curl -I http://localhost:3000
```
