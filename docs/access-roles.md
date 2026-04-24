# Access Role Matrix

This note documents how authentication roles and workspace access are split in AIRecruit.

It combines:

- the current local access model present in this checkout
- the verified platform-admin extension that exists on `origin/main` at commit `20096ce`

## Core Idea

There are two different role layers in the product:

1. The system-level user role stored in `users.role`
2. The company-scoped workspace role exposed as `company_member_role` in auth responses

These are related but not identical.

## System Role Matrix

| System role (`users.role`) | Frontend `company_member_role` | Scope | Default workspace |
|---|---|---|---|
| `candidate` | `null` | Candidate-only | `/candidate/dashboard` |
| `company_admin` | `admin` | Own company | `/company/dashboard` |
| `company_member` | `recruiter` or `viewer` | Invited company member | `/company/dashboard` |
| `platform_admin` | `null` | Whole platform | `/admin/dashboard` |

Notes:

- `company_admin` is the company owner account created during company registration.
- `company_member` is an invited user linked through `company_members`.
- `platform_admin` was verified on `origin/main` and is documented in detail in [`docs/platform-admin.md`](./platform-admin.md).

## Company Workspace Role Mapping

The company workspace uses a second, company-scoped role concept:

- `admin`
- `recruiter`
- `viewer`

How it maps:

- `company_admin` is projected to `company_member_role="admin"` in auth responses.
- `company_member` is projected from `company_members.role`.
- legacy `membership.role == "member"` is normalized to `recruiter`.
- `candidate` and `platform_admin` do not have a company-scoped role.

This means frontend code should not treat `users.role` and `company_member_role` as interchangeable.

## Ownership And Boundaries

### Candidate

- Can access candidate profile, resume, direct interviews, candidate-scoped reports, and share-link flows.
- Cannot access company workspaces.
- Cannot access platform admin APIs.

### Company admin

- Is the owner of a company, not a global admin.
- Passes company-owner-only guards such as `get_current_company_admin`.
- Is surfaced in frontend UI as company role `admin`.
- Can manage company-only settings, members, templates, campaigns, and other admin-only company actions.

### Company member

- Has system role `company_member`.
- Enters the company workspace, but permissions depend on projected company role.
- `recruiter` can access recruiter-level actions.
- `viewer` is read-only in places where mutation is restricted.

### Platform admin

- Is a cross-company, platform-wide role.
- Does not resolve into company context.
- Uses dedicated guard `get_current_platform_admin`.
- Owns `/admin/*` routes and `/api/v1/admin/*` endpoints on `origin/main`.

## Backend Guard Model

Current and verified guard split:

- `get_current_candidate`
- `get_current_company_admin`
- `get_current_company`
- `get_current_company_context`
- `get_current_company_recruiter`

Verified on `origin/main`:

- `get_current_platform_admin`

Practical meaning:

- company APIs should use company guards, not raw role checks spread across handlers
- platform APIs should use the dedicated platform-admin guard
- candidate APIs should remain isolated from both company and platform workspaces

## Frontend Redirect Model

Verified on `origin/main`, the shared redirect helper maps:

- `candidate` -> `/candidate/dashboard`
- `company_admin` -> `/company/dashboard`
- `company_member` -> `/company/dashboard`
- `platform_admin` -> `/admin/dashboard`

This routing logic lives in `frontend/src/lib/roleRedirect.ts`.

For the broader route namespace split, see [`docs/workspace-routes.md`](./workspace-routes.md).

## Why `company_admin` Is Not `platform_admin`

These roles solve different problems:

- `company_admin` is the owner of one company workspace
- `platform_admin` is an operator of the whole application

The important boundary is:

- company admins should not get cross-company visibility by default
- platform admins should not be forced through company context resolution

## Local Checkout Note

If the current local app does not expose `platform_admin` behavior yet, that may be expected.

In this repository state:

- the local checkout can still be behind `origin/main`
- `platform_admin` may exist only in the verified remote commit `20096ce`
- `/admin/login` returning `404` locally can therefore be a checkout/version issue, not an auth-model bug

See [`docs/platform-admin.md`](./platform-admin.md) for the verified remote snapshot and the local update runbook.
