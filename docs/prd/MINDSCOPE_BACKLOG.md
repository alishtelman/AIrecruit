# MindScope Backlog

Status values:

- `todo`
- `in_progress`
- `blocked`
- `done`

Priority values:

- `P0` critical foundation
- `P1` first product slice
- `P2` important expansion
- `P3` later maturity

## P0 Foundation

### MS-001 Assessment Session Orchestrator

- Status: `todo`
- Priority: `P0`
- Goal: support multiple modules inside one assessment flow instead of a single interview-only runtime
- Main backend areas:
  - `backend/app/models/company_assessment.py`
  - `backend/app/models/interview.py`
  - `backend/app/services/assessment_invite_service.py`
  - `backend/app/services/interview_service.py`
- Main frontend areas:
  - `frontend/src/app/employee/invite/[token]/page.tsx`
  - `frontend/src/app/(candidate)/candidate/interview/start/page.tsx`
  - `frontend/src/lib/types.ts`
  - `frontend/src/lib/api.ts`
- Acceptance criteria:
  - one assessment can define ordered modules
  - backend persists current module and module state
  - frontend can resume the correct module

### MS-002 Module Result Persistence

- Status: `todo`
- Priority: `P0`
- Goal: persist per-module evidence and scores separately from the top-level report
- Main backend areas:
  - new model and migration near `assessment_reports`
  - `backend/app/models/report.py`
  - `backend/app/schemas/report.py`
  - `backend/app/services/interview_service.py`
- Acceptance criteria:
  - every module stores raw evidence, structured score, and summary
  - report API can return module blocks

### MS-003 Report UI V2 Shell

- Status: `todo`
- Priority: `P0`
- Goal: make report pages module-aware
- Main frontend areas:
  - `frontend/src/app/(candidate)/candidate/reports/[id]/page.tsx`
  - `frontend/src/app/(company)/company/reports/[id]/page.tsx`
  - `frontend/src/lib/types.ts`
- Acceptance criteria:
  - report pages render module sections
  - report pages show module-specific evidence and summaries

## P1 First Product Slice

### MS-010 System Design Module MVP

- Status: `todo`
- Priority: `P1`
- Goal: dedicated system design flow using the existing adaptive interview engine as the first implementation base
- Main backend areas:
  - `backend/app/ai/interviewer.py`
  - `backend/app/ai/competencies.py`
  - `backend/app/services/interview_service.py`
- Main frontend areas:
  - candidate assessment flow page
  - company replay/report pages
- Acceptance criteria:
  - curated system-design scenarios exist
  - module has explicit stages: requirements, high-level, trade-offs
  - report includes system-design rubric output

### MS-011 System Design Replay Grouping

- Status: `todo`
- Priority: `P1`
- Goal: group replay and evidence by system-design stage
- Main areas:
  - `backend/app/services/interview_service.py`
  - `frontend/src/app/(company)/company/interviews/[id]/replay/page.tsx`
- Acceptance criteria:
  - recruiter can see stage labels and stage-specific evidence

### MS-020 Behavioral Interview Module

- Status: `todo`
- Priority: `P1`
- Goal: separate behavioral interview from generic final behavioral question coverage
- Main backend areas:
  - `backend/app/ai/interviewer.py`
  - `backend/app/ai/assessor.py`
- Acceptance criteria:
  - module runs 3-4 behavioral prompts
  - leadership / ownership / communication are scored through a dedicated rubric

### MS-021 Written Communication Task

- Status: `todo`
- Priority: `P1`
- Goal: add a short recruiter-visible writing task
- Main backend areas:
  - new task storage and scoring service
  - report schema updates
- Main frontend areas:
  - new candidate task page
  - report pages
- Acceptance criteria:
  - candidate submits written response
  - response is stored and scored
  - report shows clarity, structure, audience-awareness style metrics

### MS-022 Confidence And Evidence Presentation

- Status: `todo`
- Priority: `P1`
- Goal: expose already-stored confidence fields in the UI
- Main areas:
  - `frontend/src/app/(candidate)/candidate/reports/[id]/page.tsx`
  - `frontend/src/app/(company)/company/reports/[id]/page.tsx`
  - `frontend/src/lib/types.ts`
- Acceptance criteria:
  - overall confidence is visible
  - competency confidence is visible
  - evidence coverage and policy version can be inspected

### MS-023 Candidate Report Roadmap

- Status: `todo`
- Priority: `P1`
- Goal: add a candidate-facing development roadmap section to the final report
- Main areas:
  - `backend/app/ai/assessor.py`
  - `backend/app/schemas/report.py`
  - `frontend/src/app/(candidate)/candidate/reports/[id]/page.tsx`
  - `frontend/src/lib/types.ts`
- Acceptance criteria:
  - final report includes a concrete growth roadmap
  - roadmap ties strengths and weaknesses to next steps
  - roadmap is visible at least in the candidate report

### MS-024 Interview Structure V2

- Status: `todo`
- Priority: `P1`
- Goal: make interview order explicit: self-intro, resume follow-up, technical validation, soft-skill closing
- Main backend areas:
  - `backend/app/ai/interviewer.py`
  - `backend/app/ai/competencies.py`
  - `backend/app/services/interview_service.py`
- Acceptance criteria:
  - first question is a self-introduction / experience summary opener
  - early turns use resume-grounded follow-up
  - technical block is asked before behavioral closing
  - final block covers communication, leadership, stress handling, and collaboration where relevant

### MS-025 Admin LLM Controls

- Status: `todo`
- Priority: `P1`
- Goal: provide admin-facing controls for LLM/runtime configuration without code edits
- Main areas:
  - backend settings/config service
  - admin company/workspace settings UI
  - prompt/runtime configuration storage
- Acceptance criteria:
  - admins can select core provider/model settings
  - prompt or policy versions can be switched safely
  - retries, timeouts, and feature flags can be tuned through UI

## P2 Hands-On Expansion

### MS-030 SQL Sandbox MVP

- Status: `todo`
- Priority: `P2`
- Goal: real SQL task environment with sandbox execution
- Main backend areas:
  - new SQL execution service
  - sandbox connection layer
  - result validation logic
- Main frontend areas:
  - new SQL task page with editor
- Acceptance criteria:
  - candidate writes SQL in-browser
  - query executes against sandbox data
  - result correctness is validated

### MS-032 Coding Task Module MVP

- Status: `todo`
- Priority: `P2`
- Goal: add code-based technical assignments with solution capture and evaluation
- Recommended first cut:
  - take-home style coding prompt or in-browser coding task
  - recruiter-visible prompt, submission, and scored evidence
- Main backend areas:
  - new task/session storage
  - code submission evaluation service
  - report schema updates
- Main frontend areas:
  - candidate coding task page
  - recruiter report/review pages
- Acceptance criteria:
  - candidate receives a code task inside the assessment flow
  - code submission is stored with raw artifact and scoring summary
  - recruiter can inspect the prompt, solution, and evaluation notes

### MS-031 SQL Task Scoring

- Status: `todo`
- Priority: `P2`
- Goal: add readability, performance, and confidence scoring for SQL tasks
- Acceptance criteria:
  - correctness score exists
  - performance metrics exist
  - report links to final query and result evidence

### MS-040 Data Analysis Challenge

- Status: `todo`
- Priority: `P2`
- Goal: allow CSV-based analysis workflow
- Acceptance criteria:
  - dataset upload or preloaded dataset exists
  - candidate can submit findings
  - report captures insights and recommendations

### MS-050 DevOps Simulation MVP

- Status: `todo`
- Priority: `P2`
- Goal: first hands-on DevOps evidence path
- Recommended first cut:
  - scenario-based incident simulation before full IaC lab
- Acceptance criteria:
  - candidate can request logs/metrics
  - decisions and timeline are stored
  - recruiter sees remediation reasoning

### MS-052 Speech Proctoring Signals

- Status: `todo`
- Priority: `P2`
- Goal: extend proctoring with speech-based monitoring signals
- Main backend areas:
  - proctoring event normalization
  - interview/session behavioral signal storage
  - report timeline payload
- Main frontend areas:
  - candidate interview capture flow
  - company report / replay / proctoring timeline
- Acceptance criteria:
  - speech-related events can be captured and stored with consent-aware policy handling
  - recruiter sees speech-related signals alongside tab, paste, and face events
  - report can distinguish passive observation from hard risk flags

## P2 Soft-Skill Expansion

### MS-060 Leadership SJT

- Status: `todo`
- Priority: `P2`
- Goal: add structured scenario choices plus rationale scoring
- Acceptance criteria:
  - scenario bank exists
  - answer and explanation are stored
  - report shows outcome and rationale

### MS-061 Conflict / EQ SJT

- Status: `todo`
- Priority: `P2`
- Goal: add conflict-management and EQ scenario evidence
- Acceptance criteria:
  - scenario bank exists
  - report includes EQ-relevant evidence

## P3 Measurement Maturity

### MS-070 Role Fit Score

- Status: `todo`
- Priority: `P3`
- Goal: compute role-fit from configurable module and competency weights
- Acceptance criteria:
  - recruiter can view role-fit
  - score is traceable to underlying weights

### MS-071 Radar And Comparison V2

- Status: `todo`
- Priority: `P3`
- Goal: richer recruiter comparison
- Main frontend areas:
  - `frontend/src/app/(company)/company/dashboard/page.tsx`
- Acceptance criteria:
  - compare up to 5 candidates
  - radar or equivalent multidimensional compare is available

### MS-080 Psychometric Layer

- Status: `todo`
- Priority: `P3`
- Goal: introduce item-bank calibration and percentile logic
- Acceptance criteria:
  - item metadata exists
  - percentile output exists
  - confidence-band computation exists

### MS-090 Validation Toolkit

- Status: `todo`
- Priority: `P3`
- Goal: add expert review and validation support
- Acceptance criteria:
  - expert rescoring workflow exists
  - validation metrics can be computed offline

## Recommended Immediate Build Order

Start here:

1. `MS-001` Assessment Session Orchestrator
2. `MS-002` Module Result Persistence
3. `MS-003` Report UI V2 Shell
4. `MS-010` System Design Module MVP
5. `MS-022` Confidence And Evidence Presentation
6. `MS-024` Interview Structure V2
7. `MS-023` Candidate Report Roadmap
8. `MS-032` Coding Task Module MVP

Reason:

- this sequence uses the strongest existing code paths
- it unlocks future modules cleanly
- it produces recruiter-visible progress without requiring heavy infra work

## Suggested Owner Areas In Current Repo

Backend core:

- `backend/app/services/interview_service.py`
- `backend/app/ai/interviewer.py`
- `backend/app/ai/assessor.py`
- `backend/app/models/report.py`
- `backend/app/models/company_assessment.py`
- `backend/alembic/versions/`

Frontend core:

- `frontend/src/lib/types.ts`
- `frontend/src/lib/api.ts`
- `frontend/src/app/(candidate)/candidate/interview/`
- `frontend/src/app/(candidate)/candidate/reports/`
- `frontend/src/app/(company)/company/reports/`
- `frontend/src/app/(company)/company/dashboard/`
