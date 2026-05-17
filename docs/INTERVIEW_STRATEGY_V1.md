# Research-Based Interview Strategy for IT Roles (v1)

Updated: 2026-04-28

## 1) What research says we should enforce

### Core design rules
1. Use structured interviews, not free-form conversations.
2. Ask the same core question set in the same order per role.
3. Score answers with the same rubric for all candidates.
4. Combine methods (interview + job-knowledge + work-sample/case), not interview-only.
5. Keep questions job-related and avoid non-job personal topics.

### Why
- Structured interviews improve consistency and legal defensibility, and reduce subjectivity.
- Behavioral and situational formats both matter and can be mixed.
- Strong selection systems use multiple complementary methods with incremental validity.

## 2) Recommended base flow for all IT interviews

Use 5 blocks, always in this order:

1. **Calibration intro (1 question)**
   - Goal: establish communication baseline and role-context.
2. **Experience deep-dive (2 questions)**
   - Goal: verify resume claims with concrete project evidence.
3. **Role-core technical block (3-5 questions)**
   - Goal: assess must-have competencies for the selected role.
4. **Problem-solving / trade-off block (1-2 questions)**
   - Goal: decision quality under constraints.
5. **Behavioral closing (1 question)**
   - Goal: collaboration, ownership, pressure behavior.

Target length:
- Initial plan: 8-12 scored questions (not counting tiny clarifying probes).
- Probes allowed, but do not replace main scored questions.

## 3) Role-specific strategy and question order

The platform currently supports:
- backend_engineer
- frontend_engineer
- qa_engineer
- devops_engineer
- data_scientist
- product_manager
- mobile_engineer
- designer (UX/UI)

---

### A) Backend Engineer
Order:
1. Recent service ownership
2. API design decision
3. DB schema/index/performance
4. Reliability/failures/retries
5. Security/auth/validation
6. Debugging incident RCA
7. Trade-off case
8. Behavioral closing

Sample scored questions:
- "Расскажите про сервис, за который вы отвечали end-to-end: нагрузка, SLA, ваша зона ответственности."
- "Как проектировали versioning и backward compatibility в API?"
- "Как выбирали индексы и проверяли план запроса на production-данных?"
- "Какой инцидент был самым критичным и как вы нашли корневую причину?"

### B) Frontend Engineer
Order:
1. Product surface ownership
2. Component architecture/state
3. Performance (CWV/render/bundle)
4. Accessibility
5. Testing strategy (unit/integration/e2e)
6. Debugging cross-browser/user issues
7. Trade-off case
8. Behavioral closing

Sample:
- "Как устроили state management и почему выбрали именно этот подход?"
- "Какие конкретные шаги дали прирост LCP/INP?"
- "Как проверяли доступность и какие реальные дефекты нашли?"

### C) QA Engineer
Order:
1. Quality ownership context
2. Test strategy and risk model
3. Automation scope and ROI
4. API and integration testing
5. Performance/reliability testing
6. Defect triage + RCA example
7. CI/CD quality gate
8. Behavioral closing (quality advocacy under pressure)

Sample:
- "Как вы строили тест-стратегию для нового релиза: что шло в smoke, regression, exploratory?"
- "Что вы принципиально не автоматизировали и почему?"
- "Разберите один баг от сигнала до подтвержденного root cause."

### D) DevOps Engineer
Order:
1. Platform/on-call ownership
2. CI/CD design and rollback
3. Observability and SLOs
4. Incident response and postmortem
5. Infra as code/security controls
6. Throughput vs stability trade-off
7. Cost/performance decision
8. Behavioral closing

Sample:
- "Как вы определяли SLI/SLO и когда меняли алерты?"
- "Расскажите про incident, где пришлось выбирать между speed и stability."

### E) Data Scientist
Order:
1. Problem framing and business metric
2. Data prep/feature pipeline
3. Modeling and validation
4. Experimentation/causal or A/B
5. Productionization/monitoring drift
6. Model failure/RCA case
7. Trade-off (accuracy/latency/cost/explainability)
8. Behavioral closing

Sample:
- "Как переводили бизнес-вопрос в ML-задачу и метрику успеха?"
- "Как отслеживали drift и какие действия делали при деградации?"

### F) Product Manager
Order:
1. Product ownership scope
2. Problem discovery + prioritization
3. PRD/requirements quality
4. Metrics and experiment interpretation
5. Stakeholder conflict + decision
6. Delivery under constraints
7. Trade-off case
8. Behavioral closing

Sample:
- "Как принимали решение по приоритетам, когда инженерные и бизнес-цели конфликтовали?"
- "Какая метрика изменила ваш roadmap и почему?"

### G) Mobile Engineer
Order:
1. App module ownership
2. Architecture and state/offline strategy
3. Performance/battery/crash control
4. Networking/sync/error handling
5. Mobile testing/release pipeline
6. Platform-specific debugging
7. Trade-off case
8. Behavioral closing

Sample:
- "Как решали offline-first синхронизацию и конфликты?"
- "Какие действия дали наибольший вклад в crash-rate reduction?"

### H) UX/UI Designer
Order:
1. UX context and outcomes
2. Research method and evidence
3. Information architecture / flow decision
4. Interaction/visual design rationale
5. Handoff and collaboration with dev
6. Metrics after launch
7. Trade-off (business vs user) case
8. Behavioral closing

Sample:
- "Какое исследование повлияло на ключевой дизайн-выбор?"
- "Как измеряли эффект после релиза (показатели, период, выводы)?"

## 4) Replace manual Junior/Middle/Senior selection with adaptive leveling

## Proposed approach
Do **not** ask candidate to pick level at start.

### 4.1 Runtime adaptation
- Start from neutral difficulty (L2/L3).
- Increase difficulty after 2 strong answers in a row.
- Decrease difficulty after 2 low-signal answers in a row.
- Keep role-specific trajectory (do not switch role context mid-interview).

### 4.2 Final level output (dual format)
- Numeric: `proficiency_level` (1..7)
- Human label: `Junior 1..5`, `Middle`, `Strong Middle`, `Senior`, `Strong Senior`

Example mapping:
- 1.0-1.9: Junior 1
- 2.0-2.4: Junior 2
- 2.5-2.9: Junior 3
- 3.0-3.4: Junior 4
- 3.5-3.9: Junior 5
- 4.0-4.7: Middle
- 4.8-5.3: Strong Middle
- 5.4-6.1: Senior
- 6.2-7.0: Strong Senior

### 4.3 Scoring components
- Technical depth
- Problem solving
- Communication
- Behavioral/ownership
- Role-fit evidence quality

Each component must be backed by quoted evidence from candidate answers in report JSON.

## 5) Guardrails to prevent low-quality interview behavior

1. Resume anchors must come only from validated experience statements (already partially implemented).
2. No personal data lines (location, age, family, etc.) in generated questions.
3. Main question must be complete sentence before send; avoid over-aggressive truncation.
4. Clarifying probes should be short and non-repetitive.
5. If candidate explicitly says "такого опыта не было", switch to adjacent competency scenario (not repeated pressure on same false anchor).

## 6) Suggested implementation steps

1. Build role-specific main-question banks from the sequences above.
2. Add adaptive-difficulty controller (difficulty state in interview_state).
3. Add final level-calibration module (`proficiency_level` + label).
4. Add report section: "Why this level" with evidence snippets by competency.
5. Add regression tests:
   - role-alignment test per role
   - progress consistency (`question_count` vs `max_questions`)
   - no-truncated-main-question test
   - "no fake resume anchor" tests

## Sources

- OPM Structured Interviews: https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/
- OPM Structured Interview Guide (PDF): https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/guide.pdf
- OPM Designing an Assessment Strategy: https://www.opm.gov/policy-data-oversight/assessment-and-selection/assessment-strategy/
- EEOC Selection Procedures: https://www.eeoc.gov/laws/guidance/employment-tests-and-selection-procedures
- EEOC Interview best-practice notes: https://www.eeoc.gov/best-practices-private-sector-employers
- ScienceDirect (question-type validity context): https://www.sciencedirect.com/science/article/abs/pii/S0148296319301985
- SFIA levels framework overview: https://sfia-online.org/en/about-sfia/how-sfia-works
- NIST NICE proficiency scale report (PDF): https://www.nist.gov/system/files/documents/2023/10/05/NIST%20Measuring%20Cybersecurity%20Workforce%20Capabilities%207-25-22.pdf
- DORA 2024 report: https://dora.dev/research/2024/dora-report/
- NN/g UX careers report (PDF): https://media.nngroup.com/media/reports/free/UserExperienceCareers_2nd_Edition.pdf?ref=uxdesignweekly
- ISTQB certification + syllabus hub: https://istqb.org/certifications/certified-tester-foundation-level-agile-tester-ctfl-at/
