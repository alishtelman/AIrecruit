"""
Role-specific competency matrices for scientific interview assessment.

Each role has 8-10 competencies across 5 categories, with weights summing to 1.0.
Categories:
  - technical_core: core technical skills for the role
  - technical_breadth: adjacent technical knowledge
  - problem_solving: analytical thinking, debugging, system design approach
  - communication: clarity, structure, ability to explain complex topics
  - behavioral: teamwork, leadership, conflict resolution, growth mindset

Scoring rubric (behavioral anchors):
  1-2: No knowledge or completely wrong understanding
  3-4: Surface-level, textbook answers without practical experience
  5-6: Working knowledge, can describe basic usage but limited depth
  7-8: Strong practical experience, can discuss trade-offs and edge cases
  9-10: Expert level, demonstrates deep insight and original thinking
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Competency:
    name: str
    category: str  # technical_core | technical_breadth | problem_solving | communication | behavioral
    weight: float
    description: str


CATEGORIES = [
    "technical_core",
    "technical_breadth",
    "problem_solving",
    "communication",
    "behavioral",
]

SCORING_RUBRIC = {
    (1, 2): "No knowledge or completely wrong understanding",
    (3, 4): "Surface-level, textbook answers without practical experience",
    (5, 6): "Working knowledge, can describe basic usage but limited depth",
    (7, 8): "Strong practical experience, can discuss trade-offs and edge cases",
    (9, 10): "Expert level, demonstrates deep insight and original thinking",
}

# ---------------------------------------------------------------------------
# Role competency matrices
# ---------------------------------------------------------------------------

ROLE_COMPETENCIES: dict[str, list[Competency]] = {
    "backend_engineer": [
        Competency("System Design & Architecture", "technical_core", 0.15,
                    "Ability to design scalable systems, choose appropriate patterns, and reason about trade-offs"),
        Competency("Database Design & Optimization", "technical_core", 0.12,
                    "Schema design, query optimization, indexing strategies, replication and sharding"),
        Competency("API Design & Protocols", "technical_core", 0.12,
                    "REST/gRPC API design, versioning, error handling, documentation"),
        Competency("Programming Fundamentals", "technical_core", 0.10,
                    "Algorithms, data structures, language-specific idioms, code quality"),
        Competency("DevOps & Infrastructure", "technical_breadth", 0.08,
                    "CI/CD, containers, cloud services, deployment strategies"),
        Competency("Security & Error Handling", "technical_breadth", 0.08,
                    "Authentication, authorization, input validation, resilience patterns"),
        Competency("Debugging & Problem Decomposition", "problem_solving", 0.10,
                    "Systematic debugging, root cause analysis, breaking down complex problems"),
        Competency("Technical Communication", "communication", 0.10,
                    "Explaining technical decisions, documenting, discussing trade-offs clearly"),
        Competency("Collaboration & Code Review", "behavioral", 0.08,
                    "Teamwork, code review practices, knowledge sharing, mentoring"),
        Competency("Ownership & Growth Mindset", "behavioral", 0.07,
                    "Taking responsibility, learning from failures, continuous improvement"),
    ],
    "frontend_engineer": [
        Competency("UI Framework Mastery", "technical_core", 0.15,
                    "Deep knowledge of React/Vue/Angular, component architecture, state management"),
        Competency("Web Performance Optimization", "technical_core", 0.12,
                    "Bundle optimization, rendering strategies (SSR/SSG/CSR), lazy loading, Core Web Vitals"),
        Competency("CSS & Responsive Design", "technical_core", 0.10,
                    "Layout systems, responsive design, CSS-in-JS, design system implementation"),
        Competency("JavaScript/TypeScript Fundamentals", "technical_core", 0.12,
                    "Language mastery, async patterns, type system, ES modules"),
        Competency("Accessibility & Standards", "technical_breadth", 0.08,
                    "WCAG compliance, semantic HTML, ARIA, screen reader testing"),
        Competency("Testing & Quality", "technical_breadth", 0.08,
                    "Unit/integration/E2E testing, visual regression, testing strategies"),
        Competency("Debugging & Problem Decomposition", "problem_solving", 0.10,
                    "Browser devtools mastery, performance profiling, systematic debugging"),
        Competency("Technical Communication", "communication", 0.10,
                    "Explaining UI/UX decisions, documenting components, design discussions"),
        Competency("Collaboration & Design Partnership", "behavioral", 0.08,
                    "Working with designers, code review, cross-functional teamwork"),
        Competency("Ownership & Growth Mindset", "behavioral", 0.07,
                    "Staying current with ecosystem, learning from user feedback, initiative"),
    ],
    "qa_engineer": [
        Competency("Test Strategy & Planning", "technical_core", 0.15,
                    "Test plan design, risk-based testing, coverage analysis, test pyramid"),
        Competency("Test Automation", "technical_core", 0.14,
                    "Automation frameworks, CI integration, maintainable test suites, page objects"),
        Competency("Manual & Exploratory Testing", "technical_core", 0.10,
                    "Exploratory testing techniques, edge case discovery, heuristic-based testing"),
        Competency("API & Performance Testing", "technical_core", 0.10,
                    "API testing tools, load testing, performance benchmarking, bottleneck analysis"),
        Competency("DevOps & CI/CD Integration", "technical_breadth", 0.08,
                    "Pipeline integration, test environments, containerized testing"),
        Competency("Domain & Product Understanding", "technical_breadth", 0.08,
                    "Understanding requirements, user stories, acceptance criteria translation"),
        Competency("Root Cause Analysis", "problem_solving", 0.10,
                    "Bug investigation, reproduction steps, systematic defect analysis"),
        Competency("Technical Communication", "communication", 0.10,
                    "Bug reports, test documentation, stakeholder communication"),
        Competency("Collaboration & Advocacy", "behavioral", 0.08,
                    "Working with developers, quality advocacy, constructive feedback"),
        Competency("Ownership & Growth Mindset", "behavioral", 0.07,
                    "Process improvement, learning new tools, quality culture building"),
    ],
    "devops_engineer": [
        Competency("CI/CD Pipeline Design", "technical_core", 0.14,
                    "Pipeline architecture, build optimization, deployment strategies, GitOps"),
        Competency("Container Orchestration", "technical_core", 0.13,
                    "Kubernetes/Docker, service mesh, scaling, resource management"),
        Competency("Cloud Infrastructure", "technical_core", 0.12,
                    "AWS/GCP/Azure services, IaC (Terraform/Pulumi), networking, cost optimization"),
        Competency("Monitoring & Observability", "technical_core", 0.10,
                    "Metrics, logging, tracing, alerting, SLOs/SLIs, incident response dashboards"),
        Competency("Security & Compliance", "technical_breadth", 0.08,
                    "Secret management, network security, compliance automation, vulnerability scanning"),
        Competency("Scripting & Automation", "technical_breadth", 0.08,
                    "Shell scripting, Python automation, configuration management"),
        Competency("Incident Response & Troubleshooting", "problem_solving", 0.10,
                    "Production debugging, postmortem analysis, disaster recovery planning"),
        Competency("Technical Communication", "communication", 0.10,
                    "Runbooks, architecture docs, cross-team communication during incidents"),
        Competency("Collaboration & On-Call Culture", "behavioral", 0.08,
                    "Team coordination, knowledge sharing, on-call practices, blameless culture"),
        Competency("Ownership & Growth Mindset", "behavioral", 0.07,
                    "Reliability improvement, learning from incidents, proactive optimization"),
    ],
    "data_scientist": [
        Competency("ML Modeling & Algorithms", "technical_core", 0.15,
                    "Model selection, training, evaluation, hyperparameter tuning, deep learning"),
        Competency("Data Processing & Feature Engineering", "technical_core", 0.12,
                    "Data cleaning, feature extraction, pipeline design, handling missing data"),
        Competency("Statistics & Experimentation", "technical_core", 0.12,
                    "Hypothesis testing, A/B testing, causal inference, statistical rigor"),
        Competency("MLOps & Production ML", "technical_core", 0.10,
                    "Model deployment, monitoring drift, reproducibility, serving infrastructure"),
        Competency("Data Infrastructure & Tools", "technical_breadth", 0.08,
                    "SQL, Spark, cloud ML services, data warehousing, orchestration"),
        Competency("Domain Knowledge Application", "technical_breadth", 0.08,
                    "Translating business problems to ML tasks, domain-specific evaluation"),
        Competency("Analytical Problem Solving", "problem_solving", 0.10,
                    "Problem framing, EDA approach, debugging model performance, systematic analysis"),
        Competency("Technical Communication", "communication", 0.10,
                    "Explaining models to non-technical stakeholders, visualization, documentation"),
        Competency("Collaboration & Cross-functional Work", "behavioral", 0.08,
                    "Working with engineers, product managers, stakeholder management"),
        Competency("Ownership & Growth Mindset", "behavioral", 0.07,
                    "Research awareness, ethical ML considerations, continuous learning"),
    ],
    "product_manager": [
        Competency("Product Strategy & Vision", "technical_core", 0.15,
                    "Product roadmap, market analysis, competitive positioning, long-term vision"),
        Competency("Requirements & User Research", "technical_core", 0.13,
                    "User interviews, personas, jobs-to-be-done, requirement specification"),
        Competency("Prioritization & Decision Making", "technical_core", 0.12,
                    "Frameworks (RICE, ICE), stakeholder balancing, resource allocation"),
        Competency("Metrics & Data-Driven Decisions", "technical_core", 0.10,
                    "KPI definition, funnel analysis, A/B testing interpretation, data literacy"),
        Competency("Technical Understanding", "technical_breadth", 0.08,
                    "Engineering feasibility assessment, API concepts, system limitations"),
        Competency("Market & Business Acumen", "technical_breadth", 0.08,
                    "Business models, competitive analysis, go-to-market strategy"),
        Competency("Problem Structuring", "problem_solving", 0.10,
                    "Breaking down ambiguous problems, root cause analysis, trade-off evaluation"),
        Competency("Stakeholder Communication", "communication", 0.10,
                    "Presenting to executives, writing PRDs, cross-team alignment"),
        Competency("Leadership & Influence", "behavioral", 0.08,
                    "Leading without authority, conflict resolution, team motivation"),
        Competency("Ownership & Growth Mindset", "behavioral", 0.06,
                    "Learning from failures, customer empathy, iterative improvement"),
    ],
    "mobile_engineer": [
        Competency("Platform-Specific Development", "technical_core", 0.14,
                    "iOS/Android SDK mastery, platform lifecycle, native APIs"),
        Competency("Cross-Platform Frameworks", "technical_core", 0.12,
                    "React Native/Flutter/KMP, bridge layers, platform-specific code"),
        Competency("Mobile UI & UX Implementation", "technical_core", 0.12,
                    "Navigation patterns, animations, responsive layouts, design system adherence"),
        Competency("Performance & Memory Optimization", "technical_core", 0.10,
                    "Profiling, memory leaks, battery optimization, app size reduction"),
        Competency("Networking & Data Persistence", "technical_breadth", 0.08,
                    "REST/GraphQL clients, offline-first, local storage, sync strategies"),
        Competency("Testing & CI/CD for Mobile", "technical_breadth", 0.08,
                    "Unit/UI testing, app distribution, CI pipelines, crash analytics"),
        Competency("Debugging & Problem Decomposition", "problem_solving", 0.10,
                    "Device-specific issues, crash analysis, systematic debugging"),
        Competency("Technical Communication", "communication", 0.10,
                    "API contract discussions, design handoff, documentation"),
        Competency("Collaboration & Cross-Platform Alignment", "behavioral", 0.08,
                    "Working with backend/design teams, code review, platform parity discussions"),
        Competency("Ownership & Growth Mindset", "behavioral", 0.08,
                    "Staying current with platform updates, user feedback integration"),
    ],
    "designer": [
        Competency("UX Research & User Understanding", "technical_core", 0.15,
                    "User interviews, usability testing, personas, journey mapping"),
        Competency("UI Design & Visual Systems", "technical_core", 0.14,
                    "Design systems, typography, color theory, layout principles, Figma mastery"),
        Competency("Interaction Design", "technical_core", 0.12,
                    "Micro-interactions, navigation patterns, prototyping, motion design"),
        Competency("Information Architecture", "technical_core", 0.10,
                    "Content structure, navigation flows, card sorting, wireframing"),
        Competency("Accessibility Design", "technical_breadth", 0.08,
                    "WCAG guidelines, inclusive design, color contrast, screen reader considerations"),
        Competency("Design-to-Development Handoff", "technical_breadth", 0.08,
                    "Design specs, component documentation, developer collaboration"),
        Competency("Design Problem Solving", "problem_solving", 0.10,
                    "Design thinking, constraint-based design, iterative problem solving"),
        Competency("Stakeholder Communication", "communication", 0.10,
                    "Presenting designs, handling feedback, articulating design rationale"),
        Competency("Collaboration & Cross-functional Work", "behavioral", 0.06,
                    "Working with PMs and engineers, design critique, team processes"),
        Competency("Ownership & Growth Mindset", "behavioral", 0.07,
                    "Design trend awareness, user empathy, iterating on feedback"),
    ],
}


def get_competencies(role: str) -> list[Competency]:
    """Return competencies for the given role, falling back to backend_engineer."""
    return ROLE_COMPETENCIES.get(role, ROLE_COMPETENCIES["backend_engineer"])


def get_category_weights(role: str) -> dict[str, float]:
    """Return total weight per category for a role."""
    weights: dict[str, float] = {}
    for c in get_competencies(role):
        weights[c.category] = weights.get(c.category, 0.0) + c.weight
    return weights


def build_question_plan(role: str, max_questions: int) -> list[list[str]]:
    """
    Map each question slot to 1-2 competency names to target.

    Higher-weight competencies get dedicated questions; lower-weight ones share slots.
    Returns a list of length max_questions, each element is a list of competency names.
    """
    competencies = get_competencies(role)
    sorted_comps = sorted(competencies, key=lambda c: c.weight, reverse=True)

    plan: list[list[str]] = [[] for _ in range(max_questions)]

    # Phases:
    # Q1 (intro): highest-weight competency (resume-grounded opener)
    # Q2 to Q(max-3): technical core competencies
    # Q(max-2) to Q(max-1): problem_solving + technical_breadth
    # Q(max): behavioral + closing

    assigned: set[str] = set()

    # Q1: highest weight (intro)
    plan[0] = [sorted_comps[0].name]
    assigned.add(sorted_comps[0].name)

    # Last question: behavioral competencies
    behavioral = [c for c in sorted_comps if c.category == "behavioral" and c.name not in assigned]
    if behavioral:
        plan[max_questions - 1] = [behavioral[0].name]
        assigned.add(behavioral[0].name)
        if len(behavioral) > 1:
            plan[max_questions - 1].append(behavioral[1].name)
            assigned.add(behavioral[1].name)

    # Q(max-2) and Q(max-1): problem_solving + technical_breadth
    ps_and_breadth = [c for c in sorted_comps
                      if c.category in ("problem_solving", "technical_breadth") and c.name not in assigned]
    for i, slot_idx in enumerate(range(max(1, max_questions - 3), max_questions - 1)):
        if i < len(ps_and_breadth):
            plan[slot_idx].append(ps_and_breadth[i].name)
            assigned.add(ps_and_breadth[i].name)

    # Remaining slots Q2..Q(max-4): fill with unassigned competencies by weight
    remaining = [c for c in sorted_comps if c.name not in assigned]
    empty_slots = [i for i in range(1, max_questions) if not plan[i]]

    for i, slot_idx in enumerate(empty_slots):
        if i < len(remaining):
            plan[slot_idx].append(remaining[i].name)
            assigned.add(remaining[i].name)

    # Any unassigned competencies: double up on least-loaded slots
    still_unassigned = [c for c in sorted_comps if c.name not in assigned]
    for comp in still_unassigned:
        # Find slot with fewest competencies
        min_slot = min(range(1, max_questions), key=lambda s: len(plan[s]))
        plan[min_slot].append(comp.name)

    return plan


def build_interview_plan(role: str, max_questions: int, resume_profile: dict | None = None) -> list[dict]:
    """Return a richer plan for each core interview topic.

    Each item includes competency targets plus optional resume anchor and
    verification target derived from the uploaded resume.
    """
    base_plan = build_question_plan(role, max_questions)
    anchors = list((resume_profile or {}).get("project_highlights", []))
    verification_targets = list((resume_profile or {}).get("verification_targets", []))

    topic_plan: list[dict] = []
    anchor_idx = 0
    verification_idx = 0

    for idx, competencies in enumerate(base_plan):
        entry: dict = {
            "slot": idx + 1,
            "competencies": competencies,
            "resume_anchor": None,
            "verification_target": None,
        }

        if anchor_idx < len(anchors) and (idx == 0 or idx < max_questions - 1):
            entry["resume_anchor"] = anchors[anchor_idx]
            anchor_idx += 1

        if verification_idx < len(verification_targets):
            entry["verification_target"] = verification_targets[verification_idx]
            verification_idx += 1

        topic_plan.append(entry)

    return topic_plan
