# Workspace Route Map

This note documents the main frontend route namespaces in AIRecruit and the user roles they are intended for.

It combines:

- the route structure present in the current local checkout
- the verified platform-admin namespace that exists on `origin/main` at commit `20096ce`

Related notes:

- [`docs/access-roles.md`](./access-roles.md)
- [`docs/platform-admin.md`](./platform-admin.md)
- [`docs/admin-overview.md`](./admin-overview.md)

## Route Families

The application is split into separate route families rather than one mixed workspace:

| Route family | Intended actor | Auth expectation | Notes |
|---|---|---|---|
| `/candidate/*` | Candidate | Candidate session | Personal dashboard, interview runtime, reports, profile |
| `/company/*` | Company owner or company member | Company session | Hiring workspace, templates, campaigns, reports, settings |
| `/employee/invite/*` | Invited assessment participant | Token entry | Invite-based runtime entry into modular assessments |
| `/candidate/share/*` | Share-link viewer | Token entry | Candidate report/share-link access without full workspace login |
| `/admin/*` | Platform admin | Platform-admin session | Verified on `origin/main`; not present in older local checkouts |

## Candidate Workspace

Candidate routes present in the current local checkout:

- `/candidate/login`
- `/candidate/register`
- `/candidate/dashboard`
- `/candidate/profile`
- `/candidate/resume`
- `/candidate/interview/start`
- `/candidate/interview/[id]`
- `/candidate/reports`
- `/candidate/reports/[id]`

Intent:

- candidate self-service onboarding
- direct interview entry and active interview runtime
- candidate-visible report review
- profile and resume maintenance

Default landing for system role `candidate`:

- `/candidate/dashboard`

## Company Workspace

Company routes present in the current local checkout:

- `/company/login`
- `/company/register`
- `/company/dashboard`
- `/company/employees`
- `/company/team`
- `/company/templates`
- `/company/settings`
- `/company/candidates/[id]`
- `/company/reports/[id]`
- `/company/interviews/[id]/replay`

Intent:

- company onboarding and session entry
- assessment campaign setup and invite management
- team collaboration and company settings
- candidate review, report review, and interview replay

Default landing for system roles `company_admin` and `company_member`:

- `/company/dashboard`

## Invite And Share Routes

Token-based entry points in the current local checkout:

- `/employee/invite/[token]`
- `/candidate/share/[token]`

These routes are important because they are not the same thing as the logged-in workspaces:

- `/employee/invite/[token]` is for invite-driven assessment access
- `/candidate/share/[token]` is for shared candidate-facing report access

They should be treated as separate surfaces with their own token validation and session assumptions.

## Platform Admin Workspace

Verified on `origin/main` at commit `20096ce`:

- `/admin/login`
- `/admin/dashboard`

Default landing for system role `platform_admin`:

- `/admin/dashboard`

Important local-version note:

- older local checkouts can still lack `frontend/src/app/(admin)/*`
- in that state, `/admin/login` returning `404` is expected
- this indicates checkout drift relative to `origin/main`, not a contradiction in the verified remote docs

See [`docs/platform-admin.md`](./platform-admin.md) for the verification snapshot and local adoption runbook.

## Redirect Model

Verified route redirect intent:

- `candidate` -> `/candidate/dashboard`
- `company_admin` -> `/company/dashboard`
- `company_member` -> `/company/dashboard`
- `platform_admin` -> `/admin/dashboard`

This role-based redirect contract matters because the app is organized by workspace namespace, not by one shared post-login shell.

## Practical Reading

When debugging navigation or access issues, first ask which namespace the route belongs to:

1. Candidate workspace
2. Company workspace
3. Invite/share token flow
4. Platform admin workspace

That usually tells you which auth guard, redirect rule, and role model should apply.
