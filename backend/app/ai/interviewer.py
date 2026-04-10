"""
AI Interviewer module.

Singleton `interviewer` is an LLMInterviewer (Groq) when GROQ_API_KEY is set,
otherwise falls back to MockInterviewer.
"""
import re
import logging
from dataclasses import dataclass, field

from groq import AsyncGroq

from app.ai.model_preferences import DEFAULT_LLM_MODEL, resolve_llm_runtime_model
from app.core.config import settings

logger = logging.getLogger(__name__)

MAX_QUESTIONS = 8

_ROLE_LABELS: dict[str, str] = {
    "backend_engineer": "Backend-разработчик",
    "frontend_engineer": "Frontend-разработчик",
    "qa_engineer": "QA-инженер",
    "devops_engineer": "DevOps-инженер",
    "data_scientist": "Data Scientist",
    "product_manager": "Продакт-менеджер",
    "mobile_engineer": "Mobile-разработчик",
    "designer": "UX/UI Дизайнер",
}

_MAX_QUESTION_CHARS = 170
_MAX_QUESTION_WORDS = 28
_QUESTION_SEGMENT_RE = re.compile(r"[^?]{8,}\?")
_WHITESPACE_RE = re.compile(r"\s+")
_MARKUP_RE = re.compile(r"[*_`#>\[\]\|]")
_LEADING_FILLERS = (
    "я понимаю",
    "это важный аспект",
    "когда мы говорим",
    "давайте поговорим",
    "давайте обсудим",
    "отлично",
    "хорошо",
    "интересно",
    "хороший ответ",
    "great question",
    "great answer",
    "good answer",
    "i understand",
    "let's discuss",
)
_QUESTION_TOKEN_RE = re.compile(r"[a-zA-Zа-яА-Я0-9+#.-]+")
_QUESTION_TOKEN_STOPWORDS = {
    "как", "что", "какой", "какие", "где", "почему", "когда", "вы", "ты",
    "это", "этот", "эта", "и", "или", "но", "для", "про", "без", "над",
    "the", "a", "an", "how", "what", "which", "where", "when", "why", "you",
    "your", "with", "for", "and", "or", "to", "of", "in", "on", "about",
}
_QUESTION_WORD_HINTS = (
    "как", "что", "какой", "какие", "почему", "зачем", "где",
    "how", "what", "which", "why", "where", "walk me through", "tell me about",
)


@dataclass
class InterviewContext:
    target_role: str
    question_number: int          # 1-based core question index
    max_questions: int = MAX_QUESTIONS
    message_history: list[dict] = field(default_factory=list)
    # Each dict: {"role": "assistant"|"candidate", "content": str}
    resume_text: str | None = None
    template_questions: list[str] | None = None
    competency_targets: list[str] | None = None  # competency names for this question
    language: str = "ru"
    # Follow-up tracking (v2-adaptive)
    follow_up_count: int = 0          # how many follow-ups done on current topic (0-2)
    last_answer_words: int = 0        # word count of last candidate answer
    shallow_reason: str = ""          # "too_short" | "no_depth_indicators" | "short_and_generic"
    answer_class: str = "partial"     # strong | partial | generic | no_experience_honest | evasive
    current_topic: str = ""           # topic label for current main question
    topic_depth_score: float = 0.0    # running depth score for current topic (0-10)
    resume_anchor: str | None = None
    verification_target: str | None = None
    diversification_hint: str | None = None
    candidate_memory: list[str] = field(default_factory=list)
    # v3-depth: question type and technology tracking
    question_type: str = "main"       # main | followup | verification | deep_technical | edge_cases
    mentioned_technologies: list[str] = field(default_factory=list)
    verified_skills: list[str] = field(default_factory=list)
    contradiction_flags: list[str] = field(default_factory=list)
    pending_verification: str | None = None  # technology currently being asked about
    topic_phase: str | None = None
    module_type: str | None = None
    module_title: str | None = None
    module_scenario_id: str | None = None
    module_scenario_title: str | None = None
    module_scenario_prompt: str | None = None
    module_stage_key: str | None = None
    module_stage_title: str | None = None
    module_stage_prompt: str | None = None
    module_stage_index: int = 0
    module_stage_count: int = 0

    @property
    def is_followup_mode(self) -> bool:
        return self.question_type != "main"


# ---------------------------------------------------------------------------
# Shallow-answer detection
# ---------------------------------------------------------------------------

_DEPTH_WORDS = frozenset([
    # Russian
    "потому что", "поэтому", "так как", "поскольку", "использовал", "использовала",
    "создал", "создала", "разработал", "разработала", "настроил", "настроила",
    "решил", "решила", "построил", "построила", "реализовал", "реализовала",
    "оптимизировал", "оптимизировала", "написал", "написала", "задеплоил",
    "столкнулся", "столкнулась", "справился", "справилась",
    # English
    "because", "since", "therefore", "built", "implemented", "used", "created",
    "deployed", "configured", "solved", "optimized", "designed", "wrote",
    "integrated", "migrated", "reduced", "improved", "fixed",
])

_EXAMPLE_HINTS = frozenset([
    "например", "for example", "в проекте", "на проекте", "at work",
    "on my", "однажды", "once", "when i", "когда я", "в компании",
    "at my", "we had", "у нас", "у нас был", "в нашей команде", "my team",
    "i worked on", "я работал", "я работала",
])

_NO_EXPERIENCE_PHRASES = (
    "не знаю",
    "не помню",
    "не делал",
    "не делала",
    "не работал",
    "не работала",
    "не приходилось",
    "нет опыта",
    "никак",
    "не могу",
    "не создавал",
    "не создавала",
    "не занимался",
    "не занималась",
    "не использовал",
    "не использовала",
    "нет",
    "i don't know",
    "i dont know",
    "never worked with",
    "no experience",
    "not sure",
    "don't remember",
    "dont remember",
)

_EVASIVE_PHRASES = (
    "обычно",
    "нормально",
    "по-разному",
    "смотря",
    "как получится",
    "все четко",
    "пойдет",
    "it depends",
    "usually",
    "normally",
    "kind of",
    "sort of",
)


def classify_answer(answer: str) -> tuple[str, str]:
    """Return (answer_class, shallow_reason).

    answer_class:
    - strong
    - partial
    - generic
    - no_experience_honest
    - evasive
    """
    normalized = _WHITESPACE_RE.sub(" ", answer.strip().lower())
    words = normalized.split()
    word_count = len(words)

    if any(phrase == normalized or normalized.startswith(f"{phrase} ") for phrase in _NO_EXPERIENCE_PHRASES):
        return "no_experience_honest", "too_short" if word_count < 10 else "no_depth_indicators"

    if any(phrase == normalized or normalized.startswith(f"{phrase} ") for phrase in _EVASIVE_PHRASES):
        return "evasive", "short_and_generic"

    has_depth = any(w in normalized for w in _DEPTH_WORDS)
    has_numbers = bool(re.search(r"\d+", normalized))
    has_example = any(hint in normalized for hint in _EXAMPLE_HINTS)

    if word_count < 10:
        return "generic", "too_short"

    if not has_depth and not has_numbers and not has_example:
        return "generic", "no_depth_indicators"

    if word_count < 30 and not has_numbers and not has_example:
        return "partial", "short_and_generic"

    mentioned_techs = extract_mentioned_technologies(answer)

    if (has_depth and has_example) or (has_depth and has_numbers):
        return "strong", ""

    if has_depth and word_count >= 22 and (mentioned_techs or has_example or has_numbers):
        return "strong", ""

    if has_depth and word_count >= 30:
        return "strong", ""

    return "partial", ""


def detect_shallow_answer(answer: str) -> tuple[bool, str]:
    """Return (is_shallow, reason).

    Reason values: "too_short" | "no_depth_indicators" | "short_and_generic"

    Rules (applied in order, first match wins):
    1. < 10 words            → too_short
    2. No how/why/built +
       no numbers            → no_depth_indicators
    3. < 30 words +
       no numbers +
       no example hint       → short_and_generic
    """
    answer_class, reason = classify_answer(answer)
    return answer_class in {"generic", "partial", "evasive", "no_experience_honest"}, reason


# ---------------------------------------------------------------------------
# Follow-up prompt templates (used as fallback / context hints)
# ---------------------------------------------------------------------------

_FOLLOWUP_PROMPTS_RU: dict[str, list[str]] = {
    "too_short": [
        "Расскажи подробнее — как именно это работало в твоём случае?",
        "Можешь раскрыть чуть больше — что конкретно ты делал и почему именно так?",
        "Звучит интересно — опиши конкретный пример из практики с деталями.",
    ],
    "no_depth_indicators": [
        "Можешь привести реальный пример из своей работы — какой проект, какая задача?",
        "Как именно ты это реализовывал — какие технологии, какие решения принимал?",
        "А какие конкретно были технические сложности и как ты их решил?",
    ],
    "short_and_generic": [
        "Можешь быть конкретнее — что именно ты использовал и в каком контексте?",
        "Расскажи про реальный случай: что за проект, какая задача, как решал?",
        "Хорошо — а с какими конкретными проблемами столкнулся и что сделал?",
    ],
}

_FOLLOWUP_PROMPTS_EN: dict[str, list[str]] = {
    "too_short": [
        "Can you walk me through that in more detail — how exactly did it work in your case?",
        "Tell me more — what specifically did you do and why that approach?",
        "Interesting — give me a concrete example from your work with actual details.",
    ],
    "no_depth_indicators": [
        "Can you give a real example from your work — what project, what was the task?",
        "How exactly did you implement that — which technologies, which decisions did you make?",
        "What specific technical challenges did you face and how did you solve them?",
    ],
    "short_and_generic": [
        "Can you be more specific — what exactly did you use and in what context?",
        "Walk me through a real case: what was the project, the problem, and how you solved it?",
        "What concrete problems did you run into and what did you do about them?",
    ],
}


def get_fallback_followup(reason: str, language: str = "ru") -> str:
    """Return a deterministic follow-up question for the given shallow reason."""
    import random
    bank = (_FOLLOWUP_PROMPTS_RU if language != "en" else _FOLLOWUP_PROMPTS_EN)
    options = bank.get(reason, bank["no_depth_indicators"])
    return random.choice(options)


# ---------------------------------------------------------------------------
# Technology knowledge base — verification & depth questions
# ---------------------------------------------------------------------------

# keyword → canonical name (used for extraction)
_TECH_KEYWORD_MAP: dict[str, str] = {
    "kafka": "kafka",
    "redis": "redis",
    "postgresql": "postgresql",
    "postgres": "postgresql",
    "postgre": "postgresql",
    "kubernetes": "kubernetes",
    "k8s": "kubernetes",
    "docker": "docker",
    "elasticsearch": "elasticsearch",
    "elastic": "elasticsearch",
    "celery": "celery",
    "graphql": "graphql",
    "react": "react",
    "reactjs": "react",
    "aws": "aws",
    "amazon web services": "aws",
    "microservices": "microservices",
    "микросервис": "microservices",
    "grpc": "grpc",
    "rabbitmq": "rabbitmq",
    "rabbit": "rabbitmq",
    "nginx": "nginx",
    "clickhouse": "clickhouse",
    "airflow": "airflow",
    "spark": "spark",
}

# Verification questions: the first question tests understanding, the second tests production experience
_TECH_VERIFY_RU: dict[str, list[str]] = {
    "kafka": [
        "Ты упомянул Kafka — что такое partition и как consumer group распределяет их между воркерами?",
        "Как ты обрабатывал consumer lag и что делал когда он рос?",
        "Как Kafka гарантирует durability и как ты работал с offset commit?",
    ],
    "redis": [
        "Ты упомянул Redis — какие структуры данных использовал и для каких конкретных задач?",
        "Как настраивал eviction policy и что происходит при превышении maxmemory?",
        "Как обеспечивал persistence — RDB, AOF или без неё? Почему именно так?",
    ],
    "postgresql": [
        "Ты упомянул PostgreSQL — как работает MVCC и как это влияет на concurrent reads/writes?",
        "Как использовал EXPLAIN ANALYZE и что именно смотрел в query plan?",
        "Какие типы индексов использовал (B-tree, GIN, partial) и как выбирал?",
    ],
    "kubernetes": [
        "Ты упомянул Kubernetes — как scheduler выбирает node для pod-а и на что смотрит первым?",
        "Чем отличаются liveness и readiness probes и что происходит при failure каждой?",
        "Как настраивал resource requests/limits и что происходит при OOMKill?",
    ],
    "docker": [
        "Ты упомянул Docker — как работают слои образа и почему порядок команд в Dockerfile важен?",
        "Как обеспечивал безопасность контейнеров — non-root user, read-only filesystem?",
    ],
    "elasticsearch": [
        "Ты упомянул Elasticsearch — что такое shard и как выбирал их количество при создании индекса?",
        "Как настраивал маппинг полей и почему это важно для производительности запросов?",
    ],
    "celery": [
        "Ты упомянул Celery — как настраивал retry и что делал с задачами, которые зависали навсегда?",
        "Как мониторил состояние воркеров и очередей в production?",
    ],
    "graphql": [
        "Ты упомянул GraphQL — как решал проблему N+1 запросов к базе данных?",
        "Как реализовывал авторизацию на уровне отдельных полей в резолверах?",
    ],
    "react": [
        "Ты упомянул React — как работает reconciliation и когда stale closure становится проблемой?",
        "Как использовал useMemo/useCallback и как измерял реальный эффект на производительность?",
    ],
    "aws": [
        "Ты упомянул AWS — как настраивал IAM roles и что значит принцип least privilege в твоей практике?",
        "Как оптимизировал costs — Reserved Instances, Spot или другие подходы?",
    ],
    "microservices": [
        "Ты упомянул микросервисы — как обрабатывал distributed transactions между сервисами?",
        "Как реализовывал service discovery и что выбрал — Consul, Eureka, или что-то встроенное?",
    ],
    "grpc": [
        "Ты упомянул gRPC — как управлял версионированием proto-схем при изменении API?",
        "Как обрабатывал streaming и backpressure в gRPC?",
    ],
    "rabbitmq": [
        "Ты упомянул RabbitMQ — как настраивал exchange types (direct/fanout/topic) и для чего?",
        "Как обрабатывал dead letter queue и что делал с сообщениями, которые не обработались?",
    ],
    "nginx": [
        "Ты упомянул nginx — как настраивал upstream и load balancing между серверами?",
        "Как настраивал SSL termination и кэширование статики?",
    ],
    "clickhouse": [
        "Ты упомянул ClickHouse — как выбирал движок таблицы (MergeTree vs ReplicatedMergeTree)?",
        "Как оптимизировал запросы — как работает primary key в ClickHouse в отличие от PostgreSQL?",
    ],
    "airflow": [
        "Ты упомянул Airflow — как настраивал retry логику и SLA для задач?",
        "Как отлаживал зависшие DAG-и и что делал с застрявшими task instance?",
    ],
    "spark": [
        "Ты упомянул Spark — как выбирал между RDD, DataFrame и Dataset API?",
        "Как разбирался с data skew и как его митигировал?",
    ],
}

_TECH_VERIFY_EN: dict[str, list[str]] = {
    "kafka": [
        "You mentioned Kafka — what is a partition and how does a consumer group distribute them across workers?",
        "How did you monitor consumer lag and what did you do when it grew?",
    ],
    "redis": [
        "You mentioned Redis — which data structures did you use and for what specific tasks?",
        "How did you configure the eviction policy and what happens when maxmemory is exceeded?",
    ],
    "postgresql": [
        "You mentioned PostgreSQL — how does MVCC work and how does it affect concurrent reads/writes?",
        "How did you use EXPLAIN ANALYZE and what did you look for in the query plan?",
    ],
    "kubernetes": [
        "You mentioned Kubernetes — how does the scheduler choose a node for a pod?",
        "What's the difference between liveness and readiness probes?",
    ],
    "docker": [
        "You mentioned Docker — how do image layers work and why does command order in Dockerfile matter?",
    ],
    "graphql": [
        "You mentioned GraphQL — how did you solve the N+1 query problem?",
    ],
    "react": [
        "You mentioned React — how does reconciliation work and when does a stale closure become a problem?",
    ],
    "aws": [
        "You mentioned AWS — how did you configure IAM roles following least privilege?",
    ],
    "microservices": [
        "You mentioned microservices — how did you handle distributed transactions?",
    ],
}

_COMPETENCY_MAIN_RU: dict[str, str] = {
    "System Design & Architecture": "Опишите архитектуру самой сложной backend-системы, за которую вы отвечали. Какие trade-offs были ключевыми?",
    "Database Design & Optimization": "Как вы проектировали схему и оптимизировали PostgreSQL или другую БД под реальную нагрузку?",
    "API Design & Protocols": "Как вы проектировали API в production: versioning, contracts, ошибки и обратную совместимость?",
    "Programming Fundamentals": "Расскажите о сложном участке backend-кода, где пришлось выбирать структуру данных или алгоритм под ограничения системы.",
    "DevOps & Infrastructure": "Как вы выкатывали backend-сервисы в production и что считали главным риском в инфраструктуре?",
    "Security & Error Handling": "Как вы строили защиту backend-сервисов: auth, validation, error handling и безопасную деградацию?",
    "Debugging & Problem Decomposition": "Расскажите про production-инцидент или сложный баг: как вы сузили проблему и нашли корневую причину?",
    "Technical Communication": "Как вы объясняли сложное техническое решение команде или бизнесу так, чтобы его реально приняли?",
    "Collaboration & Code Review": "Как вы проводите code review и что для вас признак сильного инженерного обсуждения в команде?",
    "Ownership & Growth Mindset": "Расскажите о ситуации, где вы взяли на себя ответственность за проблемный участок и что улучшили после этого.",
}

_COMPETENCY_MAIN_EN: dict[str, str] = {
    "System Design & Architecture": "Walk me through the architecture of the most complex backend system you owned. What were the key trade-offs?",
    "Database Design & Optimization": "How did you design schema and optimize PostgreSQL or another database under real production load?",
    "API Design & Protocols": "How did you design production APIs: versioning, contracts, error handling, and backward compatibility?",
    "Programming Fundamentals": "Tell me about a backend code path where data structures or algorithm choice really mattered under system constraints.",
    "DevOps & Infrastructure": "How did you ship backend services to production and what infrastructure risks mattered most?",
    "Security & Error Handling": "How did you design backend security: auth, validation, error handling, and safe degradation?",
    "Debugging & Problem Decomposition": "Tell me about a production incident or hard bug: how did you narrow it down and find the root cause?",
    "Technical Communication": "How did you explain a complex technical decision so the team or business actually aligned on it?",
    "Collaboration & Code Review": "How do you run code review and what does strong engineering discussion look like in your team?",
    "Ownership & Growth Mindset": "Tell me about a situation where you took ownership of a problematic area and improved it.",
}

# Depth escalation questions — asked after a strong answer to push further
_DEPTH_ESCALATION_RU = [
    "Какие edge cases ты обрабатывал и что сломалось в первых версиях?",
    "Как это решение держалось под нагрузкой и что первым начало деградировать?",
    "Что бы ты сделал иначе, зная то что знаешь сейчас?",
    "Какие компромиссы ты принял и от чего пришлось отказаться?",
    "Как мониторил это в production и по каким метрикам понимал что всё нормально?",
    "Как это решение взаимодействовало с другими частями системы и где были трения?",
]

_DEPTH_ESCALATION_EN = [
    "What edge cases did you handle and what broke in the first versions?",
    "How did this solution hold up under load and what degraded first?",
    "What would you do differently knowing what you know now?",
    "What trade-offs did you make and what did you have to sacrifice?",
    "How did you monitor this in production and what metrics told you everything was OK?",
]


def extract_mentioned_technologies(text: str) -> set[str]:
    """Extract canonical technology names from candidate answer text.

    Uses word-boundary matching to avoid partial matches (e.g., 'reactivity').
    """
    lower = text.lower()
    found: set[str] = set()
    for keyword, canonical in _TECH_KEYWORD_MAP.items():
        # Escape special chars and use word boundaries
        if re.search(r"\b" + re.escape(keyword) + r"\b", lower):
            found.add(canonical)
    return found


def get_verification_question(tech: str, language: str = "ru") -> str | None:
    """Return first available verification question for a technology."""
    import random
    bank = _TECH_VERIFY_RU if language != "en" else _TECH_VERIFY_EN
    questions = bank.get(tech)
    if not questions:
        return None
    return random.choice(questions)


def get_depth_escalation_question(language: str = "ru") -> str:
    """Return a random depth escalation question."""
    import random
    bank = _DEPTH_ESCALATION_RU if language != "en" else _DEPTH_ESCALATION_EN
    return random.choice(bank)


def _trim_question(text: str, limit: int = _MAX_QUESTION_CHARS) -> str:
    """Trim question text to a safe UI length while keeping it readable."""
    compact = _WHITESPACE_RE.sub(" ", text or "").strip()
    if len(compact) <= limit:
        words = compact.split()
        if len(words) > _MAX_QUESTION_WORDS:
            compact = " ".join(words[:_MAX_QUESTION_WORDS]).rstrip(" ,.;:!?") + "?"
        return compact
    if ". " in compact:
        compact = compact.rsplit(". ", 1)[-1].strip()
    if len(compact) <= limit:
        words = compact.split()
        if len(words) > _MAX_QUESTION_WORDS:
            compact = " ".join(words[:_MAX_QUESTION_WORDS]).rstrip(" ,.;:!?") + "?"
        return compact
    trimmed = compact[:limit]
    if " " in trimmed:
        trimmed = trimmed.rsplit(" ", 1)[0]
    compact = trimmed.rstrip(" ,.;:") + "?"
    words = compact.split()
    if len(words) > _MAX_QUESTION_WORDS:
        compact = " ".join(words[:_MAX_QUESTION_WORDS]).rstrip(" ,.;:!?") + "?"
    return compact


def _question_tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in _QUESTION_TOKEN_RE.findall(text or "")
        if len(token) > 2 and token.lower() not in _QUESTION_TOKEN_STOPWORDS
    }


def _question_similarity(a: str, b: str) -> float:
    ta = _question_tokens(a)
    tb = _question_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(1, len(ta | tb))


def _question_is_repeated(question: str, history: list[dict], *, threshold: float = 0.78) -> bool:
    normalized = _trim_question(question).lower().strip(" ?!.")
    if not normalized:
        return False
    recent_assistant = [
        str(item.get("content", "")).strip()
        for item in history
        if item.get("role") == "assistant" and str(item.get("content", "")).strip()
    ][-4:]
    for previous in recent_assistant:
        prev_normalized = _trim_question(previous).lower().strip(" ?!.")
        if normalized == prev_normalized:
            return True
        if _question_similarity(normalized, prev_normalized) >= threshold:
            return True
    return False


def _question_like_score(candidate: str) -> tuple[int, int]:
    lowered = candidate.lower()
    hint_score = 1 if any(hint in lowered for hint in _QUESTION_WORD_HINTS) else 0
    # Prefer concise direct questions.
    length_penalty = abs(len(candidate) - 90)
    return hint_score, -length_penalty


def _normalize_question_output(raw: str, ctx: InterviewContext) -> str:
    """Normalize LLM output to one concise interview question."""
    cleaned = _MARKUP_RE.sub(" ", raw or "")
    cleaned = cleaned.replace("AI INTERVIEWER", " ")
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    if not cleaned:
        return (
            "Can you describe your most recent relevant project?"
            if ctx.language == "en"
            else "Расскажите о вашем самом релевантном проекте за последнее время?"
        )

    segments = [_WHITESPACE_RE.sub(" ", seg).strip() for seg in _QUESTION_SEGMENT_RE.findall(cleaned)]

    question_candidates: list[str] = []
    for seg in segments:
        normalized = seg.lstrip(" -:;,")
        for sentence in re.split(r"[.!]", normalized):
            candidate = sentence.strip(" ,;:")
            if not candidate:
                continue
            lowered = candidate.lower()
            if any(lowered.startswith(prefix) for prefix in _LEADING_FILLERS):
                continue
            if len(candidate) < 12:
                continue
            question_candidates.append(candidate if candidate.endswith("?") else f"{candidate}?")

    question = ""
    if question_candidates:
        question_candidates.sort(key=_question_like_score, reverse=True)
        question = question_candidates[0]

    if not question:
        first_sentence = ""
        for sentence in re.split(r"[.!]", cleaned):
            candidate = sentence.strip(" ,;:")
            if not candidate:
                continue
            lowered = candidate.lower()
            if any(lowered.startswith(prefix) for prefix in _LEADING_FILLERS):
                continue
            first_sentence = candidate
            break
        if not first_sentence:
            first_sentence = cleaned[:120].strip(" ,;:")
        question = first_sentence if first_sentence.endswith("?") else f"{first_sentence}?"

    if question.count("?") > 1:
        tail = [part.strip() for part in question.split("?") if part.strip()]
        question = f"{tail[-1]}?" if tail else question.split("?", 1)[0].strip() + "?"

    # Drop obvious preambles before direct question wording.
    lowered = question.lower()
    for hint in ("расскажите", "как ", "что ", "почему ", "how ", "what ", "why "):
        pos = lowered.find(hint)
        if pos > 0:
            question = question[pos:].strip(" ,;:")
            break

    return _trim_question(question)


def _resume_anchored_first_question(ctx: InterviewContext) -> str:
    """Deterministic first question for self-intro plus resume context."""
    anchor = ctx.resume_anchor
    if ctx.resume_text:
        if not anchor:
            for raw_line in ctx.resume_text.splitlines():
                line = _WHITESPACE_RE.sub(" ", raw_line).strip(" \t-•|")
                if len(line) < 12:
                    continue
                lowered = line.lower()
                if (
                    "@" in line
                    or lowered.startswith(("email", "телефон", "phone", "github", "linkedin"))
                    or lowered.startswith(("skills", "навыки", "summary", "education", "образование"))
                ):
                    continue
                anchor = line[:72]
                break

    if ctx.language == "en":
        if anchor:
            return _trim_question(
                f"To start, briefly tell me about yourself, your experience, and how '{anchor}' reflects your background: "
                "what was your role and what did you own?"
            )
        return (
            "To start, briefly tell me about yourself, your experience, and the kind of work that best represents your background."
        )

    if anchor:
        return _trim_question(
            f"Для начала кратко расскажите о себе, своём опыте и о том, как опыт «{anchor}» вас лучше всего характеризует: "
            "какая у вас была роль и за что вы отвечали?"
        )
    return (
        "Для начала кратко расскажите о себе, своём опыте и о том, какой тип задач лучше всего отражает ваш профессиональный путь."
    )


def _resume_anchored_main_question(ctx: InterviewContext) -> str | None:
    if not ctx.resume_anchor:
        return None

    if ctx.language == "en":
        if ctx.verification_target:
            return _trim_question(
                f"You listed '{ctx.resume_anchor}' in your resume. What was your role there and where exactly did you use {ctx.verification_target}?"
            )
        return _trim_question(
            f"You listed '{ctx.resume_anchor}' in your resume. What was the hardest technical decision there and why did you make it?"
        )

    if ctx.verification_target:
        return _trim_question(
            f"В резюме у вас указан опыт «{ctx.resume_anchor}». Какую роль вы там играли и где именно использовали {ctx.verification_target}?"
        )
    return _trim_question(
        f"В резюме у вас указан опыт «{ctx.resume_anchor}». Какое самое сложное техническое решение вы там принимали и почему?"
    )


def _behavioral_closing_question(ctx: InterviewContext) -> str:
    if ctx.language == "en":
        return _trim_question(
            "To close, tell me about a difficult work situation: how you communicated, handled pressure, and influenced the outcome for the team."
        )
    return _trim_question(
        "В завершение расскажите о сложной рабочей ситуации: как вы коммуницировали, справлялись со стрессом и повлияли на итог для команды?"
    )


def _resume_claim_probe_question(ctx: InterviewContext) -> str | None:
    tech = ctx.verification_target or ctx.pending_verification
    if not tech:
        return None

    verification = get_verification_question(tech, ctx.language)
    if ctx.language == "en":
        if verification:
            return _trim_question(
                f"Your resume suggests experience with {tech}. Let's verify it through one concrete point: {verification}"
            )
        return _trim_question(
            f"Your resume suggests experience with {tech}. What exactly did you do with it in a real project?"
        )

    if verification:
        return _trim_question(
            f"В резюме заявлен опыт с {tech}. Давайте проверим это на конкретике: {verification}"
        )
    return _trim_question(
        f"В резюме заявлен опыт с {tech}. Что именно вы с ним делали в реальном проекте?"
    )


def _competency_anchored_main_question(ctx: InterviewContext, *, preference_index: int = 0) -> str | None:
    competencies = [item for item in (ctx.competency_targets or []) if item]
    if not competencies:
        return None
    target_idx = preference_index if 0 <= preference_index < len(competencies) else 0
    primary = competencies[target_idx]
    bank = _COMPETENCY_MAIN_EN if ctx.language == "en" else _COMPETENCY_MAIN_RU
    base = bank.get(primary)
    if not base:
        return None

    return _trim_question(base)


def _fallback_question_for_context(ctx: InterviewContext, *, prefer_secondary_main_topic: bool = False) -> str | None:
    if ctx.question_type == "followup":
        return _trim_question(get_fallback_followup(ctx.shallow_reason or "no_depth_indicators", ctx.language))
    if ctx.question_type == "claim_verification":
        probe = _resume_claim_probe_question(ctx)
        return _trim_question(probe) if probe else None
    if ctx.question_type == "verification":
        tech = ctx.pending_verification or ctx.verification_target or ""
        verification = get_verification_question(tech, ctx.language)
        if verification:
            return _trim_question(verification)
        return None
    if ctx.question_type in {"deep_technical", "edge_cases"}:
        if ctx.module_type == "system_design":
            system_design_depth = _system_design_depth_question(ctx)
            if system_design_depth:
                return system_design_depth
        if ctx.module_type == "coding_task":
            coding_task_depth = _coding_task_depth_question(ctx)
            if coding_task_depth:
                return coding_task_depth
        if ctx.module_type == "sql_live":
            sql_live_depth = _sql_live_depth_question(ctx)
            if sql_live_depth:
                return sql_live_depth
        return _trim_question(get_depth_escalation_question(ctx.language))
    if ctx.module_type == "system_design":
        system_design_main = _system_design_main_question(ctx)
        if system_design_main:
            return system_design_main
    if ctx.module_type == "coding_task":
        coding_task_main = _coding_task_main_question(ctx)
        if coding_task_main:
            return coding_task_main
    if ctx.module_type == "sql_live":
        sql_live_main = _sql_live_main_question(ctx)
        if sql_live_main:
            return sql_live_main

    anchored = _competency_anchored_main_question(ctx, preference_index=1 if prefer_secondary_main_topic else 0)
    if anchored:
        return anchored
    resume_anchored = _resume_anchored_main_question(ctx)
    if resume_anchored:
        return resume_anchored
    return (
        "Can you share one concrete production case and explain your technical trade-off?"
        if ctx.language == "en"
        else "Приведите один конкретный production-кейс и объясните, какой технический компромисс вы выбрали?"
    )


def _system_design_main_question(ctx: InterviewContext) -> str | None:
    if ctx.module_type != "system_design":
        return None

    scenario_title = ctx.module_scenario_title or (
        "the system design scenario" if ctx.language == "en" else "сценарий system design"
    )
    match ctx.module_stage_key:
        case "requirements":
            question = (
                f'For the scenario "{scenario_title}", which requirements, traffic assumptions, and constraints would you clarify first?'
                if ctx.language == "en"
                else f'Для сценария «{scenario_title}» какие требования, объёмы нагрузки и ограничения вы бы уточнили вначале?'
            )
        case "high_level_design":
            question = (
                f'Now outline the high-level architecture for "{scenario_title}": main services, data flow, storage, and scaling choices.'
                if ctx.language == "en"
                else f'Теперь опишите high-level архитектуру для «{scenario_title}»: основные сервисы, поток данных, хранилища и масштабирование.'
            )
        case "tradeoffs":
            question = (
                f'What are the main trade-offs in your design for "{scenario_title}", and what would break first at 10x load?'
                if ctx.language == "en"
                else f'Какие ключевые trade-offs есть в вашем дизайне для «{scenario_title}» и что сломается первым при нагрузке x10?'
            )
        case _:
            question = (
                f'Walk me through how you would design "{scenario_title}" from requirements to key technical trade-offs.'
                if ctx.language == "en"
                else f'Проведите меня по тому, как вы бы спроектировали «{scenario_title}»: от требований до ключевых технических trade-offs.'
            )
    return _trim_question(question)


def _system_design_depth_question(ctx: InterviewContext) -> str | None:
    if ctx.module_type != "system_design":
        return None

    scenario_title = ctx.module_scenario_title or (
        "the system design scenario" if ctx.language == "en" else "этот system design сценарий"
    )
    match ctx.module_stage_key:
        case "requirements":
            question = (
                f'Which assumption in "{scenario_title}" is the riskiest, and how would you validate it before implementation?'
                if ctx.language == "en"
                else f'Какое допущение в сценарии «{scenario_title}» самое рискованное и как вы бы проверили его до реализации?'
            )
        case "high_level_design":
            question = (
                f'In your design for "{scenario_title}", what is the first bottleneck and how would you mitigate it?'
                if ctx.language == "en"
                else f'В вашем дизайне для «{scenario_title}» где возникнет первое узкое место и как вы бы его снимали?'
            )
        case "tradeoffs":
            question = (
                f'Which trade-off in "{scenario_title}" would you defend most strongly, and why not the main alternative?'
                if ctx.language == "en"
                else f'Какой trade-off в «{scenario_title}» вы бы защищали сильнее всего и почему не выбрали главный альтернативный вариант?'
            )
        case _:
            question = (
                f'Which part of your design for "{scenario_title}" would you revisit first after launch, and why?'
                if ctx.language == "en"
                else f'Какую часть вашего дизайна для «{scenario_title}» вы бы пересмотрели первой после запуска и почему?'
            )
    return _trim_question(question)


def _coding_task_main_question(ctx: InterviewContext) -> str | None:
    if ctx.module_type != "coding_task":
        return None

    scenario_title = ctx.module_scenario_title or (
        "the coding task" if ctx.language == "en" else "coding task"
    )
    match ctx.module_stage_key:
        case "task_brief":
            question = (
                f'For the task "{scenario_title}", how would you break it down: inputs, outputs, edge cases, and implementation plan?'
                if ctx.language == "en"
                else f'Для задачи «{scenario_title}» как вы её декомпозируете: входы, выходы, edge cases и план реализации?'
            )
        case "implementation":
            question = (
                f'Please paste the core implementation for "{scenario_title}" and explain the key function or state flow.'
                if ctx.language == "en"
                else f'Пожалуйста, вставьте core implementation для «{scenario_title}» и объясните ключевую функцию или поток состояния.'
            )
        case "review":
            question = (
                f'How would you test your solution for "{scenario_title}", what is the complexity, and what would you improve next?'
                if ctx.language == "en"
                else f'Как бы вы протестировали решение для «{scenario_title}», какая у него сложность и что бы вы улучшили следующим?'
            )
        case _:
            question = (
                f'Walk me through how you would solve "{scenario_title}" and show the most important code.'
                if ctx.language == "en"
                else f'Проведите меня по тому, как вы бы решали «{scenario_title}», и покажите самый важный фрагмент кода.'
            )
    return _trim_question(question)


def _coding_task_depth_question(ctx: InterviewContext) -> str | None:
    if ctx.module_type != "coding_task":
        return None

    scenario_title = ctx.module_scenario_title or (
        "the coding task" if ctx.language == "en" else "эту coding task задачу"
    )
    match ctx.module_stage_key:
        case "task_brief":
            question = (
                f'Which edge case in "{scenario_title}" is easiest to miss, and how would your design catch it early?'
                if ctx.language == "en"
                else f'Какой edge case в задаче «{scenario_title}» проще всего пропустить и как ваш дизайн поймает его заранее?'
            )
        case "implementation":
            question = (
                f'In your code for "{scenario_title}", which branch or data structure matters most, and why did you choose it?'
                if ctx.language == "en"
                else f'В вашем коде для «{scenario_title}» какая ветка или структура данных наиболее критична и почему вы выбрали именно её?'
            )
        case "review":
            question = (
                f'What failure case would still worry you in "{scenario_title}", and which test would you add first?'
                if ctx.language == "en"
                else f'Какой failure case в задаче «{scenario_title}» всё ещё вызывает у вас тревогу и какой тест вы бы добавили первым?'
            )
        case _:
            question = (
                f'Which part of your solution for "{scenario_title}" is the weakest today, and how would you harden it?'
                if ctx.language == "en"
                else f'Какая часть вашего решения для «{scenario_title}» сегодня самая слабая и как бы вы её усилили?'
            )
    return _trim_question(question)


def _sql_live_main_question(ctx: InterviewContext) -> str | None:
    if ctx.module_type != "sql_live":
        return None

    scenario_title = ctx.module_scenario_title or (
        "the SQL task" if ctx.language == "en" else "SQL-задачу"
    )
    match ctx.module_stage_key:
        case "schema_review":
            question = (
                f'For the SQL task "{scenario_title}", which tables, joins, filters, and aggregates do you need before you write the query?'
                if ctx.language == "en"
                else f'Для SQL-задачи «{scenario_title}» какие таблицы, join, фильтры и агрегаты вам нужны до написания запроса?'
            )
        case "query_authoring":
            question = (
                f'Please write the SQL query for "{scenario_title}" and explain the key join, grouping, and ordering choices.'
                if ctx.language == "en"
                else f'Пожалуйста, напишите SQL-запрос для «{scenario_title}» и объясните ключевые решения по join, grouping и ordering.'
            )
        case "result_review":
            question = (
                f'How would you validate the result for "{scenario_title}", and what would you optimize first if the dataset grows?'
                if ctx.language == "en"
                else f'Как вы бы проверили результат для «{scenario_title}» и что бы оптимизировали первым при росте объёма данных?'
            )
        case _:
            question = (
                f'Walk me through how you would solve "{scenario_title}" in SQL and what result shape you expect.'
                if ctx.language == "en"
                else f'Проведите меня по тому, как вы бы решили «{scenario_title}» на SQL и какую форму результата ожидаете.'
            )
    return _trim_question(question)


def _sql_live_depth_question(ctx: InterviewContext) -> str | None:
    if ctx.module_type != "sql_live":
        return None

    scenario_title = ctx.module_scenario_title or (
        "the SQL task" if ctx.language == "en" else "эту SQL-задачу"
    )
    match ctx.module_stage_key:
        case "schema_review":
            question = (
                f'Which row or business rule in "{scenario_title}" is easiest to mis-handle, and how would you account for it in the query design?'
                if ctx.language == "en"
                else f'Какую строку или бизнес-правило в задаче «{scenario_title}» проще всего обработать неправильно и как вы учтёте это в дизайне запроса?'
            )
        case "query_authoring":
            question = (
                f'In your SQL for "{scenario_title}", which clause does the real correctness work, and why did you structure it that way?'
                if ctx.language == "en"
                else f'В вашем SQL для «{scenario_title}» какой clause делает основную работу по корректности и почему вы построили запрос именно так?'
            )
        case "result_review":
            question = (
                f'What incorrect result would still worry you in "{scenario_title}", and which validation query or test would you run first?'
                if ctx.language == "en"
                else f'Какой некорректный результат в задаче «{scenario_title}» всё ещё вызывает у вас сомнение и какой validation query или тест вы бы запустили первым?'
            )
        case _:
            question = (
                f'Which part of your SQL solution for "{scenario_title}" is the most fragile today, and how would you harden it?'
                if ctx.language == "en"
                else f'Какая часть вашего SQL-решения для «{scenario_title}» сейчас самая хрупкая и как бы вы её усилили?'
            )
    return _trim_question(question)


# ---------------------------------------------------------------------------
# LLM implementation (Groq)
# ---------------------------------------------------------------------------

def _build_system_prompt(ctx: InterviewContext) -> str:
    role_label = _ROLE_LABELS.get(ctx.target_role, ctx.target_role.replace("_", " "))

    prompt = (
        f"## ПРИОРИТЕТ\n"
        f"Ты оцениваешь компетенции роли «{role_label}».\n"
        f"Резюме — ТОЛЬКО контекст для персонализации вопросов.\n"
        f"Никогда не уходи от компетенций роли из-за содержания резюме.\n\n"

        f"Ты — опытный технический интервьюер, ведущий живое собеседование "
        f"на позицию «{role_label}».\n\n"

        "## Твоя задача\n"
        "Провести настоящий профессиональный разговор, а не анкету. "
        "Ты оцениваешь реальную глубину знаний и практический опыт.\n\n"

        "## Персонализация (контекст, не оценка)\n"
        "Если предоставлено резюме — изучи его внимательно:\n"
        "- Упоминай конкретные компании, проекты, технологии и сроки из CV.\n"
        "- Вместо общего «Расскажи про базы данных» спроси: «Я вижу, ты 2 года "
        "работал с PostgreSQL в [Компания] — какие были нагрузки и как вы их решали?»\n"
        "- Если в резюме есть пробел, смена направления или нетипичный проект — "
        "спроси об этом.\n"
        "- Если резюме не релевантно позиции — отметь это в вопросе и задай "
        "технический вопрос по роли.\n\n"

        "## Реакция на ответы кандидата\n"
        "- Ответ поверхностный (нет конкретных примеров) → попроси конкретный случай: "
        "«Можешь привести конкретный случай из практики?» Не переходи к следующей теме.\n"
        "- Ответ слишком короткий (1-2 предложения) → переформулируй вопрос уже: "
        "«Давай конкретнее — какой именно инструмент/подход ты использовал и какой был результат?»\n"
        "- Упомянута конкретная технология → уточни детали: "
        "«Ты упомянул Kafka — как выстраивал топологию, как боролся с consumer lag?»\n"
        "- Описан проект → уточни личный вклад, технические решения и их последствия.\n"
        "- Ответ полный и конкретный → переходи к следующей теме естественно.\n"
        "- Ответ явная чушь, несерьёзный или противоречит предыдущим ответам → "
        "задай уточняющий вопрос по той же теме: «Ты раньше говорил X, а сейчас Y — "
        "можешь пояснить?»\n\n"

        "## Формат ответа\n"
        "- Только ОДИН вопрос. Без нумерации.\n"
        "- Коротко: 1 предложение, максимум 170 символов.\n"
        "- НЕ начинай с оценки («Отлично!», «Хороший ответ», «Интересно»).\n"
        "- НЕ повторяй вопрос. НЕ давай советов и комментариев.\n"
    )

    if ctx.candidate_memory:
        memory_lines = "\n".join(f"- {item}" for item in ctx.candidate_memory[-8:])
        prompt += (
            "\n## Память текущей сессии\n"
            "Учитывай уже озвученные факты кандидата. Не переспрашивай то, что уже подробно раскрыто, "
            "если нет новой цели верификации или углубления.\n"
            f"{memory_lines}\n"
        )

    if ctx.module_type == "system_design":
        prompt += (
            "\n## Режим модуля: System Design\n"
            "Ты ведёшь сценарное system design интервью. Держись одного сценария до конца модуля.\n"
            "Не переключайся обратно на resume-driven вопросы и не уводи разговор в общие карьерные темы.\n"
        )
        if ctx.module_scenario_title:
            prompt += f"Сценарий: {ctx.module_scenario_title}\n"
        if ctx.module_scenario_prompt:
            prompt += f"Контекст сценария: {ctx.module_scenario_prompt}\n"
        if ctx.module_stage_title:
            prompt += f"Текущий этап: {ctx.module_stage_title}\n"
        if ctx.module_stage_prompt:
            prompt += f"Фокус этапа: {ctx.module_stage_prompt}\n"
    if ctx.module_type == "coding_task":
        prompt += (
            "\n## Режим модуля: Coding Task\n"
            "Ты ведёшь coding task интервью. Кандидат может вставлять код, псевдокод или структурированное решение прямо в чат.\n"
            "Держись одного задания до конца модуля. Не переключайся обратно на resume-driven вопросы и не уводи разговор в общие карьерные темы.\n"
            "Если кандидат уже показал код, проси объяснить логику, edge cases, тесты и trade-offs, а не переписывать всё заново.\n"
        )
        if ctx.module_scenario_title:
            prompt += f"Задание: {ctx.module_scenario_title}\n"
        if ctx.module_scenario_prompt:
            prompt += f"Описание задачи: {ctx.module_scenario_prompt}\n"
    if ctx.module_type == "sql_live":
        prompt += (
            "\n## Режим модуля: SQL Live\n"
            "Ты ведёшь SQL task интервью. Кандидат может вставлять SQL-запрос прямо в workspace или в чат.\n"
            "Держись одного SQL-сценария до конца модуля. Не переключайся обратно на resume-driven вопросы и не уводи разговор в общие карьерные темы.\n"
            "Если кандидат уже написал запрос, проси объяснить логику join/filter/grouping, валидацию результата и возможные оптимизации.\n"
        )
        if ctx.module_scenario_title:
            prompt += f"SQL-задача: {ctx.module_scenario_title}\n"
        if ctx.module_scenario_prompt:
            prompt += f"Описание SQL-задачи: {ctx.module_scenario_prompt}\n"
        if ctx.module_stage_title:
            prompt += f"Текущий этап: {ctx.module_stage_title}\n"
        if ctx.module_stage_prompt:
            prompt += f"Фокус этапа: {ctx.module_stage_prompt}\n"

    # Non-main question types — override phase-based instructions and return early
    if ctx.question_type != "main":
        is_ru = ctx.language != "en"

        # Contradiction context (shown for all non-main types if flags exist)
        if ctx.contradiction_flags:
            flags_str = "; ".join(ctx.contradiction_flags)
            if is_ru:
                prompt += (
                    f"\n## Выявленные несоответствия\n"
                    f"Зафиксировано: {flags_str}\n"
                    "Кандидат заявил о знании технологии но не смог ответить на базовые вопросы. "
                    "Это сигнал возможного преувеличения опыта.\n"
                )
            else:
                prompt += (
                    f"\n## Detected inconsistencies\n"
                    f"Flagged: {flags_str}\n"
                    "Candidate claimed knowledge but couldn't answer basic questions. "
                    "Possible exaggeration of experience.\n"
                )

        # ── FOLLOW-UP (shallow answer) ─────────────────────────────────────
        if ctx.question_type == "followup":
            _reason_hint_ru = {
                "too_short": "Кандидат ответил очень коротко (меньше 10 слов), тема не раскрыта.",
                "no_depth_indicators": "Кандидат ответил обще: нет конкретных примеров, нет цифр, нет 'как/почему'.",
                "short_and_generic": "Кандидат дал короткий общий ответ без реального проектного контекста.",
            }.get(ctx.shallow_reason, "Кандидат не раскрыл тему достаточно глубоко.")

            _reason_hint_en = {
                "too_short": "The candidate's answer was very short (under 10 words) — topic not explored.",
                "no_depth_indicators": "The candidate answered generically: no real examples, no numbers, no 'how' or 'why'.",
                "short_and_generic": "The candidate gave a short generic answer without real project context.",
            }.get(ctx.shallow_reason, "The candidate did not explore the topic deeply enough.")

            attempt_label = f"{ctx.follow_up_count + 1}/2"
            if is_ru:
                prompt += (
                    f"\n## Режим: Follow-up (попытка {attempt_label})\n"
                    f"Ситуация: {_reason_hint_ru}\n\n"
                    "Задача: задать ОДИН короткий уточняющий вопрос (максимум 140 символов).\n"
                    "НЕ переходи на другую тему. НЕ начинай с оценки. НЕ повторяй вопрос дословно.\n"
                    "Зацепись за что-то конкретное из последнего ответа.\n\n"
                    "Стратегии:\n"
                    "- Если кандидат честно говорит что не делал/не помнит → не дави, а мягко смени рамку: "
                    "'Окей, если лично не делал, как бы ты подошёл к такой задаче?'\n"
                    "- Короткий ответ → 'Расскажи подробнее — как именно это работало?'\n"
                    "- Нет примера → 'Можешь привести конкретный случай из практики?'\n"
                    "- Нет метрик → 'Какой был масштаб и какой конкретный результат?'\n"
                    "- Упомянута технология → 'Ты упомянул [X] — как именно использовал и с какими проблемами столкнулся?'\n"
                    "- Нет 'почему' → 'Почему именно этот подход, а не альтернативы?'\n"
                )
            else:
                prompt += (
                    f"\n## Mode: Follow-up (attempt {attempt_label})\n"
                    f"Situation: {_reason_hint_en}\n\n"
                    "Task: generate ONE short probing question (max 140 characters).\n"
                    "Do NOT switch topics. Do NOT start with praise. Do NOT repeat verbatim.\n"
                    "Latch onto something specific in the last answer.\n\n"
                    "Strategies:\n"
                    "- If the candidate honestly says they haven't done this / don't remember, do not push harder. Reframe: "
                    "'If you haven't done it directly, how would you approach it?'\n"
                    "- Short answer → 'Walk me through that — how exactly did it work?'\n"
                    "- No example → 'Can you give a concrete example from your work?'\n"
                    "- No metrics → 'What was the scale and what was the measurable result?'\n"
                    "- Tech mentioned → 'You mentioned [X] — how exactly did you use it and what problems came up?'\n"
                    "- No 'why' → 'Why that approach and not the alternatives?'\n"
                )

        # ── VERIFICATION (checking claimed technology knowledge) ───────────
        elif ctx.question_type == "verification" and ctx.pending_verification:
            tech = ctx.pending_verification
            verify_q = get_verification_question(tech, ctx.language)
            if is_ru:
                prompt += (
                    f"\n## Режим: Верификация знания — «{tech}»\n"
                    "Кандидат упомянул эту технологию. Нужно проверить реальную глубину знаний.\n\n"
                    "Задача: задать ОДИН проверочный вопрос по конкретному механизму этой технологии.\n"
                    "НЕ спрашивай 'работал ли ты с X' — кандидат уже сказал что да.\n"
                    "Спроси о КОНКРЕТНОМ механизме, настройке или проблеме.\n\n"
                )
                if verify_q:
                    prompt += f"Рекомендуемый вопрос (можешь адаптировать под контекст): {verify_q}\n"
            else:
                prompt += (
                    f"\n## Mode: Knowledge verification — '{tech}'\n"
                    "The candidate mentioned this technology. Check the actual depth of knowledge.\n\n"
                    "Task: ask ONE question about a specific mechanism, configuration, or problem.\n"
                    "Do NOT ask 'have you worked with X' — they already said yes.\n"
                    "Ask about a SPECIFIC internal mechanism, setting, or edge case.\n\n"
                )
                if verify_q:
                    prompt += f"Suggested question (adapt to context): {verify_q}\n"

        elif ctx.question_type == "claim_verification":
            tech = ctx.verification_target or ctx.pending_verification or ""
            probe_q = _resume_claim_probe_question(ctx)
            if is_ru:
                prompt += (
                    f"\n## Режим: Проверка заявленного опыта — «{tech}»\n"
                    "Эта технология уже присутствует в резюме кандидата, но текущий ответ не даёт убедительной конкретики.\n\n"
                    "Задача: задать ОДИН короткий вопрос, который проверяет реальный личный опыт, "
                    "а не просто строчку в CV. Не дави и не обвиняй.\n\n"
                )
                if probe_q:
                    prompt += f"Направление: {probe_q}\n"
            else:
                prompt += (
                    f"\n## Mode: Resume claim verification — '{tech}'\n"
                    "This technology is already present in the candidate's resume, but the current answer lacks convincing specifics.\n\n"
                    "Task: ask ONE short question that checks for real hands-on experience, "
                    "not just a resume keyword. Do not be accusatory.\n\n"
                )
                if probe_q:
                    prompt += f"Direction: {probe_q}\n"

        # ── DEEP TECHNICAL (strong answer, push deeper) ────────────────────
        elif ctx.question_type == "deep_technical":
            depth_q = get_depth_escalation_question(ctx.language)
            if is_ru:
                prompt += (
                    "\n## Режим: Углубление\n"
                    "Кандидат дал хороший ответ. Теперь проверяем глубину: edge cases, "
                    "production experience, trade-offs.\n\n"
                    "Задача: задать ОДИН вопрос, который раскрывает настоящий боевой опыт.\n"
                    "Фокус на: что сломалось, что переделали, какие компромиссы, что мониторили.\n\n"
                    f"Направление (можешь адаптировать): {depth_q}\n"
                )
            else:
                prompt += (
                    "\n## Mode: Depth escalation\n"
                    "The candidate gave a good answer. Now test the depth: edge cases, "
                    "production experience, trade-offs.\n\n"
                    "Task: ask ONE question that reveals real production experience.\n"
                    "Focus on: what broke, what was reworked, what trade-offs, what was monitored.\n\n"
                    f"Direction (adapt as needed): {depth_q}\n"
                )

        # ── EDGE CASES ─────────────────────────────────────────────────────
        elif ctx.question_type == "edge_cases":
            if is_ru:
                prompt += (
                    "\n## Режим: Edge Cases\n"
                    "Кандидат показал хорошее базовое знание. Проверяем граничные случаи.\n\n"
                    "Задача: задать вопрос про edge case, failure mode или нетипичную ситуацию.\n"
                    "Примеры: 'Что происходит при потере соединения?', "
                    "'Как ведёт себя система при 10x нагрузке?', "
                    "'Что если клиент прислал некорректные данные?'\n"
                )
            else:
                prompt += (
                    "\n## Mode: Edge Cases\n"
                    "The candidate showed solid baseline knowledge. Now test boundary conditions.\n\n"
                    "Task: ask about an edge case, failure mode, or atypical situation.\n"
                    "Examples: 'What happens when the connection is lost?', "
                    "'How does the system behave at 10x load?', "
                    "'What if the client sends malformed data?'\n"
                )

        return prompt

    # Phase-based instructions
    is_first = ctx.question_number == 1
    is_last = ctx.question_number == ctx.max_questions
    is_late = ctx.question_number >= ctx.max_questions - 2

    if is_first:
        prompt += (
            "\n## Фаза: Приветствие (первый вопрос)\n"
            "Кратко представься как AI-интервьюер на позицию, поприветствуй кандидата. "
            "Затем задай первый вопрос, опираясь на самый значимый опыт из резюме. "
            "Формат: приветствие + вопрос в одном сообщении.\n"
        )
    elif is_last:
        prompt += (
            "\n## Фаза: Завершение (последний вопрос)\n"
            "Это последний вопрос. Задай поведенческий/ситуационный вопрос (формат STAR). "
            "После вопроса добавь: «Это наш последний вопрос. Есть ли что-то, "
            "что вы хотели бы добавить о своём опыте?»\n"
        )
    elif is_late:
        prompt += (
            "\n## Фаза: Проблемные сценарии\n"
            "Задай сценарный/ситуационный вопрос: описание проблемы, debugging-задачу "
            "или кейс из реальной практики. Оцени аналитическое мышление.\n"
        )
    else:
        prompt += (
            "\n## Фаза: Техническое ядро\n"
            "Задай глубокий технический вопрос. Проверяй не только знания, "
            "но и умение рассуждать о trade-offs.\n"
        )

    # Competency targeting
    if ctx.competency_targets:
        from app.ai.competencies import get_competencies, SCORING_RUBRIC
        all_comps = {c.name: c for c in get_competencies(ctx.target_role)}
        targets_info = []
        for name in ctx.competency_targets:
            comp = all_comps.get(name)
            if comp:
                targets_info.append(f"- **{comp.name}** ({comp.category}): {comp.description}")

        if targets_info:
            rubric_lines = []
            for (lo, hi), desc in SCORING_RUBRIC.items():
                rubric_lines.append(f"  {lo}-{hi}: {desc}")
            prompt += (
                "\n## Целевые компетенции для этого вопроса\n"
                "Этот вопрос должен оценивать следующие компетенции:\n"
                + "\n".join(targets_info) + "\n\n"
                "Шкала оценки (для твоего понимания, не озвучивай кандидату):\n"
                + "\n".join(rubric_lines) + "\n"
                "Формулируй вопрос так, чтобы сильный ответ (7-8) требовал конкретных "
                "примеров из практики с описанием trade-offs.\n"
            )

    # Template questions as a structured plan
    if ctx.template_questions:
        n = len(ctx.template_questions)
        topics = "\n".join(
            f"  {i+1}. {q}" for i, q in enumerate(ctx.template_questions)
        )
        prompt += (
            f"\n## Структура собеседования (темы-ориентиры)\n"
            f"Всего {n} тем, по одной на каждый вопрос. Прорабатывай их по порядку, "
            f"но формулируй каждый вопрос исходя из резюме и предыдущих ответов. "
            f"Это план — не скрипт для зачитывания.\n"
            f"{topics}\n\n"
            f"Сейчас задаёшь вопрос по теме №{ctx.question_number} из {n}.\n"
        )
    else:
        prompt += (
            f"\n## Структура\n"
            f"Это вопрос {ctx.question_number} из {ctx.max_questions}.\n"
        )

    # Resume
    if ctx.resume_text:
        prompt += f"\n## Резюме кандидата\n{ctx.resume_text[:4000]}\n"

    if ctx.resume_anchor:
        prompt += (
            "\n## Резюме-опора для этой темы\n"
            f"Если уместно, опирайся на этот фрагмент опыта: {ctx.resume_anchor}\n"
        )

    if ctx.diversification_hint:
        prompt += (
            "\n## Диверсификация следующей темы\n"
            f"{ctx.diversification_hint}\n"
        )

    if ctx.verification_target and ctx.question_type == "main":
        prompt += (
            "\n## Что желательно верифицировать\n"
            f"Если это естественно для темы, проверь реальный опыт с технологией: {ctx.verification_target}\n"
        )

    # Language
    if ctx.language == "en":
        prompt += "\n## Language\nConduct this interview entirely in English.\n"

    return prompt


class LLMInterviewer:
    """Generates adaptive interview questions via Groq API."""

    def __init__(self, client: AsyncGroq) -> None:
        self._client = client

    async def get_next_question(self, ctx: InterviewContext, model_override: str | None = None) -> str:
        # First question: always deterministic (faster, no LLM needed)
        if ctx.module_type == "system_design" and ctx.question_type == "main":
            system_design_main = _system_design_main_question(ctx)
            if system_design_main:
                return system_design_main
        if ctx.module_type == "coding_task" and ctx.question_type == "main":
            coding_task_main = _coding_task_main_question(ctx)
            if coding_task_main:
                return coding_task_main
        if ctx.module_type == "sql_live" and ctx.question_type == "main":
            sql_live_main = _sql_live_main_question(ctx)
            if sql_live_main:
                return sql_live_main
        if ctx.topic_phase == "intro" and not ctx.is_followup_mode:
            return _resume_anchored_first_question(ctx)
        if ctx.topic_phase == "behavioral_closing" and ctx.question_type == "main":
            return _behavioral_closing_question(ctx)
        if ctx.question_type == "main" and ctx.topic_phase == "resume_followup" and ctx.resume_anchor:
            anchored = _resume_anchored_main_question(ctx)
            if anchored and not _question_is_repeated(anchored, ctx.message_history):
                return anchored
        if ctx.question_type == "main":
            anchored_main = _competency_anchored_main_question(ctx)
            if anchored_main and not _question_is_repeated(anchored_main, ctx.message_history):
                return anchored_main
            alternative_main = _fallback_question_for_context(ctx, prefer_secondary_main_topic=True)
            if alternative_main and not _question_is_repeated(alternative_main, ctx.message_history):
                return alternative_main
        if ctx.question_type == "claim_verification":
            probe = _resume_claim_probe_question(ctx)
            if probe and not _question_is_repeated(probe, ctx.message_history):
                return probe

        system = _build_system_prompt(ctx)

        messages: list[dict] = [
            {"role": "system", "content": system},
            {"role": "user", "content": "Начни собеседование." if ctx.language != "en" else "Start the interview."},
        ]
        for msg in ctx.message_history:
            role = "assistant" if msg["role"] == "assistant" else "user"
            messages.append({"role": role, "content": msg["content"]})

        # Non-main question types: shorter output, slightly higher temperature for variety
        is_non_main = ctx.question_type != "main"
        max_tokens = 96 if is_non_main else 140
        temperature = 0.65 if is_non_main else 0.5

        try:
            resolved_model = resolve_llm_runtime_model(model_override)
            try:
                response = await self._client.chat.completions.create(
                    model=resolved_model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    messages=messages,
                )
            except Exception:
                if resolved_model != DEFAULT_LLM_MODEL:
                    logger.exception("Preferred interviewer model failed, retrying with default model")
                    response = await self._client.chat.completions.create(
                        model=DEFAULT_LLM_MODEL,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        messages=messages,
                    )
                else:
                    raise
            raw = response.choices[0].message.content.strip()
            normalized = _normalize_question_output(raw, ctx)
            if _question_is_repeated(normalized, ctx.message_history):
                fallback = _fallback_question_for_context(ctx, prefer_secondary_main_topic=True)
                if fallback and not _question_is_repeated(fallback, ctx.message_history):
                    return fallback
            return normalized
        except Exception:
            if settings.allow_mock_ai:
                logger.exception("Interviewer LLM failed, using deterministic fallback question")
                return await MockInterviewer().get_next_question(ctx, model_override=model_override)
            logger.exception("Interviewer LLM failed")
            raise RuntimeError("AI interviewer request failed")


# ---------------------------------------------------------------------------
# Mock fallback (no API key)
# ---------------------------------------------------------------------------

_QUESTIONS: dict[str, list[str]] = {
    "frontend_engineer": [
        "Расскажите о себе и своём опыте в frontend-разработке.",
        "Как вы подходите к оптимизации производительности веб-приложений?",
        "Объясните разницу между SSR, SSG и CSR. Когда вы используете каждый подход?",
        "Как вы организуете состояние в крупном React/Vue/Angular приложении?",
        "Опишите ваш опыт с accessibility (a11y). Как вы обеспечиваете доступность интерфейсов?",
        "Как вы подходите к тестированию frontend-кода?",
        "Расскажите о сложной UI-задаче, которую вам пришлось решить.",
        "Как вы следите за новинками во frontend и принимаете решения о внедрении новых технологий?",
    ],
    "devops_engineer": [
        "Расскажите о себе и своём опыте в DevOps.",
        "Опишите CI/CD пайплайн, который вы настраивали. Какие инструменты использовали?",
        "Как вы подходите к мониторингу и алертингу production-систем?",
        "Расскажите о вашем опыте с Kubernetes или другими оркестраторами контейнеров.",
        "Как вы обеспечиваете безопасность инфраструктуры? Приведите конкретные практики.",
        "Опишите инцидент в production, в котором вы участвовали. Как вы его решали?",
        "Как вы управляете конфигурацией и секретами в разных окружениях?",
        "Как вы подходите к disaster recovery и обеспечению высокой доступности?",
    ],
    "data_scientist": [
        "Расскажите о себе и своём опыте в Data Science.",
        "Опишите проект ML, который вы довели до production. Какие были основные вызовы?",
        "Как вы выбираете метрики для оценки модели? Приведите пример из практики.",
        "Как вы обрабатываете пропущенные данные и выбросы в датасете?",
        "Объясните разницу между underfitting и overfitting. Как вы с ними боретесь?",
        "Расскажите о вашем опыте с A/B-тестированием.",
        "Как вы объясняете результаты модели нетехническим стейкхолдерам?",
        "Как вы следите за качеством модели в production (model drift, data drift)?",
    ],
    "mobile_engineer": [
        "Расскажите о себе и вашем опыте в мобильной разработке.",
        "Какие платформы вы разрабатывали? Опишите ключевые различия между iOS и Android разработкой.",
        "Как вы оптимизируете производительность мобильного приложения?",
        "Расскажите о вашем опыте с React Native, Flutter или другими кроссплатформенными фреймворками.",
        "Как вы подходите к тестированию мобильных приложений?",
        "Опишите сложную техническую задачу в мобильной разработке, которую вы решали.",
        "Как вы обеспечиваете безопасность данных в мобильном приложении?",
        "Как вы работаете с push-уведомлениями, offline-режимом и синхронизацией данных?",
    ],
    "designer": [
        "Расскажите о себе и вашем опыте в UX/UI дизайне.",
        "Опишите ваш процесс дизайна — от исследования до финального макета.",
        "Как вы проводите пользовательские исследования? Какие методы предпочитаете?",
        "Расскажите о дизайн-решении, которым вы особенно гордитесь. Как вы к нему пришли?",
        "Как вы работаете с разработчиками при передаче дизайна в разработку?",
        "Как вы измеряете успех дизайна после запуска?",
        "Как вы справляетесь с противоречиями между бизнес-требованиями и интересами пользователей?",
        "Расскажите о случае, когда пользовательское тестирование изменило ваш первоначальный дизайн.",
    ],
    "backend_engineer": [
        "Расскажите о себе и своём опыте в backend-разработке.",
        "Опишите самую сложную систему, которую вы создавали. Какие ключевые архитектурные решения вы принимали?",
        "Как вы подходите к проектированию базы данных для высоконагруженного приложения?",
        "Как вы обрабатываете ошибки, повторные попытки и отказы в production-сервисах?",
        "Опишите ваш опыт с асинхронными или событийно-ориентированными архитектурами.",
        "Как вы обеспечиваете безопасность в API и сервисах, которые создаёте?",
        "Каков ваш подход к профилированию и оптимизации производительности?",
        "Как вы балансируете технический долг и разработку новых функций?",
    ],
    "qa_engineer": [
        "Расскажите о себе и вашем опыте в обеспечении качества.",
        "Опишите ваш подход к построению стратегии тестирования для нового функционала.",
        "Каков ваш опыт с автоматизацией тестирования? Какие фреймворки использовали?",
        "Как вы решаете, что автоматизировать, а что тестировать вручную?",
        "Опишите критичный баг, который вы нашли и который предотвратил инцидент в production.",
        "Как вы поступаете, когда разработчики отклоняют ваши баг-репорты?",
        "Каков ваш опыт с нагрузочным и производительностным тестированием?",
        "Как вы поддерживаете качество в agile-среде с короткими циклами релизов?",
    ],
    "product_manager": [
        "Расскажите о себе и вашем опыте в роли продакт-менеджера.",
        "Объясните, как вы формируете и приоритизируете продуктовый роадмап.",
        "Опишите продукт, который вы довели от идеи до запуска.",
        "Как вы собираете и валидируете требования пользователей?",
        "Как вы измеряете успех фичи после запуска?",
        "Приведите пример, когда вам пришлось отказать стейкхолдеру.",
        "Как вы взаимодействуете с инженерами для обеспечения качественной разработки?",
        "Приведите пример продуктового решения, основанного на данных.",
    ],
}

_DEFAULT_ROLE = "backend_engineer"


class MockInterviewer:
    async def get_next_question(self, ctx: InterviewContext, model_override: str | None = None) -> str:
        match ctx.question_type:
            case "followup":
                return get_fallback_followup(ctx.shallow_reason or "no_depth_indicators", ctx.language)
            case "claim_verification":
                q = _resume_claim_probe_question(ctx)
                return q or get_fallback_followup("no_depth_indicators", ctx.language)
            case "verification":
                tech = ctx.pending_verification or ""
                q = get_verification_question(tech, ctx.language)
                return q or get_fallback_followup("no_depth_indicators", ctx.language)
            case "deep_technical" | "edge_cases":
                if ctx.module_type == "system_design":
                    system_design_depth = _system_design_depth_question(ctx)
                    if system_design_depth:
                        return system_design_depth
                if ctx.module_type == "coding_task":
                    coding_task_depth = _coding_task_depth_question(ctx)
                    if coding_task_depth:
                        return coding_task_depth
                if ctx.module_type == "sql_live":
                    sql_live_depth = _sql_live_depth_question(ctx)
                    if sql_live_depth:
                        return sql_live_depth
                return get_depth_escalation_question(ctx.language)
            case _:
                if ctx.module_type == "system_design":
                    system_design_main = _system_design_main_question(ctx)
                    if system_design_main:
                        return system_design_main
                if ctx.module_type == "coding_task":
                    coding_task_main = _coding_task_main_question(ctx)
                    if coding_task_main:
                        return coding_task_main
                if ctx.module_type == "sql_live":
                    sql_live_main = _sql_live_main_question(ctx)
                    if sql_live_main:
                        return sql_live_main
                if ctx.topic_phase == "intro":
                    return _resume_anchored_first_question(ctx)
                if ctx.topic_phase == "behavioral_closing":
                    return _behavioral_closing_question(ctx)
                if ctx.topic_phase == "resume_followup" and ctx.resume_anchor:
                    anchored = _resume_anchored_main_question(ctx)
                    if anchored:
                        return anchored
                anchored_main = _competency_anchored_main_question(ctx)
                if anchored_main:
                    return anchored_main
                questions = _QUESTIONS.get(ctx.target_role, _QUESTIONS[_DEFAULT_ROLE])
                idx = ctx.question_number - 1
                if 0 <= idx < len(questions):
                    return questions[idx]
                return "Хотите добавить что-то ещё о своём опыте?"


class DisabledInterviewer:
    async def get_next_question(self, ctx: InterviewContext, model_override: str | None = None) -> str:
        raise RuntimeError("AI interviewer is not configured")


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

if settings.GROQ_API_KEY:
    interviewer = LLMInterviewer(client=AsyncGroq(api_key=settings.GROQ_API_KEY))
elif settings.allow_mock_ai:
    interviewer = MockInterviewer()  # type: ignore[assignment]
else:
    interviewer = DisabledInterviewer()  # type: ignore[assignment]
