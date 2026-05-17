# Interview Engine v2

## Purpose
Interview Engine v2 should run as a live technical interview, not as a linear questionnaire. The system must adapt to answer quality, probe real work evidence, avoid conversational loops, and produce reliable assessment signals.

## Why v1 degrades quality
- Python decision logic is over-constraining the flow and forcing deterministic paths.
- LLM is mostly treated as a text generator, not an interviewing strategist.
- Resume anchors can hijack interview focus away from role competency map.
- Follow-up flow can loop on generic clarifications.
- Questions can become generic and detached from real production cases.

## Design goals
- Keep Python in control of safety, state, persistence, and deterministic guardrails.
- Give LLM controlled strategic autonomy for next-step selection and question framing.
- Make competency evidence the primary interview signal.
- Make resume personalization secondary and non-dominant.
- Prevent loops, repetition, and low-signal spirals.

## Non-goals
- No full autonomous interviewer without guardrails.
- No direct final hiring decision from a single low-confidence interview.
- No role-specific hardcoding in controller logic that bypasses config.

---

## 1) Architecture v2

## High-level split
- Python layer: state manager, guardrails, persistence, policy enforcement, retries, and hard stops.
- LLM layer: interviewer strategist that chooses interview action and composes next question.
- Assessor layer: post-interview evidence-based scoring and report generation.

## Components
- `InterviewStateManager` (Python)
  - Owns state lifecycle and transitions.
  - Validates phase gates and anti-loop rules.
  - Stores `InterviewState` after each turn.

- `InterviewStrategist` (LLM contract)
  - Input: condensed state + last answer evaluation + role map + allowed actions.
  - Output: `QuestionDecision` (action + reason + expected_signal + question_text).
  - Must operate inside allowed action set from Python guardrails.

- `QuestionGuardrails` (Python)
  - Dedup/repeat detection.
  - Phase progression constraints.
  - Scenario chain constraints.
  - Clarification and fallback policies.

- `RuntimeAnswerEvaluator` (Python/LLM hybrid optional)
  - Runs after each candidate answer.
  - Produces quality/depth/clarity signal and follow-up intent.

- `EvidenceAssessor` (LLM + deterministic scoring caps)
  - Consumes transcript + runtime evaluations + competency coverage.
  - Produces confidence-aware verdict with guardrails.

## Request cycle
1. Candidate answer received.
2. `RuntimeAnswerEvaluator` evaluates answer.
3. `InterviewStateManager` updates state and computes allowed actions.
4. `InterviewStrategist` returns `QuestionDecision`.
5. `QuestionGuardrails` validates decision; rewrites/fallbacks if needed.
6. Next interviewer question persisted and returned.
7. On close action: `EvidenceAssessor` builds report.

---

## 2) InterviewState v2

```json
{
  "phase": "intro | resume_deep_dive | technical_case | technical_deep_dive | behavioral | closing",
  "role": "qa_engineer",
  "language": "ru",
  "current_competency": "Test Strategy & Planning",
  "current_scenario_id": "qa_payment_failed_money_deducted",
  "scenario_step": 2,
  "attempts_on_current_step": 1,
  "confusion_count": 0,
  "repeated_question_count": 0,
  "covered_competencies": ["Technical Communication", "Test Strategy & Planning"],
  "validated_competencies": ["Test Strategy & Planning"],
  "weak_competencies": ["Test Automation"],
  "last_answer_evaluation": {
    "quality": "medium",
    "has_example": true,
    "has_technical_detail": false,
    "depth_score": 4.5,
    "needs_followup": true,
    "followup_type": "deep_dive",
    "interviewer_failure": false
  },
  "next_action": "continue_scenario"
}
```

## State semantics
- `phase`: global interview stage. Phase transitions are explicit and guarded.
- `current_competency`: active competency target for scoring and question quality checks.
- `current_scenario_id/scenario_step`: where candidate is inside a work-case chain.
- `attempts_on_current_step`: max retries before forced switch.
- `confusion_count`: increment on "не понял" / equivalent confusion markers.
- `repeated_question_count`: increment when guardrail catches semantic duplicate.
- `covered_competencies`: competencies touched by at least one scored question.
- `validated_competencies`: competencies with strong enough evidence.
- `weak_competencies`: competencies with low or inconsistent signal.
- `next_action`: chosen strategic action from last decision cycle.

---

## 3) QuestionDecision v2

```json
{
  "action": "ask_new_topic | follow_up | simplify | switch_topic | start_scenario | continue_scenario | close_interview",
  "question_text": "Опишите, как бы вы воспроизвели дефект: платеж не прошел, но деньги списались?",
  "target_competency": "Root Cause Analysis",
  "scenario_id": "qa_payment_failed_money_deducted",
  "scenario_step": 1,
  "difficulty_tier": 3,
  "reason": "last answer had no concrete reproduction steps",
  "expected_signal": "candidate provides reproducible steps + trace artifacts"
}
```

## Decision constraints
- Action must be in Python-provided `allowed_actions`.
- `question_text` required for all actions except `close_interview`.
- `scenario_step` required for `start_scenario` and `continue_scenario`.
- `target_competency` must exist in role competency map.
- `reason` must be explicit and machine-auditable.

---

## 4) Interview principle: role-first, resume-second

## Rule
Role competency map defines interview backbone. Resume is only personalization context.

## Enforcement
- Every scored question must map to a role competency ID.
- Resume anchors cannot change phase order or replace mandatory role competencies.
- Resume anchors are ignored if they are low-signal/non-experience metadata.
- If resume contradicts role path, system keeps role path and asks bridging question.

---

## 5) Anti-loop policy

## Mandatory rules
- No repeated question (semantic dedup by token overlap + embedding similarity threshold).
- If candidate says "не понял" (or equivalent):
  - action must become `simplify`.
  - next question must include concrete scenario/context.
- Maximum 1 generic follow-up on same step.
- After 2 weak answers on same competency:
  - force `start_scenario` or `switch_topic` to concrete case.
- Maximum attempts on one scenario step: 2.
- If repeated-question guard trips twice in same phase:
  - force phase-level reset to new competency or close.

## Loop break matrix
- weak + no example -> follow_up (specific ask)
- weak + repeated twice -> start_scenario
- confusion_count >= 1 -> simplify with example
- confusion_count >= 2 -> switch_topic (same phase)
- repeated_question_count >= 2 -> guardrail rewrite + scenario jump

---

## 6) Role competency map and scenario examples

## Backend Engineer
### Key competency areas
- System Design & Architecture
- API Design & Contracts
- Database Design & Query Optimization
- Reliability, Error Handling, Observability
- Security and Access Control
- Performance and Scalability
- Collaboration & Code Review

### Scenario examples
- High-load checkout API starts timing out after release.
- Partial failure between service and DB causes duplicate writes.
- JWT auth bypass attempt during traffic spike.

## Frontend Engineer
### Key competency areas
- UI Architecture and State Management
- Performance and Rendering Optimization
- Accessibility (a11y)
- API Integration and Error UX
- Testing Strategy (unit/integration/e2e)
- Design System Consistency
- Collaboration with Product/Design

### Scenario examples
- Critical UI freeze on low-end mobile devices.
- Accessibility issue blocks keyboard-only users in checkout.
- Race condition between optimistic UI and backend rollback.

## QA Engineer
### Key competency areas
- Test Strategy & Risk Prioritization
- Manual and Exploratory Testing
- API and Integration Testing
- Root Cause Analysis and Defect Isolation
- Test Automation Strategy
- CI/CD Quality Gates
- Quality Advocacy and Cross-team Communication

### Scenario examples
- Payment failed but money deducted.
- Critical release under deadline with regression risk.
- Intermittent API failure with inconsistent status codes.

## DevOps Engineer
### Key competency areas
- CI/CD Pipeline Design
- Infrastructure as Code
- Observability and Incident Response
- Reliability Engineering (SLO/SLI/Error Budget)
- Security and Secrets Management
- Kubernetes/Container Operations
- Cost and Capacity Management

### Scenario examples
- Deployment causes cascading failures across services.
- Alert storm with high noise-to-signal in monitoring.
- Cluster resource exhaustion under sudden 3x load.

## Data Scientist
### Key competency areas
- Problem Framing and Metric Selection
- Data Quality and Feature Engineering
- Model Design and Validation
- Experimentation (A/B, causal reasoning)
- Productionization and Monitoring
- Explainability and Communication
- Responsible AI / Bias Awareness

### Scenario examples
- Model performs well offline but degrades in production.
- Data drift causes sudden drop in conversion predictions.
- Business asks for metric uplift that conflicts with fairness target.

## Product Manager
### Key competency areas
- Problem Discovery and Opportunity Sizing
- Prioritization and Roadmap Trade-offs
- Experimentation and KPI Design
- Delivery Coordination and Risk Management
- Stakeholder Communication
- Product Analytics and Decision Quality
- Ownership and Post-release Learning

### Scenario examples
- Key feature misses KPI after launch.
- Conflicting stakeholder priorities before roadmap freeze.
- Critical user journey drop-off spikes after release.

## Mobile Developer
### Key competency areas
- Mobile Architecture and State Handling
- Performance and Battery/Memory Efficiency
- Networking and Offline-first Design
- Platform-specific UX and Native Constraints
- Mobile Testing and Release Quality
- Security on Device and Transport
- Crash/Observability and Incident Response

### Scenario examples
- Crash spike appears only on one OS version.
- Offline sync conflict corrupts user data.
- Push-notification flow works on Android but fails on iOS.

## UX/UI Designer
### Key competency areas
- Problem Discovery and User Research
- Information Architecture and User Flows
- Interaction Design and Visual Hierarchy
- Usability Testing and Iteration
- Accessibility and Inclusive Design
- Collaboration with Product/Engineering
- Outcome Measurement and Design Rationale

### Scenario examples
- Conversion drop after UI redesign despite positive subjective feedback.
- Ambiguous onboarding flow causes high user churn.
- Design handoff mismatch leads to implementation regressions.

---

## 7) Phase policy

## Target phase progression
- `intro` -> `resume_deep_dive` -> `technical_case` -> `technical_deep_dive` -> `behavioral` -> `closing`

## Minimum technical evidence gate
- Cannot enter `behavioral` unless:
  - at least 60% required technical competencies are covered, and
  - at least 2 validated technical competencies, and
  - minimum scored technical questions threshold met.

## QA-specific minimums
- Minimum 10 scored questions.
- Minimum 6 case-based technical questions.
- At least 2 completed scenario chains.

---

## 8) Confidence-aware verdict policy

- `confidence < 40` -> verdict = `insufficient_data`
- `40 <= confidence < 70` -> verdict = `needs_human_review`
- `confidence >= 70` -> normal verdict policy

## Confidence factors
- Number of validated competencies
- Number of strong answers
- Scenario depth completion (steps completed with evidence)
- Consistency across answers

## Hard rule
No fallback score inflation (no synthetic default like 6.0 without evidence).

---

## 9) Migration plan (no breaking rewrite)

## Phase M0: Feature flag + observability
- Add `INTERVIEW_ENGINE_V2_ENABLED` flag.
- Add runtime logging for state transitions and decisions.
- Add metrics:
  - loop_rate
  - repeated_question_rate
  - scenario_completion_rate
  - technical_coverage_before_behavioral

## Phase M1: State contract rollout
- Introduce `InterviewState v2` fields in persistence.
- Backward-compatible adapters from v1 state.
- No behavior change yet.

## Phase M2: Decision contract rollout
- Introduce `QuestionDecision v2` schema and validator.
- Keep current selector but emit decisions in new format.
- Log validation failures and fallback causes.

## Phase M3: LLM strategist mode
- Move next-action selection to LLM with allowed-action constraints.
- Python still owns guardrails and final accept/rewrite.
- Keep deterministic fallback if strategist fails.

## Phase M4: Anti-loop guardrail hardening
- Enable semantic dedup gate.
- Enforce confusion/simplify rules.
- Enforce max generic follow-up and scenario forcing rules.

## Phase M5: Role-first policy enforcement
- Ensure competency map drives all phase progression.
- Downgrade resume anchors to personalization-only context.
- Reject decisions that violate competency path.

## Phase M6: Assessor alignment
- Consume runtime evidence directly.
- Apply confidence verdict guard.
- Remove all non-evidence score fallbacks.

## Phase M7: Shadow eval and rollout
- Run v1 and v2 in shadow mode on same interviews.
- Compare:
  - perceived interview quality
  - competency coverage quality
  - confidence calibration
  - report usefulness
- Gradual traffic ramp: 5% -> 20% -> 50% -> 100%.

---

## 10) Risks and mitigations

- Risk: LLM chooses unstable action patterns.
  - Mitigation: strict allowed-actions list, decision validator, deterministic fallback.

- Risk: More tokens and latency.
  - Mitigation: compact state summary, bounded transcript window, cached role maps.

- Risk: Overfitting to scripted scenario chains.
  - Mitigation: mix scenario + free technical deep dive and adaptive switch-topic paths.

- Risk: Regression in report consistency.
  - Mitigation: assessor consumes structured runtime evidence from v2 state.

---

## 11) Acceptance criteria for v2 rollout

- No repeated semantic questions within same competency step.
- Candidate confusion always triggers contextual simplify question.
- Behavioral phase blocked until technical evidence threshold is met.
- QA interviews satisfy:
  - >=10 scored questions
  - >=6 case-based technical questions
  - >=2 scenario chains with step progression
- Confidence guard correctly maps low-confidence interviews to non-hard verdicts.

