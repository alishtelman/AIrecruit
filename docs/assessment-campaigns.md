# Assessment Campaigns

This document describes the shipped modular assessment flow that sits on top of the core interview engine.

## Scope

As of April 2026, company assessment campaigns support:

- internal employee assessments and external candidate assessments
- branding, deadlines, and expiry on invite links
- ordered `module_plan` execution with per-module status tracking
- role-aware `coding_task` and `sql_live` profiles
- candidate-side module preview and resume behavior
- module-aware report summaries plus saved task workspace artifacts
- company AI workspace settings for proctoring policy and future model-aware runtime preferences

## Runtime Model

`company_assessments.module_plan` stores the ordered module list, and `company_assessments.current_module_index` points at the active module.

Current behavior:

- the first module must be `adaptive_interview`
- runtime-ready modules are `adaptive_interview`, `system_design`, `behavioral_interview`, `written_communication`, `coding_task`, and `sql_live`
- staged module types such as `data_analysis` and `devops_incident` can exist in the plan but do not yet have a candidate-startable runtime
- when a module finishes, the service advances `current_module_index`; the assessment is marked `completed` only after the last module finishes

## Company Workflow

Recommended company flow:

1. Optionally pick an interview template for the adaptive interview opener.
2. Fetch role-aware module profile options from `GET /api/v1/company/assessment-module-profiles`.
3. Build `module_plan` in the order you want the candidate to complete it.
4. Create the campaign with `POST /api/v1/company/assessments`.
5. Share the branded invite link from the company workspace.

Important constraints:

- `POST /api/v1/company/assessments` validates supported `module_type` values
- duplicate `module_id` values are rejected
- the first module must remain `adaptive_interview` until alternate start flows are implemented

Example request:

```json
{
  "employee_email": "candidate@example.com",
  "employee_name": "Aruzhan Sadykova",
  "assessment_type": "candidate_external",
  "target_role": "frontend_engineer",
  "template_id": null,
  "module_plan": [
    {
      "module_id": "adaptive_interview_1",
      "module_type": "adaptive_interview",
      "title": "Adaptive Interview"
    },
    {
      "module_id": "coding_task_main",
      "module_type": "coding_task",
      "title": "Coding Task",
      "config": {
        "scenario_id": "async_search_state_manager"
      }
    },
    {
      "module_id": "sql_live_main",
      "module_type": "sql_live",
      "title": "SQL Live",
      "config": {
        "scenario_id": "incident_error_budget_audit"
      }
    }
  ],
  "deadline_at": "2026-04-20T12:00:00Z",
  "expires_at": "2026-04-22T12:00:00Z",
  "branding_name": "Frontend Hiring Sprint",
  "branding_logo_url": "https://cdn.example.com/logo.png"
}
```

## Task Profiles

`GET /api/v1/company/assessment-module-profiles?target_role=...&language=...` returns profile options for:

- `coding_task`
- `sql_live`

Each option returns:

- `scenario_id`
- `title`
- `prompt`
- `stack_focus`
- `preferred_language`
- `workspace_hint`
- `recommended`

This endpoint is used by the company workspace form to preselect role-aligned tasks before invite creation.

## Invite Experience

`GET /api/v1/employee/invite/{token}` is the public preload endpoint for branded invite pages.

It returns:

- campaign metadata (`assessment_type`, role, template, deadlines, branding)
- the full `module_plan`
- `current_module_index`, `current_module_type`, and `current_module_title`
- `current_module_preview` with scenario prompt, stack focus, preferred language, and workspace hint
- `active_interview_id` when the invite already has an in-progress interview
- `can_start_current_module` so the frontend knows whether it can start or only resume

This lets the same invite link behave correctly for first launch, resume, completed, expired, and runtime-not-yet-available states.

## Candidate Runtime

Interview responses are now module-aware.

The following payloads can expose both `assessment_progress` and `module_session`:

- `GET /api/v1/interviews/{interview_id}`
- `POST /api/v1/interviews/{interview_id}/message`
- `POST /api/v1/interviews/{interview_id}/finish`
- `GET /api/v1/interviews/{interview_id}/report-status`
- `POST /api/v1/interviews/{interview_id}/report-retry`

`module_session` carries:

- `module_type` and `module_title`
- `scenario_id`, `scenario_title`, and `scenario_prompt`
- `stack_focus`, `preferred_language`, and `workspace_hint`
- `stage_key`, `stage_title`, `stage_index`, and `stage_count`

For `coding_task` and `sql_live`, the candidate UI also uses a saved code workspace artifact:

- `GET /api/v1/interviews/{interview_id}/coding-artifact`
- `PUT /api/v1/interviews/{interview_id}/coding-artifact`

The artifact is stored in `interviews.interview_state` and is only available for `coding_task` or `sql_live` interviews.

For `written_communication`, the candidate UI uses a separate saved writing artifact:

- `GET /api/v1/interviews/{interview_id}/written-artifact`
- `PUT /api/v1/interviews/{interview_id}/written-artifact`

## Report Surface

Assessment reports can now include both generic interview scoring and module-specific evidence.

Shared module context:

- `module_session`

Module summaries:

- `system_design_summary`
- `behavioral_interview_summary`
- `coding_task_summary`
- `sql_live_summary`
- `written_communication_summary`

Notable module summary fields:

- `behavioral_interview_summary` includes ownership, collaboration, leadership, and reflection scoring plus stage-level evidence and coaching notes
- `coding_task_summary` includes coverage, runner, and stack checks, plus `implementation_excerpt`, `has_code_submission`, and `code_signal_score`
- `sql_live_summary` includes validation checks, `query_excerpt`, and `has_query_submission`
- `written_communication_summary` includes clarity, structure, audience-awareness, `writing_excerpt`, and targeted next-step guidance

The same module context also appears in company replay/report views so the reviewer can connect transcript evidence to the assigned scenario.

## Company Review Surface

Company-side review now includes:

- `GET /api/v1/company/reports/{report_id}` for the full module-aware report
- `GET /api/v1/company/reports/{report_id}/proctoring-timeline` for normalized signal events and risk summaries
- `GET /api/v1/company/interviews/{interview_id}/replay` for transcript/replay context with module metadata

The company assessments list also returns enriched `module_plan` items with:

- `scenario_id`
- `scenario_title`
- `stack_focus`
- `preferred_language`
- `workspace_hint`

That allows the workspace to show which task profile was actually assigned to each campaign and surfaced in the report.

## AI Workspace Settings

Company admins can inspect and update AI workspace controls through:

- `GET /api/v1/company/settings/ai`
- `PUT /api/v1/company/settings/ai`

Important semantics:

- `proctoring_policy_mode` is applied immediately to new company assessment interviews
- `interviewer_model_preference` and `assessor_model_preference` are stored now so later model-aware runtimes can honor admin preference without losing intent
- the response also exposes runtime provider/model fields plus `runtime_applied_fields` and `stored_preference_fields`

## Related Files

- [`backend/app/services/assessment_invite_service.py`](../backend/app/services/assessment_invite_service.py)
- [`backend/app/services/interview_service.py`](../backend/app/services/interview_service.py)
- [`backend/app/api/v1/company.py`](../backend/app/api/v1/company.py)
- [`backend/app/api/v1/employee.py`](../backend/app/api/v1/employee.py)
- [`backend/app/api/v1/interviews.py`](../backend/app/api/v1/interviews.py)
