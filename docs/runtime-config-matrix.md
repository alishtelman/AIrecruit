# Runtime Config Matrix

This note documents runtime configuration flags that affect security posture, local developer behavior, and the platform-admin overview surface.

Related notes:

- [`docs/platform-admin.md`](./platform-admin.md)
- [`docs/admin-overview.md`](./admin-overview.md)
- [`docs/platform-admin-operator-runbook.md`](./platform-admin-operator-runbook.md)

## Runtime Flags Exposed In Admin Overview

`GET /api/v1/admin/overview` returns:

- `app_env`
- `rate_limit_enabled`
- `platform_admin_bootstrap_enabled`

| Overview field | Source | Meaning |
|---|---|---|
| `app_env` | `settings.APP_ENV` | Raw environment mode string |
| `rate_limit_enabled` | `settings.rate_limit_enabled` | Rate limiting is enforced only when `RATE_LIMIT_ENABLED=true` and the app is not local/test |
| `platform_admin_bootstrap_enabled` | `settings.platform_admin_bootstrap_enabled` | Platform-admin bootstrap is enabled only when local/test or explicit bootstrap is on, and credentials are present |

## Mode Matrix

`Settings.is_local_or_test` treats all of the following as local/test mode:

- `development`
- `dev`
- `local`
- `test`

| Behavior | Local / test | Production-like |
|---|---|---|
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

## AI And Voice Runtime Flags

LLM runtime variables:

- `AI_PROVIDER=openai`
- `OPENAI_API_KEY`
- `OPENAI_MODEL` (`gpt-5.4-mini` by default)

Voice/media runtime variables:

- `GROQ_API_KEY` (media/STT/TTS stack only, not LLM)
- `TTS_PROVIDER`
- `TTS_FALLBACK_PROVIDER`
- `ELEVENLABS_API_KEY`
- `ELEVENLABS_VOICE_ID`
- `ELEVENLABS_TTS_MODEL`

Practical interpretation:

- interviewer and assessor LLM calls use OpenAI only
- there is no mock LLM mode or cross-provider LLM fallback
- STT/TTS can still use the media providers configured by the media service
