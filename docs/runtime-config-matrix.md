# Runtime Config Matrix

This note documents the runtime configuration flags that most directly affect security posture, local developer behavior, and the platform-admin overview surface.

It combines:

- the current runtime rules in `backend/app/core/config.py`
- the verified platform-admin extension present on `origin/main` at commit `20096ce`

Related notes:

- [`docs/platform-admin.md`](./platform-admin.md)
- [`docs/admin-overview.md`](./admin-overview.md)
- [`docs/platform-admin-operator-runbook.md`](./platform-admin-operator-runbook.md)

## Why This Note Exists

Several important behaviors are not controlled by raw environment variables alone.

They are computed from `APP_ENV` and helper properties in `Settings`, especially:

- `allow_mock_ai`
- `rate_limit_enabled`
- `platform_admin_bootstrap_enabled`

Those computed values are what the platform-admin overview exposes in its `runtime` block.

## Runtime Flags Exposed In Admin Overview

Verified on `origin/main` at `20096ce`, `GET /api/v1/admin/overview` returns:

- `app_env`
- `mock_ai_enabled`
- `rate_limit_enabled`
- `platform_admin_bootstrap_enabled`

These fields map to config behavior as follows:

| Overview field | Source | Meaning |
|---|---|---|
| `app_env` | `settings.APP_ENV` | Raw environment mode string |
| `mock_ai_enabled` | `settings.allow_mock_ai` | Mock AI is allowed only when both `ALLOW_MOCK_AI=true` and the app is local/test |
| `rate_limit_enabled` | `settings.rate_limit_enabled` | Rate limiting is enforced only when `RATE_LIMIT_ENABLED=true` and the app is not local/test |
| `platform_admin_bootstrap_enabled` | `settings.platform_admin_bootstrap_enabled` | Platform-admin bootstrap is enabled only when local/test or explicit bootstrap is on, and credentials are present |

## Mode Matrix

`Settings.is_local_or_test` treats all of the following as local/test mode:

- `development`
- `dev`
- `local`
- `test`

The practical behavior split is:

| Behavior | Local / test | Production-like |
|---|---|---|
| `allow_mock_ai` | Can be `true` when `ALLOW_MOCK_AI=true` | Always effectively `false` |
| `rate_limit_enabled` | Effectively `false` even if `RATE_LIMIT_ENABLED=true` | Controlled by `RATE_LIMIT_ENABLED` |
| `platform_admin_bootstrap_enabled` | Enabled when admin credentials resolve successfully | Requires explicit `PLATFORM_ADMIN_BOOTSTRAP=true` plus credentials |
| `AUTH_ALLOW_BEARER` | Allowed for compatibility | Must be `false` |
| `SESSION_COOKIE_SECURE` | May be `false` | Must be `true` |
| `SECRET_KEY` default | Tolerated for local/test | Rejected |
| Wildcard CORS / CSRF origins | Tolerated in local/test | Rejected |

## Security Guardrails Outside Local/Test

`Settings.validate_security_settings()` blocks startup outside local/test if any of the following are true:

- `SECRET_KEY` is still a known insecure default
- `SECRET_KEY` is shorter than 32 characters
- `AUTH_ALLOW_BEARER=true`
- `SESSION_COOKIE_SECURE=false`
- `CORS_ORIGINS` contains `*`
- `CSRF_TRUSTED_ORIGINS` contains `*`

These rules are covered by `backend/tests/test_security_settings.py`.

## Platform Admin Bootstrap Matrix

Verified on `origin/main`, the platform-admin config adds:

- `PLATFORM_ADMIN_EMAIL`
- `PLATFORM_ADMIN_PASSWORD`
- `PLATFORM_ADMIN_BOOTSTRAP`

Computed behavior:

| Condition | Result |
|---|---|
| Local/test mode and no explicit admin env vars | Defaults resolve to `admin@airecruit.dev` / `Admin12345!` |
| Local/test mode with explicit admin env vars | Explicit values win |
| Production-like mode with no explicit admin env vars | No bootstrap credentials resolve |
| Production-like mode with credentials but `PLATFORM_ADMIN_BOOTSTRAP=false` | Bootstrap remains off |
| Production-like mode with credentials and `PLATFORM_ADMIN_BOOTSTRAP=true` | Bootstrap can be enabled |

This is why platform-admin login can work automatically in local/test on the verified remote revision while staying opt-in outside local/test.

## AI And Voice Runtime Flags

Core runtime variables:

- `GROQ_API_KEY`
- `ALLOW_MOCK_AI`
- `TTS_PROVIDER`
- `TTS_FALLBACK_PROVIDER`
- `ELEVENLABS_API_KEY`
- `ELEVENLABS_VOICE_ID`
- `ELEVENLABS_TTS_MODEL`

Practical interpretation:

- interviewer/assessor/STT rely on Groq configuration
- mock AI fallback is a development/test convenience, not a production mode
- TTS can use Groq or ElevenLabs with provider fallback

## Rate Limit Runtime Flags

Relevant variables:

- `RATE_LIMIT_ENABLED`
- `RATE_LIMIT_LOGIN_PER_MINUTE`
- `RATE_LIMIT_INTERVIEW_START_PER_MINUTE`
- `RATE_LIMIT_INTERVIEW_MESSAGE_PER_MINUTE`
- `RATE_LIMIT_TTS_PER_MINUTE`
- `RATE_LIMIT_STT_PER_MINUTE`

Important nuance:

- the numeric limits can be configured in all environments
- actual enforcement is suppressed in local/test by `settings.rate_limit_enabled`

This matters when comparing local smoke checks with production behavior.

## Auth And Session Runtime Flags

Relevant variables:

- `SESSION_COOKIE_NAME`
- `SESSION_COOKIE_SAMESITE`
- `SESSION_COOKIE_SECURE`
- `AUTH_ALLOW_BEARER`
- `CSRF_TRUSTED_ORIGINS`
- `CORS_ORIGINS`
- `ACCESS_TOKEN_EXPIRE_MINUTES`

Important boundary:

- local/test is intentionally permissive for developer convenience
- production-like environments are intentionally strict and fail fast on unsafe settings

## `.env.example` Drift Note

The current local checkout and `origin/main` can differ here.

Observed during verification:

- current local `.env.example` does not yet include platform-admin variables
- `origin/main` at `20096ce` does include:
  - `PLATFORM_ADMIN_EMAIL=admin@airecruit.dev`
  - `PLATFORM_ADMIN_PASSWORD=Admin12345!`
  - `PLATFORM_ADMIN_BOOTSTRAP=true`

So if local docs mention platform admin but the local `.env.example` still lacks those keys, that is a revision mismatch, not a contradiction in the verified remote feature set.

## Practical Reading

When diagnosing runtime behavior, separate three questions:

1. Which revision is running: current local checkout or `origin/main` after `20096ce`?
2. Is the app in local/test mode or production-like mode?
3. Are you looking at raw env vars or computed settings properties?

That distinction explains most differences in:

- mock AI availability
- rate limit behavior
- platform-admin bootstrap behavior
- startup security validation
