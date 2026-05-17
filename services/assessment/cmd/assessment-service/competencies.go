package main

type Competency struct {
	Name        string  `json:"name"`
	Category    string  `json:"category"`
	Weight      float64 `json:"weight"`
	Description string  `json:"description"`
}

var RoleCompetencies = map[string][]Competency{
	"backend_engineer": {
		{"System Design & Architecture", "technical_core", 0.15, "Ability to design scalable systems, choose appropriate patterns, and reason about trade-offs"},
		{"Database Design & Optimization", "technical_core", 0.12, "Schema design, query optimization, indexing strategies, replication and sharding"},
		{"API Design & Protocols", "technical_core", 0.12, "REST/gRPC API design, versioning, error handling, documentation"},
		{"Programming Fundamentals", "technical_core", 0.10, "Algorithms, data structures, language-specific idioms, code quality"},
		{"DevOps & Infrastructure", "technical_breadth", 0.08, "CI/CD, containers, cloud services, deployment strategies"},
		{"Security & Error Handling", "technical_breadth", 0.08, "Authentication, authorization, input validation, resilience patterns"},
		{"Debugging & Problem Decomposition", "problem_solving", 0.10, "Systematic debugging, root cause analysis, breaking down complex problems"},
		{"Technical Communication", "communication", 0.10, "Explaining technical decisions, documenting, discussing trade-offs clearly"},
		{"Collaboration & Code Review", "behavioral", 0.08, "Teamwork, code review practices, knowledge sharing, mentoring"},
		{"Ownership & Growth Mindset", "behavioral", 0.07, "Taking responsibility, learning from failures, continuous improvement"},
	},
	"frontend_engineer": {
		{"UI Framework Mastery", "technical_core", 0.15, "Deep knowledge of React/Vue/Angular, component architecture, state management"},
		{"Web Performance Optimization", "technical_core", 0.12, "Bundle optimization, rendering strategies (SSR/SSG/CSR), lazy loading, Core Web Vitals"},
		{"CSS & Responsive Design", "technical_core", 0.10, "Layout systems, responsive design, CSS-in-JS, design system implementation"},
		{"JavaScript/TypeScript Fundamentals", "technical_core", 0.12, "Language mastery, async patterns, type system, ES modules"},
		{"Accessibility & Standards", "technical_breadth", 0.08, "WCAG compliance, semantic HTML, ARIA, screen reader testing"},
		{"Testing & Quality", "technical_breadth", 0.08, "Unit/integration/E2E testing, visual regression, testing strategies"},
		{"Debugging & Problem Decomposition", "problem_solving", 0.10, "Browser devtools mastery, performance profiling, systematic debugging"},
		{"Technical Communication", "communication", 0.10, "Explaining UI/UX decisions, documenting components, design discussions"},
		{"Collaboration & Design Partnership", "behavioral", 0.08, "Working with designers, code review, cross-functional teamwork"},
		{"Ownership & Growth Mindset", "behavioral", 0.07, "Staying current with ecosystem, learning from user feedback, initiative"},
	},
	"qa_engineer": {
		{"Test Strategy & Planning", "technical_core", 0.15, "Test plan design, risk-based testing, coverage analysis, test pyramid"},
		{"Test Automation", "technical_core", 0.14, "Automation frameworks, CI integration, maintainable test suites, page objects"},
		{"Manual & Exploratory Testing", "technical_core", 0.10, "Exploratory testing techniques, edge case discovery, heuristic-based testing"},
		{"API & Performance Testing", "technical_core", 0.10, "API testing tools, load testing, performance benchmarking, bottleneck analysis"},
		{"DevOps & CI/CD Integration", "technical_breadth", 0.08, "Pipeline integration, test environments, containerized testing"},
		{"Domain & Product Understanding", "technical_breadth", 0.08, "Understanding requirements, user stories, acceptance criteria translation"},
		{"Root Cause Analysis", "problem_solving", 0.10, "Bug investigation, reproduction steps, systematic defect analysis"},
		{"Technical Communication", "communication", 0.10, "Bug reports, test documentation, stakeholder communication"},
		{"Collaboration & Advocacy", "behavioral", 0.08, "Working with developers, quality advocacy, constructive feedback"},
		{"Ownership & Growth Mindset", "behavioral", 0.07, "Process improvement, learning new tools, quality culture building"},
	},
	"devops_engineer": {
		{"CI/CD Pipeline Design", "technical_core", 0.14, "Pipeline architecture, build optimization, deployment strategies, GitOps"},
		{"Container Orchestration", "technical_core", 0.13, "Kubernetes/Docker, service mesh, scaling, resource management"},
		{"Cloud Infrastructure", "technical_core", 0.12, "AWS/GCP/Azure services, IaC (Terraform/Pulumi), networking, cost optimization"},
		{"Monitoring & Observability", "technical_core", 0.10, "Metrics, logging, tracing, alerting, SLOs/SLIs, incident response dashboards"},
		{"Security & Compliance", "technical_breadth", 0.08, "Secret management, network security, compliance automation, vulnerability scanning"},
		{"Scripting & Automation", "technical_breadth", 0.08, "Shell scripting, Python automation, configuration management"},
		{"Incident Response & Troubleshooting", "problem_solving", 0.10, "Production debugging, postmortem analysis, disaster recovery planning"},
		{"Technical Communication", "communication", 0.10, "Runbooks, architecture docs, cross-team communication during incidents"},
		{"Collaboration & On-Call Culture", "behavioral", 0.08, "Team coordination, knowledge sharing, on-call practices, blameless culture"},
		{"Ownership & Growth Mindset", "behavioral", 0.07, "Reliability improvement, learning from incidents, proactive optimization"},
	},
	"data_scientist": {
		{"ML Modeling & Algorithms", "technical_core", 0.15, "Model selection, training, evaluation, hyperparameter tuning, deep learning"},
		{"Data Processing & Feature Engineering", "technical_core", 0.12, "Data cleaning, feature extraction, pipeline design, handling missing data"},
		{"Statistics & Experimentation", "technical_core", 0.12, "Hypothesis testing, A/B testing, causal inference, statistical rigor"},
		{"MLOps & Production ML", "technical_core", 0.10, "Model deployment, monitoring drift, reproducibility, serving infrastructure"},
		{"Data Infrastructure & Tools", "technical_breadth", 0.08, "SQL, Spark, cloud ML services, data warehousing, orchestration"},
		{"Domain Knowledge Application", "technical_breadth", 0.08, "Translating business problems to ML tasks, domain-specific evaluation"},
		{"Analytical Problem Solving", "problem_solving", 0.10, "Problem framing, EDA approach, debugging model performance, systematic analysis"},
		{"Technical Communication", "communication", 0.10, "Explaining models to non-technical stakeholders, visualization, documentation"},
		{"Collaboration & Cross-functional Work", "behavioral", 0.08, "Working with engineers, product managers, stakeholder management"},
		{"Ownership & Growth Mindset", "behavioral", 0.07, "Research awareness, ethical ML considerations, continuous learning"},
	},
	"product_manager": {
		{"Product Strategy & Vision", "technical_core", 0.15, "Product roadmap, market analysis, competitive positioning, long-term vision"},
		{"Requirements & User Research", "technical_core", 0.13, "User interviews, personas, jobs-to-be-done, requirement specification"},
		{"Prioritization & Decision Making", "technical_core", 0.12, "Frameworks (RICE, ICE), stakeholder balancing, resource allocation"},
		{"Metrics & Data-Driven Decisions", "technical_core", 0.10, "KPI definition, funnel analysis, A/B testing interpretation, data literacy"},
		{"Technical Understanding", "technical_breadth", 0.08, "Engineering feasibility assessment, API concepts, system limitations"},
		{"Market & Business Acumen", "technical_breadth", 0.08, "Business models, competitive analysis, go-to-market strategy"},
		{"Problem Structuring", "problem_solving", 0.10, "Breaking down ambiguous problems, root cause analysis, trade-off evaluation"},
		{"Stakeholder Communication", "communication", 0.10, "Presenting to executives, writing PRDs, cross-team alignment"},
		{"Leadership & Influence", "behavioral", 0.08, "Leading without authority, conflict resolution, team motivation"},
		{"Ownership & Growth Mindset", "behavioral", 0.06, "Learning from failures, customer empathy, iterative improvement"},
	},
	"mobile_engineer": {
		{"Platform-Specific Development", "technical_core", 0.14, "iOS/Android SDK mastery, platform lifecycle, native APIs"},
		{"Cross-Platform Frameworks", "technical_core", 0.12, "React Native/Flutter/KMP, bridge layers, platform-specific code"},
		{"Mobile UI & UX Implementation", "technical_core", 0.12, "Navigation patterns, animations, responsive layouts, design system adherence"},
		{"Performance & Memory Optimization", "technical_core", 0.10, "Profiling, memory leaks, battery optimization, app size reduction"},
		{"Networking & Data Persistence", "technical_breadth", 0.08, "REST/GraphQL clients, offline-first, local storage, sync strategies"},
		{"Testing & CI/CD for Mobile", "technical_breadth", 0.08, "Unit/UI testing, app distribution, CI pipelines, crash analytics"},
		{"Debugging & Problem Decomposition", "problem_solving", 0.10, "Device-specific issues, crash analysis, systematic debugging"},
		{"Technical Communication", "communication", 0.10, "API contract discussions, design handoff, documentation"},
		{"Collaboration & Cross-Platform Alignment", "behavioral", 0.08, "Working with backend/design teams, code review, platform parity discussions"},
		{"Ownership & Growth Mindset", "behavioral", 0.08, "Staying current with platform updates, user feedback integration"},
	},
	"designer": {
		{"UX Research & User Understanding", "technical_core", 0.15, "User interviews, usability testing, personas, journey mapping"},
		{"UI Design & Visual Systems", "technical_core", 0.14, "Design systems, typography, color theory, layout principles, Figma mastery"},
		{"Interaction Design", "technical_core", 0.12, "Micro-interactions, navigation patterns, prototyping, motion design"},
		{"Information Architecture", "technical_core", 0.10, "Content structure, navigation flows, card sorting, wireframing"},
		{"Accessibility Design", "technical_breadth", 0.08, "WCAG guidelines, inclusive design, color contrast, screen reader considerations"},
		{"Design-to-Development Handoff", "technical_breadth", 0.08, "Design specs, component documentation, developer collaboration"},
		{"Design Problem Solving", "problem_solving", 0.10, "Design thinking, constraint-based design, iterative problem solving"},
		{"Stakeholder Communication", "communication", 0.10, "Presenting designs, handling feedback, articulating design rationale"},
		{"Collaboration & Cross-functional Work", "behavioral", 0.06, "Working with PMs and engineers, design critique, team processes"},
		{"Ownership & Growth Mindset", "behavioral", 0.07, "Design trend awareness, user empathy, iterating on feedback"},
	},
}

func GetCompetencies(role string) []Competency {
	if comps, ok := RoleCompetencies[role]; ok {
		return comps
	}
	return RoleCompetencies["backend_engineer"]
}
