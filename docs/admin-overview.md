# Platform Admin Overview Contract

This note documents the verified platform-admin overview surface that exists on `origin/main` at commit `20096ce`.

Related notes:

- [`docs/platform-admin.md`](./platform-admin.md)
- [`docs/access-roles.md`](./access-roles.md)
- [`docs/workspace-routes.md`](./workspace-routes.md)
- [`docs/platform-admin-operator-runbook.md`](./platform-admin-operator-runbook.md)
- [`docs/runtime-config-matrix.md`](./runtime-config-matrix.md)

## Scope

The current platform-admin surface is intentionally lightweight.

It is an overview workspace, not a full operator console yet.

Verified pieces on `origin/main`:

- frontend route: `/admin/dashboard`
- backend endpoint: `GET /api/v1/admin/overview`
- frontend data client: `adminApi.getOverview()`

## Access Rules

- the dashboard requires system role `platform_admin`
- the frontend page uses `useAuth({ redirectTo: "/admin/login", allowedRoles: ["platform_admin"] })`
- the backend endpoint is protected by `get_current_platform_admin`

This means:

- `candidate` users are redirected away
- `company_admin` and `company_member` users are redirected away
- only `platform_admin` can load the overview payload

## API Response Shape

`GET /api/v1/admin/overview` returns:

```json
{
  "metrics": {
    "total_users": 0,
    "active_candidates": 0,
    "active_companies": 0,
    "company_members": 0,
    "interviews_total": 0,
    "interviews_completed": 0,
    "reports_generated": 0
  },
  "runtime": {
    "app_env": "development",
    "mock_ai_enabled": true,
    "rate_limit_enabled": false,
    "platform_admin_bootstrap_enabled": true
  },
  "recent_users": [],
  "recent_companies": [],
  "recent_interviews": [],
  "recent_reports": []
}
```

## Metrics Block

`metrics` contains platform-wide counters:

- `total_users`
- `active_candidates`
- `active_companies`
- `company_members`
- `interviews_total`
- `interviews_completed`
- `reports_generated`

Important interpretation:

- these are aggregate cross-platform counts, not company-scoped analytics
- `active_companies` is based on `Company.is_active`
- `interviews_completed` includes interviews in `completed` and `report_generated`

## Runtime Block

`runtime` exposes a compact operational snapshot:

- `app_env`
- `mock_ai_enabled`
- `rate_limit_enabled`
- `platform_admin_bootstrap_enabled`

This is useful for fast operator checks such as:

- whether the app is running in local/dev/test/prod mode
- whether mock AI fallback is allowed
- whether runtime rate limiting is active
- whether platform-admin bootstrap should be available

## Recent Entities

### `recent_users`

Each item contains:

- `id`
- `email`
- `role`
- `is_active`
- `created_at`

### `recent_companies`

Each item contains:

- `id`
- `name`
- `owner_email`
- `is_active`
- `created_at`

### `recent_interviews`

Each item contains:

- `id`
- `candidate_name`
- `target_role`
- `status`
- `language`
- `created_at`
- `completed_at`
- `report_ready`

`report_ready` is derived from report existence, not from a separate interview flag.

### `recent_reports`

Each item contains:

- `id`
- `candidate_name`
- `target_role`
- `overall_score`
- `hiring_recommendation`
- `created_at`

## Dashboard Surface

Verified UI sections on `/admin/dashboard`:

1. Hero block with current admin session email
2. Metric cards for users, candidates, companies, and reports
3. Runtime card with environment, mock AI, rate limit, and bootstrap status
4. Throughput card with interviews and member counts
5. Recent users list
6. Recent companies list
7. Recent interviews list
8. Recent reports list

This means the current dashboard is optimized for overview and orientation, not for mutation workflows.

## Current Limitations

As verified in `20096ce`, the platform-admin workspace does not yet provide:

- user management actions
- company management actions
- report repair actions
- interview retry or intervention actions
- global AI/runtime configuration editing

Those are reasonable next product steps, but they are not part of the verified current contract.

## Local Verification Expectations

After updating the local checkout to `origin/main` at or after `20096ce`:

- `/admin/login` should load
- platform-admin login should redirect to `/admin/dashboard`
- `/api/v1/admin/overview` should return `200` for the admin session
- the dashboard should render even when the recent lists are empty

If `/admin/login` still returns `404`, see [`docs/platform-admin.md`](./platform-admin.md) for the checkout/update runbook.
