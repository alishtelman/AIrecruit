# Platform Admin Workspace

This note documents the platform admin workspace that was verified on `origin/main` on April 16, 2026.

Related role mapping note:

- [`docs/access-roles.md`](./access-roles.md)
- [`docs/admin-overview.md`](./admin-overview.md)
- [`docs/workspace-routes.md`](./workspace-routes.md)
- [`docs/platform-admin-operator-runbook.md`](./platform-admin-operator-runbook.md)
- [`docs/runtime-config-matrix.md`](./runtime-config-matrix.md)

## Verification Snapshot

- remote branch checked: `origin/main`
- verified commit: `20096ce3b00967886c276af60283ea4154406c80`
- commit date: `2026-04-14 17:03:12 +0500`
- commit title: `Add platform admin workspace and auth guardrails`

At the time of verification, the local checkout was still behind:

- local `HEAD`: `5b42290db4b5f9182d1b9123d4a420513332c499`
- local commit title: `Show task profiles in reports`

That mismatch explains why the running local frontend can still return `404` for `/admin/login` even though the feature is already present on `origin/main`.

## What Landed In `origin/main`

Verified files:

- `frontend/src/app/(admin)/admin/login/page.tsx`
- `frontend/src/app/(admin)/admin/dashboard/page.tsx`
- `frontend/src/app/(admin)/layout.tsx`
- `frontend/src/components/admin-workspace-header.tsx`
- `frontend/src/lib/roleRedirect.ts`
- `backend/app/api/v1/admin.py`
- `backend/app/schemas/admin.py`
- `backend/app/services/admin_service.py`
- `backend/app/core/config.py`
- `backend/app/services/auth_service.py`
- `backend/app/api/v1/deps.py`

The commit also updates auth and redirect behavior in shared frontend/backend files and adds backend coverage in `backend/tests/test_admin.py`.

## Routes

Frontend routes added on `origin/main`:

- `/admin/login`
- `/admin/dashboard`

Backend API added on `origin/main`:

- `GET /api/v1/admin/overview`

The frontend redirect map in `frontend/src/lib/roleRedirect.ts` sends:

- `candidate` -> `/candidate/dashboard`
- `company_admin` and `company_member` -> `/company/dashboard`
- `platform_admin` -> `/admin/dashboard`

## Auth Model

The new backend role is:

- `platform_admin`

Access guard:

- `get_current_platform_admin` in `backend/app/api/v1/deps.py`

Bootstrap behavior is configured in `backend/app/core/config.py` through:

- `PLATFORM_ADMIN_EMAIL`
- `PLATFORM_ADMIN_PASSWORD`
- `PLATFORM_ADMIN_BOOTSTRAP`

Local/test defaults on `origin/main`:

- email: `admin@airecruit.dev`
- password: `Admin12345!`

`backend/app/services/auth_service.py` bootstraps the platform admin during login when local/test bootstrap is enabled and the configured admin account does not exist yet.

## Local Runtime Note

During verification:

- `http://localhost:3000/company/login` returned `200`
- `http://localhost:3000/admin/login` returned `404`

This was expected because the running local services were built from the older local checkout, not from `origin/main` at `20096ce`.

To use the platform admin workspace locally, the checkout and running containers must be updated to include `origin/main` at or after `20096ce`.

## Local Adoption Runbook

If the local app still returns `404` for `/admin/login`, the most likely cause is that the local checkout or containers are still on an older revision.

For the full safe-update and smoke-check flow, see [`docs/platform-admin-operator-runbook.md`](./platform-admin-operator-runbook.md).

Recommended local update flow:

1. Verify the local branch state:
   - `git branch --show-current`
   - `git rev-parse --short HEAD`
   - `git rev-parse --short origin/main`
2. Update the checkout to a revision that contains `20096ce` or newer on `origin/main`.
3. Rebuild and restart the application containers:
   - `docker compose up -d --build`
4. Re-run migrations:
   - `docker compose exec backend alembic upgrade head`
5. Verify the routes:
   - `http://localhost:3000/admin/login`
   - `http://localhost:3000/admin/dashboard`
   - `http://localhost:8001/docs`

Expected local bootstrap login after the update:

- email: `admin@airecruit.dev`
- password: `Admin12345!`

Useful smoke checks after the update:

- `/admin/login` should return `200`
- successful login as `platform_admin` should redirect to `/admin/dashboard`
- `GET /api/v1/admin/overview` should return `200` for the platform admin session

## Config Note

The platform-admin environment keys are defined in `origin/main` at `20096ce`, but an older local checkout may still have a pre-admin `.env.example`.

If the local branch is still behind, it is normal to observe all of the following at once:

- `.env.example` does not contain `PLATFORM_ADMIN_EMAIL`
- the running frontend returns `404` for `/admin/login`
- the backend does not expose `GET /api/v1/admin/overview`

Those symptoms indicate checkout drift, not a broken platform-admin implementation on `origin/main`.

## Scope Of This Note

This document confirms:

- the commit exists on `origin/main`
- the admin workspace files and role wiring exist in that commit
- the expected local bootstrap credentials are defined there

This document does not claim that the full test/build suite was re-run locally against commit `20096ce` during this verification pass.
