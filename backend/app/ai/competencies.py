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

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.ai.resume_anchor_filters import (
    filter_resume_anchors_for_role,
    filter_verification_targets_for_role,
)

logger = logging.getLogger(__name__)


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

# ---------------------------------------------------------------------------
# Structured role block ordering (Iteration 2)
# ---------------------------------------------------------------------------

# Priority order of core competencies for resume deep-dive + technical block.
# This enforces stable role-relevant sequencing and avoids topic jumps.
_DEFAULT_ROLE_CORE_COMPETENCY_ORDER: dict[str, list[str]] = {
    # service -> API/data -> reliability
    "backend_engineer": [
        "API Design & Protocols",
        "Database Design & Optimization",
        "System Design & Architecture",
        "Debugging & Problem Decomposition",
        "Security & Error Handling",
        "DevOps & Infrastructure",
        "Programming Fundamentals",
    ],
    # feature ownership -> state/perf -> accessibility
    "frontend_engineer": [
        "UI Framework Mastery",
        "Web Performance Optimization",
        "JavaScript/TypeScript Fundamentals",
        "Accessibility & Standards",
        "Testing & Quality",
        "Debugging & Problem Decomposition",
        "CSS & Responsive Design",
    ],
    # product quality -> strategy -> automation/CI
    "qa_engineer": [
        "Domain & Product Understanding",
        "Test Strategy & Planning",
        "Test Automation",
        "DevOps & CI/CD Integration",
        "Root Cause Analysis",
        "Manual & Exploratory Testing",
        "API & Performance Testing",
    ],
    # pipeline -> rollout safety -> incidents/SLO
    "devops_engineer": [
        "CI/CD Pipeline Design",
        "Security & Compliance",
        "Container Orchestration",
        "Monitoring & Observability",
        "Incident Response & Troubleshooting",
        "Cloud Infrastructure",
        "Scripting & Automation",
    ],
    # problem framing -> data/statistics -> model/monitoring
    "data_scientist": [
        "Domain Knowledge Application",
        "Data Processing & Feature Engineering",
        "Statistics & Experimentation",
        "ML Modeling & Algorithms",
        "MLOps & Production ML",
        "Analytical Problem Solving",
        "Data Infrastructure & Tools",
    ],
    # user problem -> prioritization -> metrics/stakeholders
    "product_manager": [
        "Requirements & User Research",
        "Prioritization & Decision Making",
        "Metrics & Data-Driven Decisions",
        "Stakeholder Communication",
        "Problem Structuring",
        "Product Strategy & Vision",
        "Technical Understanding",
    ],
    # module ownership -> crash/perf -> release quality
    "mobile_engineer": [
        "Platform-Specific Development",
        "Performance & Memory Optimization",
        "Debugging & Problem Decomposition",
        "Testing & CI/CD for Mobile",
        "Networking & Data Persistence",
        "Mobile UI & UX Implementation",
        "Cross-Platform Frameworks",
    ],
    # case study -> research -> design trade-offs
    "designer": [
        "UX Research & User Understanding",
        "Information Architecture",
        "Interaction Design",
        "Design Problem Solving",
        "UI Design & Visual Systems",
        "Accessibility Design",
        "Design-to-Development Handoff",
    ],
}


@lru_cache(maxsize=1)
def _load_role_question_banks() -> dict:
    banks_path = Path(__file__).with_name("role_question_banks.json")
    try:
        with banks_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        logger.warning("role_question_banks.json not found, using built-in defaults")
        return {}
    except Exception:
        logger.exception("Failed to load role_question_banks.json, using built-in defaults")
        return {}

    if not isinstance(payload, dict):
        logger.warning("role_question_banks.json has invalid shape, using built-in defaults")
        return {}
    return payload


def get_role_core_competency_order(role: str) -> list[str]:
    banks = _load_role_question_banks()
    role_entry = banks.get(role) if isinstance(banks, dict) else None
    if isinstance(role_entry, dict):
        configured = role_entry.get("core_competency_order")
        if isinstance(configured, list):
            validated = [str(item).strip() for item in configured if str(item).strip()]
            if validated:
                return validated
    return _DEFAULT_ROLE_CORE_COMPETENCY_ORDER.get(role, [])


def _normalized_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            result.append(text)
    return result


def _normalize_question_block_entry(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    block = str(raw.get("block") or "").strip()
    tier = str(raw.get("tier") or "").strip()
    lead_question = str(raw.get("lead_question") or "").strip()
    allowed_probes = _normalized_string_list(raw.get("allowed_probes"))
    scored_metrics = _normalized_string_list(raw.get("scored_metrics"))
    if not block or not tier or not lead_question:
        return None
    if not scored_metrics:
        return None
    return {
        "block": block,
        "tier": tier,
        "lead_question": lead_question,
        "allowed_probes": allowed_probes,
        "scored_metrics": scored_metrics,
    }


def get_role_question_blocks(role: str) -> list[dict]:
    banks = _load_role_question_banks()
    role_entry = banks.get(role) if isinstance(banks, dict) else None
    if isinstance(role_entry, dict):
        configured = role_entry.get("question_blocks")
        if isinstance(configured, list):
            normalized = [
                item
                for item in (_normalize_question_block_entry(raw) for raw in configured)
                if item is not None
            ]
            if normalized:
                return normalized

    return [
        {
            "block": "intro",
            "tier": "adaptive",
            "lead_question": "Расскажите о себе: путь, профильное образование и релевантный опыт.",
            "allowed_probes": [
                "Что в вашем опыте лучше всего готовит к целевой роли?",
                "Какие задачи вам давались сложнее и как вы их закрывали?",
            ],
            "scored_metrics": ["communication", "role_fit", "growth_potential"],
        },
        {
            "block": "resume_followup",
            "tier": "adaptive",
            "lead_question": "Давайте пройдем по опыту из резюме: зона ответственности, сложные кейсы и личный вклад.",
            "allowed_probes": [
                "Какие решения принимали лично вы?",
                "По каким сигналам оценивали результат?",
            ],
            "scored_metrics": ["practical_experience", "problem_solving", "communication"],
        },
        {
            "block": "technical_foundation",
            "tier": "core",
            "lead_question": "Разберите ключевой технический кейс: контекст, действия, результат.",
            "allowed_probes": [
                "Какие trade-off учитывали?",
                "Какие проверки или метрики использовали?",
            ],
            "scored_metrics": ["technical_depth", "problem_solving", "practical_experience"],
        },
        {
            "block": "technical_depth",
            "tier": "advanced",
            "lead_question": "Усложним задачу: как бы вы действовали при ограничениях и рисках в production?",
            "allowed_probes": [
                "Как диагностировали первопричину?",
                "Какой альтернативный подход рассматривали?",
            ],
            "scored_metrics": ["technical_depth", "problem_solving", "ownership"],
        },
        {
            "block": "behavioral_closing",
            "tier": "closing",
            "lead_question": "В завершение: расскажите о сложной кросс-командной ситуации и вашей роли в результате.",
            "allowed_probes": [
                "Как снимали напряжение и выравнивали ожидания?",
                "Чему научились и что изменили в подходе?",
            ],
            "scored_metrics": ["ownership", "communication", "growth_potential"],
        },
    ]


def _normalize_followup_rules(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, str] = {}
    for key in ("clarify", "deep_dive", "simplify"):
        text = str(raw.get(key) or "").strip()
        if text:
            normalized[key] = text
    return normalized


def _normalize_scenario_chain_entry(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    case_id = str(raw.get("case_id") or "").strip()
    title = str(raw.get("title") or "").strip()
    competency = str(raw.get("competency") or "").strip()
    try:
        difficulty_tier = int(raw.get("difficulty_tier") or 3)
    except (TypeError, ValueError):
        difficulty_tier = 3
    if difficulty_tier < 1:
        difficulty_tier = 1
    if difficulty_tier > 5:
        difficulty_tier = 5
    followup_rules = _normalize_followup_rules(raw.get("followup_rules"))
    questions = _normalized_string_list(raw.get("questions"))
    if not case_id or not title or not competency:
        return None
    if len(questions) < 4:
        return None
    return {
        "case_id": case_id,
        "title": title,
        "competency": competency,
        "difficulty_tier": difficulty_tier,
        "followup_rules": followup_rules,
        "questions": questions[:6],
    }


def get_role_scenario_chains(role: str) -> list[dict]:
    banks = _load_role_question_banks()
    role_entry = banks.get(role) if isinstance(banks, dict) else None
    if not isinstance(role_entry, dict):
        return []
    configured = role_entry.get("scenario_chains")
    if not isinstance(configured, list):
        return []
    normalized = [
        item
        for item in (_normalize_scenario_chain_entry(raw) for raw in configured)
        if item is not None
    ]
    return normalized


_QA_COMPETENCY_CASE_QUESTIONS_RU: dict[str, str] = {
    "Domain & Product Understanding": "Разберите продуктовый QA-кейс: какой пользовательский риск считали критичным, как проверяли и что включили в acceptance?",
    "Test Strategy & Planning": "На примере новой фичи: какие проверки ставите в smoke, какие в regression и почему?",
    "Test Automation": "Один кейс по автотестам: что автоматизировали первым, какой риск закрыли и чем подтвердили стабильность?",
    "DevOps & CI/CD Integration": "Один CI/CD-кейс: где quality gate, что блокирует релиз и по каким правилам принимаете решение о выпуске?",
    "Root Cause Analysis": "Один production-дефект: как воспроизвели, где нашли первопричину и как подтвердили фикc?",
    "Manual & Exploratory Testing": "Один exploratory-кейс: какая гипотеза была, какие шаги сделали и какой неочевидный дефект нашли?",
    "API & Performance Testing": "Один API-кейс: какой endpoint проверяли, какие негативные сценарии добавили и какие метрики использовали для решения о релизе?",
}

_QA_COMPETENCY_ALLOWED_PROBES_RU: dict[str, list[str]] = {
    "Domain & Product Understanding": [
        "Как приоритизировали риск для пользователя и бизнеса?",
        "Какой сигнал показал, что риск действительно закрыт?",
    ],
    "Test Strategy & Planning": [
        "Какие критерии входа/выхода были у тестирования?",
        "Что бы вы убрали из плана, если времени стало в 2 раза меньше?",
    ],
    "Test Automation": [
        "Какой флаки-тест был самым проблемным и как его стабилизировали?",
        "Как отслеживали, что автотесты продолжают ловить реальные регрессии?",
    ],
    "DevOps & CI/CD Integration": [
        "Что должно падать в пайплайне автоматически, а что требует ручного решения?",
        "Какой rollback-сценарий считали минимально безопасным?",
    ],
    "Root Cause Analysis": [
        "Какие артефакты использовали в расследовании: логи, метрики, трассировки?",
        "Как убедились, что фикс не сломал соседний функционал?",
    ],
    "Manual & Exploratory Testing": [
        "Какие эвристики использовали для поиска неочевидных дефектов?",
        "Как документировали находки, чтобы команда могла воспроизвести дефект?",
    ],
    "API & Performance Testing": [
        "Какие коды/контракты ответа считали критичными для блокировки релиза?",
        "Какой порог latency/error rate считали приемлемым и почему?",
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


def build_question_plan(
    role: str,
    max_questions: int,
    *,
    structured_flow: bool = True,
) -> list[list[str]]:
    """
    Map each question slot to 1-2 competency names to target.

    Higher-weight competencies get dedicated questions; lower-weight ones share slots.
    Returns a list of length max_questions, each element is a list of competency names.
    """
    competencies = get_competencies(role)
    sorted_comps = sorted(competencies, key=lambda c: c.weight, reverse=True)

    plan: list[list[str]] = [[] for _ in range(max_questions)]

    if not structured_flow:
        # Legacy ordering for template-guided flows.
        assigned: set[str] = set()

        plan[0] = [sorted_comps[0].name]
        assigned.add(sorted_comps[0].name)

        behavioral = [c for c in sorted_comps if c.category == "behavioral" and c.name not in assigned]
        if behavioral:
            plan[max_questions - 1] = [behavioral[0].name]
            assigned.add(behavioral[0].name)
            if len(behavioral) > 1:
                plan[max_questions - 1].append(behavioral[1].name)
                assigned.add(behavioral[1].name)

        ps_and_breadth = [
            c for c in sorted_comps
            if c.category in ("problem_solving", "technical_breadth") and c.name not in assigned
        ]
        for i, slot_idx in enumerate(range(max(1, max_questions - 3), max_questions - 1)):
            if i < len(ps_and_breadth):
                plan[slot_idx].append(ps_and_breadth[i].name)
                assigned.add(ps_and_breadth[i].name)

        remaining = [c for c in sorted_comps if c.name not in assigned]
        empty_slots = [i for i in range(1, max_questions) if not plan[i]]

        for i, slot_idx in enumerate(empty_slots):
            if i < len(remaining):
                plan[slot_idx].append(remaining[i].name)
                assigned.add(remaining[i].name)

        still_unassigned = [c for c in sorted_comps if c.name not in assigned]
        for comp in still_unassigned:
            min_slot = min(range(1, max_questions), key=lambda s: len(plan[s]))
            plan[min_slot].append(comp.name)

        return plan

    # Structured flow V2:
    # Q1: self-intro / experience summary led by communication
    # Q2: resume-driven clarification
    # Q3..Q(max-1): technical and problem-solving block
    # Q(max): behavioral closing
    communication = [c for c in sorted_comps if c.category == "communication"]
    intro_competency = communication[0] if communication else sorted_comps[0]

    assigned: set[str] = set()

    plan[0] = [intro_competency.name]
    assigned.add(intro_competency.name)

    behavioral = [c for c in sorted_comps if c.category == "behavioral" and c.name not in assigned]
    if behavioral:
        plan[max_questions - 1] = [behavioral[0].name]
        assigned.add(behavioral[0].name)
        if len(behavioral) > 1:
            plan[max_questions - 1].append(behavioral[1].name)
            assigned.add(behavioral[1].name)

    remaining_by_weight = [c for c in sorted_comps if c.name not in assigned]
    remaining_map = {c.name: c for c in remaining_by_weight}

    ordered_names: list[str] = []
    for name in get_role_core_competency_order(role):
        if name in remaining_map and name not in ordered_names:
            ordered_names.append(name)

    for comp in remaining_by_weight:
        if comp.name not in ordered_names:
            ordered_names.append(comp.name)

    if not ordered_names:
        return plan

    # Slot 2 is always resume deep-dive for structured flow.
    if max_questions > 2:
        plan[1] = [ordered_names[0]]

    # Fill technical block with stable role order; once exhausted, keep cycling.
    technical_slots = list(range(2, max_questions - 1))
    cursor = 1
    for slot_idx in technical_slots:
        if cursor < len(ordered_names):
            plan[slot_idx] = [ordered_names[cursor]]
            cursor += 1
        else:
            cycle_idx = (slot_idx - technical_slots[0]) % len(ordered_names)
            plan[slot_idx] = [ordered_names[cycle_idx]]

    return plan


def build_interview_plan(
    role: str,
    max_questions: int,
    resume_profile: dict | None = None,
    *,
    structured_flow: bool = True,
) -> list[dict]:
    """Return a richer plan for each core interview topic.

    Each item includes competency targets plus optional resume anchor and
    verification target derived from the uploaded resume.
    """
    base_plan = build_question_plan(role, max_questions, structured_flow=structured_flow)
    role_blocks = get_role_question_blocks(role)
    anchors = filter_resume_anchors_for_role(
        role,
        list((resume_profile or {}).get("project_highlights", [])),
    )
    verification_targets = filter_verification_targets_for_role(
        role,
        list((resume_profile or {}).get("verification_targets", [])),
    )

    topic_plan: list[dict] = []
    anchor_idx = 0
    verification_idx = 0
    technical_block_idx = 0

    normalized_blocks = {item.get("block"): item for item in role_blocks}
    technical_blocks = [
        item for item in role_blocks
        if str(item.get("block", "")).startswith("technical")
    ]

    for idx, competencies in enumerate(base_plan):
        if structured_flow and idx == 0:
            block_spec = normalized_blocks.get("intro")
        elif structured_flow and idx == 1:
            block_spec = normalized_blocks.get("resume_followup")
        elif structured_flow and idx == max_questions - 1:
            block_spec = normalized_blocks.get("behavioral_closing")
        elif structured_flow and technical_blocks:
            block_spec = technical_blocks[technical_block_idx % len(technical_blocks)]
            technical_block_idx += 1
        else:
            block_spec = role_blocks[min(idx, len(role_blocks) - 1)] if role_blocks else None

        entry: dict = {
            "slot": idx + 1,
            "competencies": competencies,
            "resume_anchor": None,
            "verification_target": None,
            "phase": (
                "intro"
                if structured_flow and idx == 0
                else "resume_followup"
                if structured_flow and idx == 1
                else "behavioral_closing"
                if structured_flow and idx == max_questions - 1
                else "technical"
                if structured_flow
                else None
            ),
            "block": block_spec.get("block") if isinstance(block_spec, dict) else None,
            "tier": block_spec.get("tier") if isinstance(block_spec, dict) else None,
            "lead_question": block_spec.get("lead_question") if isinstance(block_spec, dict) else None,
            "allowed_probes": list(block_spec.get("allowed_probes") or []) if isinstance(block_spec, dict) else [],
            "scored_metrics": list(block_spec.get("scored_metrics") or []) if isinstance(block_spec, dict) else [],
        }

        if role == "qa_engineer" and structured_flow and entry.get("phase") == "technical":
            primary_competency = str(competencies[0]).strip() if competencies else ""
            override_question = _QA_COMPETENCY_CASE_QUESTIONS_RU.get(primary_competency)
            override_probes = _QA_COMPETENCY_ALLOWED_PROBES_RU.get(primary_competency)
            if override_question:
                entry["lead_question"] = override_question
            if override_probes:
                entry["allowed_probes"] = list(override_probes)

        use_anchor_slot = idx < max_questions - 1
        if structured_flow and idx == 0:
            # Keep opening intro generic and reserve strongest anchor for resume follow-up.
            use_anchor_slot = False

        if anchor_idx < len(anchors) and use_anchor_slot:
            entry["resume_anchor"] = anchors[anchor_idx]
            anchor_idx += 1

        use_verification_slot = True
        if structured_flow and idx == 0:
            use_verification_slot = False

        if use_verification_slot and verification_idx < len(verification_targets):
            entry["verification_target"] = verification_targets[verification_idx]
            verification_idx += 1

        topic_plan.append(entry)

    return topic_plan
