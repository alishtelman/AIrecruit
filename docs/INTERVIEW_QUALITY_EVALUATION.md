# Interview Quality Evaluation Framework (Engine v2)

## Goal
Create a repeatable live-smoke evaluation loop for Interview Engine v2 so quality is measured by evidence, not by subjective impressions.

## Scope
- Roles for smoke set: `qa_engineer`, `backend_engineer`, `frontend_engineer`, `devops_engineer`
- Each smoke: 10-15 conversational turns
- Include mixed candidate behavior:
  - normal answers
  - weak/general answers
  - clarification/meta questions
  - confusion moments

## Metrics (1-10)
Use integer scores unless strong reason for half-step.

### 1) `conversational_realism`
How natural the dialogue feels as a real interviewer conversation.
- 1-3: robotic script
- 4-6: mixed
- 7-8: mostly natural
- 9-10: highly human-like

### 2) `adaptation_quality`
How well interviewer adapts to candidate intent/quality.
- Handles confusion, meta, weak answers, strong answers differently.

### 3) `pressure_quality`
How useful follow-up pressure is.
- Should ask concrete narrowing questions, not generic repeats.

### 4) `technical_depth`
How deeply technical signal is probed.
- Includes edge cases, trade-offs, debugging reasoning.

### 5) `repetition_level` (lower is better)
How repetitive question intent/phrasing is.
- 1-2: almost no repeats
- 8-10: heavy repetitive loop

### 6) `phase_pacing`
How well interview pacing moves through phases.
- Resume warm-up should not overstay.
- Technical probing should dominate middle.

### 7) `resume_usage_quality`
Resume used for personalization, not as wrong primary focus.

### 8) `human_likeness`
Overall interviewer behavior quality (tone, flow, reaction, control).

## Operational Metrics (from runtime/trace)
- `total_turns`
- `scored_questions`
- `strategist_success_count`
- `fallback_count`
- `repeated_question_count`
- `resume_phase_turns`
- `technical_case_turns`
- `pressure_followup_count`
- `clarification_count`

## Target Thresholds
- `strategist_success_count > 80%`
- `fallback_count == 0`
- `repeated_question_count <= 1`
- `technical_case_turns > resume_phase_turns`
- `conversational_realism >= 8`
- `human_likeness >= 8`

## Per-Smoke Review Template

### Interview Metadata
- Role:
- Engine version:
- Provider/model:
- Date/time:

### Transcript Summary
- 5-10 bullet summary of flow:
  - warm-up / resume deep-dive
  - technical cases
  - behavioral/closing
  - notable confusion/meta moments

### Metric Scores
- conversational_realism:
- adaptation_quality:
- pressure_quality:
- technical_depth:
- repetition_level:
- phase_pacing:
- resume_usage_quality:
- human_likeness:

### Runtime Metrics
- total_turns:
- scored_questions:
- strategist_success_count:
- fallback_count:
- repeated_question_count:
- resume_phase_turns:
- technical_case_turns:
- pressure_followup_count:
- clarification_count:

### Honest Self-Review (Mandatory)
- Where interview still feels robotic:
- Weak follow-up points:
- Premature topic switch points:
- Candidate confusion handling failures:
- Technical probing gaps:
- Concrete evidence from transcript/trace:

### Actionable Improvements
- Max 3 targeted fixes only.
- No large guardrail additions without trace evidence.

## Execution Loop
1. Run live-smoke.
2. Export transcript summary + debug trace + runtime metrics.
3. Score all 8 quality metrics.
4. Write honest self-review.
5. Propose only evidence-backed targeted improvements.
