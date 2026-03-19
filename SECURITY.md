# Security Policy

## Reporting

If you find a security issue, do not open a public issue with exploit details.

- Email the maintainer or repository owner with:
  - affected area
  - reproduction steps
  - impact assessment
  - any proposed mitigation
- Give reasonable time for validation and remediation before public disclosure.

## Supported Baseline

This project currently treats the latest `main` branch as the supported security baseline.

## Production Requirements

Before exposing the app outside local development:

- Set `APP_ENV=production`
- Override `SECRET_KEY` with a long random value
- Set `SESSION_COOKIE_SECURE=true`
- Restrict `CORS_ORIGINS` to trusted frontend origins only
- Use HTTPS for both frontend and backend
- Rotate any example/default secrets
- Review `security_best_practices_report.md` and close any remaining high-risk items

## Current Controls

- Browser auth uses `HttpOnly` session cookies by default
- Backend still accepts bearer tokens for backward compatibility during migration
- Candidate privacy controls gate marketplace access, direct links, and request-only approvals
- Private assessment reports and replays stay company-scoped
- Recording uploads are constrained by MIME type and size

## Recommended Ongoing Checks

- Run frontend lint and build on every change
- Run backend targeted auth/privacy/collaboration tests on every change
- Keep dependencies updated and review advisories before releases
