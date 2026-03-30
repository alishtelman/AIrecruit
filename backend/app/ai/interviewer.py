"""
AI Interviewer module.

Singleton `interviewer` is an LLMInterviewer (Groq) when GROQ_API_KEY is set,
otherwise falls back to MockInterviewer.
"""
import re
import logging
from dataclasses import dataclass, field

from groq import AsyncGroq

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

_MAX_QUESTION_CHARS = 240
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


@dataclass
class InterviewContext:
    target_role: str
    question_number: int          # 1-based, counts MAIN questions only
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
    current_topic: str = ""           # topic label for current main question
    topic_depth_score: float = 0.0    # running depth score for current topic (0-10)
    # v3-depth: question type and technology tracking
    question_type: str = "main"       # main | followup | verification | deep_technical | edge_cases
    mentioned_technologies: list[str] = field(default_factory=list)
    verified_skills: list[str] = field(default_factory=list)
    contradiction_flags: list[str] = field(default_factory=list)
    pending_verification: str | None = None  # technology currently being asked about

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
    words = answer.strip().split()
    word_count = len(words)
    lower = answer.lower()

    if word_count < 10:
        return True, "too_short"

    has_depth = any(w in lower for w in _DEPTH_WORDS)
    has_numbers = bool(re.search(r"\d+", answer))

    if not has_depth and not has_numbers:
        return True, "no_depth_indicators"

    if word_count < 30 and not has_numbers:
        has_example = any(hint in lower for hint in _EXAMPLE_HINTS)
        if not has_example:
            return True, "short_and_generic"

    return False, ""


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
    if len(text) <= limit:
        return text
    trimmed = text[:limit]
    if " " in trimmed:
        trimmed = trimmed.rsplit(" ", 1)[0]
    return trimmed.rstrip(" ,.;:") + "?"


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

    segments = [
        _WHITESPACE_RE.sub(" ", seg).strip()
        for seg in _QUESTION_SEGMENT_RE.findall(cleaned)
    ]

    question = ""
    for seg in segments:
        normalized = seg.lstrip(" -:;,")
        sentence_candidates = [
            sentence.strip(" ,;:")
            for sentence in re.split(r"[.!]", normalized)
            if sentence.strip(" ,;:")
        ]
        prioritized = (
            [item for item in sentence_candidates if "?" in item]
            + [item for item in sentence_candidates if "?" not in item]
        )
        for candidate in prioritized:
            if not candidate:
                continue
            lowered = candidate.lower()
            if any(lowered.startswith(prefix) for prefix in _LEADING_FILLERS):
                continue
            question = candidate if candidate.endswith("?") else f"{candidate}?"
            break
        if question:
            break

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
        question = question.split("?", 1)[0].strip() + "?"
    return _trim_question(question)


def _resume_anchored_first_question(ctx: InterviewContext) -> str:
    """Deterministic first question anchored to resume context."""
    anchor = None
    if ctx.resume_text:
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
                f"In your resume you mention '{anchor}'. Walk me through that project: "
                "your role, one key technical decision, and measurable impact?"
            )
        return (
            "Based on your resume, walk me through your most recent relevant project: "
            "your role, one key technical decision, and measurable impact?"
        )

    if anchor:
        return _trim_question(
            f"В резюме вы указали «{anchor}». Расскажите про этот проект: "
            "вашу роль, одно ключевое техническое решение и измеримый результат?"
        )
    return (
        "Опираясь на ваше резюме, расскажите про самый свежий релевантный проект: "
        "вашу роль, одно ключевое техническое решение и измеримый результат?"
    )


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
        "- Коротко: 1-2 предложения, максимум 220 символов.\n"
        "- НЕ начинай с оценки («Отлично!», «Хороший ответ», «Интересно»).\n"
        "- НЕ повторяй вопрос. НЕ давай советов и комментариев.\n"
    )

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

    # Language
    if ctx.language == "en":
        prompt += "\n## Language\nConduct this interview entirely in English.\n"

    return prompt


class LLMInterviewer:
    """Generates adaptive interview questions via Groq API."""

    def __init__(self, client: AsyncGroq) -> None:
        self._client = client

    async def get_next_question(self, ctx: InterviewContext) -> str:
        # First question: always deterministic (faster, no LLM needed)
        if ctx.question_number == 1 and not ctx.is_followup_mode:
            return _resume_anchored_first_question(ctx)

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
        max_tokens = 120 if is_non_main else 220
        temperature = 0.65 if is_non_main else 0.5

        try:
            response = await self._client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                max_tokens=max_tokens,
                temperature=temperature,
                messages=messages,
            )
            raw = response.choices[0].message.content.strip()
            normalized = _normalize_question_output(raw, ctx)
            return normalized
        except Exception:
            logger.exception("Interviewer LLM failed, using deterministic fallback question")
            return await MockInterviewer().get_next_question(ctx)


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
    async def get_next_question(self, ctx: InterviewContext) -> str:
        match ctx.question_type:
            case "followup":
                return get_fallback_followup(ctx.shallow_reason or "no_depth_indicators", ctx.language)
            case "verification":
                tech = ctx.pending_verification or ""
                q = get_verification_question(tech, ctx.language)
                return q or get_fallback_followup("no_depth_indicators", ctx.language)
            case "deep_technical" | "edge_cases":
                return get_depth_escalation_question(ctx.language)
            case _:
                questions = _QUESTIONS.get(ctx.target_role, _QUESTIONS[_DEFAULT_ROLE])
                idx = ctx.question_number - 1
                if 0 <= idx < len(questions):
                    return questions[idx]
                return "Хотите добавить что-то ещё о своём опыте?"


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

if settings.GROQ_API_KEY:
    interviewer = LLMInterviewer(client=AsyncGroq(api_key=settings.GROQ_API_KEY))
else:
    interviewer = MockInterviewer()  # type: ignore[assignment]
