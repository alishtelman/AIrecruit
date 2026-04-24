# Platform Admin Operator Runbook

This runbook describes how to validate the platform-admin workspace locally after it lands on `origin/main`.

It is intended for the situation where:

- the remote branch already contains the admin workspace
- the local checkout is still behind
- the local working tree may already contain unrelated in-progress changes

Related notes:

- [`docs/platform-admin.md`](./platform-admin.md)
- [`docs/admin-overview.md`](./admin-overview.md)
- [`docs/workspace-routes.md`](./workspace-routes.md)

## Goal

Confirm all of the following locally without accidentally overwriting unrelated work:

- `/admin/login` loads
- `platform_admin` login works
- `/admin/dashboard` renders
- `GET /api/v1/admin/overview` is available to the admin session

## Recommended Validation Strategy

If the current checkout is dirty, prefer validating from a separate worktree instead of forcing the main working directory forward.

This is the safest option because it:

- preserves the current in-progress branch state
- avoids stash/reapply conflicts
- allows rebuilding containers from the verified remote revision

## Option A: Validate In A Separate Worktree

Recommended when the current checkout already has uncommitted work.

1. Refresh remote refs:
   - `git fetch origin --prune`
2. Create a temporary worktree from remote main:
   - `git worktree add ../AIrecruit-origin-main origin/main`
3. Move into the new worktree:
   - `cd ../AIrecruit-origin-main`
4. Confirm the revision:
   - `git rev-parse --short HEAD`
   - the revision should be `20096ce` or newer
5. Start the stack from that checkout:
   - `docker compose up -d --build`
6. Apply migrations:
   - `docker compose exec backend alembic upgrade head`

This approach avoids touching the original dirty tree.

## Option B: Fast-Forward The Active Checkout

Use this only when the active checkout is clean, or when its current changes are already safely committed elsewhere.

Suggested flow:

1. Refresh remote refs:
   - `git fetch origin --prune`
2. Confirm current state:
   - `git status --short`
   - `git rev-parse --short HEAD`
   - `git rev-parse --short origin/main`
3. Update to a revision that contains `20096ce` or newer.
4. Rebuild containers:
   - `docker compose up -d --build`
5. Apply migrations:
   - `docker compose exec backend alembic upgrade head`

If the tree is not clean, do not force through with destructive git commands.

## Required Bootstrap Inputs

Verified on `origin/main`:

- `PLATFORM_ADMIN_EMAIL`
- `PLATFORM_ADMIN_PASSWORD`
- `PLATFORM_ADMIN_BOOTSTRAP`

Local/test defaults at the verified revision:

- email: `admin@airecruit.dev`
- password: `Admin12345!`

If local bootstrap is enabled, the admin account should be created during login if it does not already exist.

## Smoke Check Sequence

After the updated containers are running, validate in this order.

### 1. Frontend route presence

Open:

- `http://localhost:3000/admin/login`

Expected:

- HTTP `200`
- login form rendered instead of Next.js `404`

### 2. Backend route presence

Open:

- `http://localhost:8001/docs`

Expected:

- the admin router is present
- `GET /api/v1/admin/overview` appears in the OpenAPI surface

### 3. Platform-admin login

Sign in at `/admin/login` with:

- email: `admin@airecruit.dev`
- password: `Admin12345!`

Expected:

- successful auth
- redirect to `/admin/dashboard`

### 4. Dashboard render

Open:

- `http://localhost:3000/admin/dashboard`

Expected UI surface:

- session/hero block with admin email
- metric cards
- runtime summary
- throughput summary
- recent users
- recent companies
- recent interviews
- recent reports

Empty recent lists are acceptable in a fresh local environment.

### 5. Overview API access

With an authenticated platform-admin session, verify:

- `GET /api/v1/admin/overview`

Expected:

- HTTP `200`
- JSON payload with `metrics`, `runtime`, `recent_users`, `recent_companies`, `recent_interviews`, `recent_reports`

## Expected Failure Meanings

### `/admin/login` returns `404`

Most likely causes:

- the running frontend is still built from an older checkout
- the local checkout does not yet contain `frontend/src/app/(admin)/*`

This is usually a version-drift issue, not an auth bug.

### Login fails with invalid credentials

Check:

- the active checkout actually contains the platform-admin bootstrap code
- the environment does not override the default admin credentials
- `PLATFORM_ADMIN_BOOTSTRAP` is enabled in the local/test environment

### `/admin/dashboard` redirects away after login

Most likely causes:

- the session was created without role `platform_admin`
- the frontend redirect logic and backend auth model are out of sync across revisions

Confirm the runtime is built from one consistent checkout.

### `GET /api/v1/admin/overview` returns `401` or `403`

Interpretation:

- `401` usually means the session cookie is missing or not being sent
- `403` usually means the authenticated user is not recognized as `platform_admin`

## Minimal Validation Record

For a lightweight verification note, capture:

- checkout revision used for the run
- whether the app was launched from the active tree or a separate worktree
- result for `/admin/login`
- result for login redirect
- result for `/admin/dashboard`
- result for `GET /api/v1/admin/overview`

That is enough to distinguish route drift, auth drift, and API drift.
