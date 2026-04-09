# MindScope Roadmap

## Goal

Evolve the current interview-centric platform into a modular skills assessment platform that supports:

- structured hard-skill modules
- structured soft-skill modules
- richer recruiter-facing scorecards
- stronger measurement and validation

## Existing Platform Assets To Reuse

- adaptive interview runtime
- role-specific competency matrices
- structured scoring and report generation
- replay and evidence model
- company assessment campaigns
- baseline proctoring pipeline
- candidate/company workspaces

These assets should be extended, not replaced.

## Delivery Principles

- keep the current architecture: thin routers, service-driven backend, shared frontend API layer
- add modules incrementally instead of attempting a full PRD rewrite in one release
- reuse `interviews`, `assessment_reports`, `company_assessments`, and company workspace flows where possible
- avoid introducing psychometrics before module-level evidence capture exists

## Recommended Phases

## Phase 0: Platform Preparation

Objective:
Create the minimum shared foundation for multi-module assessments.

Scope:

- add assessment-session orchestration beyond a single interview flow
- define module types and module results
- extend report schema to support module-level evidence
- add recruiter-facing navigation for module-aware reports

Exit criteria:

- one assessment can contain multiple modules
- module progress and outcomes are persisted
- report payload can show module sections

## Phase 1: First Recruiter-Visible Expansion

Objective:
Ship the first meaningful PRD-aligned improvements using the current architecture.

Scope:

- system design module MVP
- behavioral interview module MVP
- written communication task MVP
- richer company report UI
- candidate-facing report roadmap block
- interview structure V2:
  - opening self-introduction + experience summary
  - resume-driven follow-up
  - technical skill validation block
  - soft-skill closing block
- admin controls for LLM providers, prompts, retries, and feature flags

Exit criteria:

- recruiter sees more than a transcript-based interview score
- system design has a dedicated flow
- writing output is stored and scored
- report UI exposes module sections, confidence, and evidence more clearly
- candidate report includes a concrete development roadmap
- interview order is explicit and role-consistent instead of purely adaptive from the first turn
- admins can tune core LLM/runtime settings without code edits

## Phase 2: Hands-On Skill Modules

Objective:
Add real task environments for technical evaluation.

Scope:

- coding task / code review module MVP
- SQL sandbox
- data analysis challenge
- DevOps simulation or IaC lab
- proctoring expansion with speech monitoring / speech-anomaly signals

Exit criteria:

- candidates complete at least one real task in-browser
- outputs are automatically persisted and scored
- recruiter can inspect raw task evidence
- platform supports at least one code-based technical assignment
- proctoring can correlate suspicious speech patterns with other session signals

## Phase 3: Judgment And Scenario Modules

Objective:
Broaden soft-skill measurement beyond transcript inference.

Scope:

- SJT for leadership
- SJT for conflict / EQ
- scenario explanation scoring

Exit criteria:

- soft-skill evidence is multi-source, not only interview-derived
- reports can cite scenario decisions and rationale

## Phase 4: Measurement Maturity

Objective:
Add the psychometric and validation layer from the PRD.

Scope:

- item bank and calibration metadata
- percentile and confidence-band computation
- role-fit scoring
- validation dashboards and expert-review workflows

Exit criteria:

- scores are population-aware
- recruiter scorecards expose percentile / confidence / role fit
- validation process exists outside ad hoc manual review

## Recommended First Engineering Slice

Build this first:

1. Assessment session orchestration
2. System design module MVP
3. Recruiter report section for module evidence

Reason:

- it uses the strongest existing assets
- it aligns with the PRD's most visible gap
- it avoids the heavier infra cost of SQL and DevOps labs
- it creates the module framework needed by later work

## System Design MVP Definition

Target scope:

- dedicated module type: `system_design`
- prompt-based scenario selection from a curated task pool
- structured stage flow:
  - requirements
  - high-level design
  - trade-offs
- textual architecture notes first
- optional whiteboard support as a second step, not in MVP-0

Recommended MVP evidence:

- candidate transcript
- stage-by-stage prompts
- structured AI scoring rubric
- replay grouped by stage

Recommended non-goals for MVP:

- full Excalidraw embed
- vision scoring
- multi-image replay snapshots
- IRT calibration

## Risks

- if module orchestration is skipped, later modules will be bolted onto the interview flow and become hard to maintain
- if psychometrics start before evidence capture stabilizes, the scoring layer will be fragile
- if hands-on labs are attempted before Phase 0, product complexity will spike too early
- if speech monitoring is added without clear consent/privacy handling, it will create legal and product risk
- if interview structure stays fully implicit, recruiter expectations and candidate experience will remain inconsistent
