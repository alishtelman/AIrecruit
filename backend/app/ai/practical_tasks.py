"""
Practical task bank for voice-first interview mode.

Trigger policy (see should_trigger_practical_task):
  - role must be in PRACTICAL_TASK_ROLES
  - answered_count >= MIN_ANSWERS_BEFORE_PRACTICAL
  - answered_count <= MAX_ANSWERS_BEFORE_PRACTICAL (don't trigger too late)
  - current stage must be in PRACTICAL_TASK_ALLOWED_STAGES (or stage unknown)
  - practical task must not have been triggered already this interview

Design rationale:
  "question 4" was too rigid — timing should depend on the interview stage,
  not a hardcoded counter. A mid-interview practical task fits best after the
  candidate has answered a few questions establishing their background, and
  before the closing behavioural phase.
"""
import random
import uuid

# Answers thresholds — trigger window, not a fixed slot
MIN_ANSWERS_BEFORE_PRACTICAL = 3   # don't trigger before at least 3 real answers
MAX_ANSWERS_BEFORE_PRACTICAL = 6   # don't trigger after more than 6 (too late)

# Stage keys where a practical task is appropriate.
# Empty string / None means stage is not tracked yet — allowed.
PRACTICAL_TASK_ALLOWED_STAGES = {
    "",          # no stage set (simple interview, no structured phases)
    "technical", # the main technical deep-dive phase
    "technical_case",
    "technical_validation",
    "practical_case",
    "resume_followup",  # still acceptable — covers follow-up on technical experience
    "resume_deep_dive",
}

# Roles that receive practical tasks.
PRACTICAL_TASK_ROLES = {
    "backend_engineer",
    "frontend_engineer",
    "qa_engineer",
    "devops_engineer",
    "data_scientist",
    "product_manager",
    "mobile_engineer",
}


def _t(ru: str, en: str, language: str) -> str:
    return ru if language == "ru" else en


PRACTICAL_TASK_BANK: dict[str, list[dict]] = {
    "backend_engineer": [
        {
            "task_type": "coding_task",
            "title_ru": "Валидация входящих данных",
            "title_en": "Request payload validation",
            "instruction_ru": (
                "Напишите функцию `validate_registration(data: dict) -> dict`, "
                "которая проверяет данные регистрации пользователя.\n\n"
                "Поля: `email` (строка, обязательное), `password` (строка, минимум 8 символов), "
                "`age` (целое, от 18 до 120).\n\n"
                "Верните `{\"valid\": true}` или `{\"valid\": false, \"errors\": [\"...\"]}`."
            ),
            "instruction_en": (
                "Write a function `validate_registration(data: dict) -> dict` "
                "that validates user registration payload.\n\n"
                "Fields: `email` (string, required), `password` (string, min 8 chars), "
                "`age` (integer, 18-120).\n\n"
                "Return `{\"valid\": true}` or `{\"valid\": false, \"errors\": [\"...\"]}`."
            ),
            "voice_intro_ru": "Сейчас открою практическое задание. Нужно реализовать валидацию входящих данных.",
            "voice_intro_en": "I'll open a practical task now. You need to implement request payload validation.",
            "language": "python",
            "starter_code": (
                "def validate_registration(data: dict) -> dict:\n"
                "    \"\"\"\n"
                "    Validates user registration data.\n"
                "    Returns {\"valid\": True} or {\"valid\": False, \"errors\": [...]}\n"
                "    \"\"\"\n"
                "    # your code here\n"
                "    pass\n"
            ),
            "examples": [
                {"input": '{"email": "a@b.com", "password": "secret123", "age": 25}', "output": '{"valid": true}'},
                {"input": '{"email": "", "password": "x", "age": 15}', "output": '{"valid": false, "errors": ["email required", "password too short", "age must be 18+"]}'},
            ],
            "evaluation_criteria": ["Корректность", "Обработка edge cases", "Читаемость"],
            "time_limit_minutes": 10,
        },
        {
            "task_type": "debugging_task",
            "title_ru": "Найди баг в пагинации",
            "title_en": "Debug the pagination function",
            "instruction_ru": (
                "В коде ниже есть баг в функции пагинации. Найдите и исправьте его.\n\n"
                "Функция должна возвращать срез списка `items` для указанной страницы."
            ),
            "instruction_en": (
                "The function below has a bug in pagination logic. Find and fix it.\n\n"
                "The function should return a slice of `items` for the given page."
            ),
            "voice_intro_ru": "Сейчас открою задание на поиск бага. Нужно найти и исправить ошибку в коде.",
            "voice_intro_en": "I'll open a debugging task. Find and fix the bug in the code.",
            "language": "python",
            "starter_code": (
                "def paginate(items: list, page: int, page_size: int) -> list:\n"
                "    \"\"\"\n"
                "    Returns the items for a given page (1-indexed).\n"
                "    Bug: returns wrong slice. Fix it.\n"
                "    \"\"\"\n"
                "    start = page * page_size          # <-- check this\n"
                "    end = start + page_size\n"
                "    return items[start:end]\n\n"
                "# paginate([1,2,3,4,5], page=1, page_size=2) should return [1, 2]\n"
                "# paginate([1,2,3,4,5], page=2, page_size=2) should return [3, 4]\n"
            ),
            "examples": [
                {"input": "page=1, page_size=2, items=[1,2,3,4,5]", "output": "[1, 2]"},
                {"input": "page=2, page_size=2, items=[1,2,3,4,5]", "output": "[3, 4]"},
            ],
            "evaluation_criteria": ["Нашёл баг", "Объяснил причину", "Правильно исправил"],
            "time_limit_minutes": 8,
        },
    ],

    "frontend_engineer": [
        {
            "task_type": "coding_task",
            "title_ru": "Дебаунс функция",
            "title_en": "Debounce function",
            "instruction_ru": (
                "Реализуйте функцию `debounce(fn, delay)`, которая откладывает вызов `fn` "
                "на `delay` миллисекунд. Если функция вызывается снова до истечения задержки, "
                "таймер сбрасывается."
            ),
            "instruction_en": (
                "Implement a `debounce(fn, delay)` function that delays calling `fn` "
                "by `delay` milliseconds. If called again before the delay expires, "
                "the timer resets."
            ),
            "voice_intro_ru": "Открою практическое задание. Нужно реализовать функцию debounce на JavaScript.",
            "voice_intro_en": "I'll open a practical task. Implement a debounce function in JavaScript.",
            "language": "javascript",
            "starter_code": (
                "/**\n"
                " * @param {Function} fn\n"
                " * @param {number} delay\n"
                " * @returns {Function}\n"
                " */\n"
                "function debounce(fn, delay) {\n"
                "  // your code here\n"
                "}\n\n"
                "// Example usage:\n"
                "// const debouncedSearch = debounce(search, 300);\n"
                "// debouncedSearch('hello');\n"
            ),
            "examples": [
                {"description": "Три быстрых вызова → только один реальный вызов через 300ms"},
            ],
            "evaluation_criteria": ["Корректная реализация", "Сброс таймера", "Чистый код"],
            "time_limit_minutes": 8,
        },
    ],

    "qa_engineer": [
        {
            "task_type": "qa_test_case_task",
            "title_ru": "Тест-кейсы для формы логина",
            "title_en": "Test cases for login form",
            "instruction_ru": (
                "Напишите тест-кейсы для формы логина.\n\n"
                "Поля формы: Email, Пароль, кнопка «Войти».\n\n"
                "Опишите минимум 6 тест-кейсов: позитивные и негативные сценарии. "
                "Формат: Описание | Входные данные | Ожидаемый результат"
            ),
            "instruction_en": (
                "Write test cases for a login form.\n\n"
                "Form fields: Email, Password, 'Sign In' button.\n\n"
                "Describe at least 6 test cases: positive and negative scenarios. "
                "Format: Description | Input | Expected result"
            ),
            "voice_intro_ru": "Открою практическое задание. Нужно написать тест-кейсы для формы логина.",
            "voice_intro_en": "I'll open a practical task. Write test cases for a login form.",
            "language": "text",
            "starter_code": (
                "# Тест-кейсы для формы логина\n"
                "# Формат: Описание | Входные данные | Ожидаемый результат\n\n"
                "1. Успешный логин | email: user@example.com, pass: correct | ...\n"
                "2. ...\n"
            ),
            "examples": [],
            "evaluation_criteria": ["Покрытие позитивных сценариев", "Негативные сценарии", "Граничные случаи", "Чёткость описания"],
            "time_limit_minutes": 10,
        },
    ],

    "devops_engineer": [
        {
            "task_type": "debugging_task",
            "title_ru": "Анализ Docker Compose конфига",
            "title_en": "Analyze Docker Compose config",
            "instruction_ru": (
                "Ниже представлен Docker Compose конфиг с несколькими проблемами. "
                "Найдите проблемы и опишите, как их исправить."
            ),
            "instruction_en": (
                "The Docker Compose config below has several issues. "
                "Find the issues and describe how to fix them."
            ),
            "voice_intro_ru": "Открою практическое задание. Нужно найти проблемы в Docker Compose конфиге.",
            "voice_intro_en": "I'll open a practical task. Find issues in the Docker Compose config.",
            "language": "other",
            "starter_code": (
                "version: '3.8'\n"
                "services:\n"
                "  web:\n"
                "    image: myapp:latest\n"
                "    ports:\n"
                "      - '80:80'\n"
                "    environment:\n"
                "      DATABASE_URL: postgres://user:password@db/mydb\n"
                "    depends_on:\n"
                "      - db\n"
                "  db:\n"
                "    image: postgres\n"
                "    volumes:\n"
                "      - ./data:/var/lib/postgresql/data\n"
                "    # Missing: POSTGRES_PASSWORD, POSTGRES_USER, POSTGRES_DB env vars\n"
                "    # Missing: healthcheck\n"
                "    # Missing: restart policy\n"
                "\n"
                "# Your analysis:\n"
                "# Problem 1: ...\n"
                "# Fix: ...\n"
            ),
            "examples": [],
            "evaluation_criteria": ["Нашёл все проблемы", "Правильные исправления", "Безопасность конфига"],
            "time_limit_minutes": 10,
        },
    ],

    "data_scientist": [
        {
            "task_type": "sql_task",
            "title_ru": "SQL-запрос: топ пользователи",
            "title_en": "SQL query: top users by revenue",
            "instruction_ru": (
                "Дана таблица `orders(user_id, amount, created_at)`.\n\n"
                "Напишите SQL-запрос, который возвращает топ-5 пользователей "
                "по суммарной выручке за последние 30 дней. "
                "Вывести: `user_id`, `total_revenue`, отсортировать по убыванию."
            ),
            "instruction_en": (
                "Given table `orders(user_id, amount, created_at)`.\n\n"
                "Write a SQL query that returns the top 5 users "
                "by total revenue over the last 30 days. "
                "Output: `user_id`, `total_revenue`, sorted descending."
            ),
            "voice_intro_ru": "Открою SQL задание. Нужно написать запрос для топ пользователей по выручке.",
            "voice_intro_en": "I'll open a SQL task. Write a query to find the top users by revenue.",
            "language": "sql",
            "starter_code": (
                "-- Table: orders(user_id INT, amount DECIMAL, created_at TIMESTAMP)\n\n"
                "SELECT\n"
                "    -- your code here\n"
                "FROM orders\n"
                "WHERE -- filter for last 30 days\n"
                "GROUP BY user_id\n"
                "ORDER BY -- total revenue descending\n"
                "LIMIT 5;\n"
            ),
            "examples": [
                {"description": "Returns user_id and total_revenue for the top 5 buyers in the last 30 days"},
            ],
            "evaluation_criteria": ["Правильный SQL", "Фильтрация по дате", "Сортировка и LIMIT"],
            "time_limit_minutes": 10,
        },
    ],

    "product_manager": [
        {
            "task_type": "product_case_task",
            "title_ru": "Приоритизация бэклога",
            "title_en": "Backlog prioritization",
            "instruction_ru": (
                "У вас 5 фич в бэклоге. Приоритизируйте их, используя любой фреймворк "
                "(RICE, MoSCoW, ICE, и т.д.).\n\n"
                "Фичи:\n"
                "1. Push-уведомления\n"
                "2. Тёмная тема\n"
                "3. Оффлайн-режим\n"
                "4. Реферальная программа\n"
                "5. Ускорение загрузки (с 3s до 1s)\n\n"
                "Контекст: B2C мобильное приложение, DAU 50k, retention D30 = 15%."
            ),
            "instruction_en": (
                "You have 5 features in the backlog. Prioritize them using any framework "
                "(RICE, MoSCoW, ICE, etc.).\n\n"
                "Features:\n"
                "1. Push notifications\n"
                "2. Dark mode\n"
                "3. Offline mode\n"
                "4. Referral program\n"
                "5. Performance improvement (3s → 1s load time)\n\n"
                "Context: B2C mobile app, DAU 50k, D30 retention 15%."
            ),
            "voice_intro_ru": "Открою кейс на приоритизацию. Нужно расставить приоритеты для 5 фич.",
            "voice_intro_en": "I'll open a product case. Prioritize these 5 features for the backlog.",
            "language": "text",
            "starter_code": (
                "Фреймворк: [RICE / MoSCoW / ICE / другой]\n\n"
                "Приоритеты:\n"
                "1. [Фича] — [Обоснование]\n"
                "2. ...\n\n"
                "Краткое обоснование топ-приоритета:\n"
            ),
            "examples": [],
            "evaluation_criteria": ["Обоснованный выбор фреймворка", "Качество аргументации", "Бизнес-ориентированность"],
            "time_limit_minutes": 12,
        },
    ],

    "mobile_engineer": [
        {
            "task_type": "coding_task",
            "title_ru": "Реализация LRU кэша",
            "title_en": "Implement LRU cache",
            "instruction_ru": (
                "Реализуйте класс `LRUCache` с методами `get(key)` и `put(key, value)`.\n\n"
                "Кэш должен хранить не более `capacity` элементов. "
                "При превышении ёмкости вытесняется наименее давно используемый элемент."
            ),
            "instruction_en": (
                "Implement an `LRUCache` class with `get(key)` and `put(key, value)` methods.\n\n"
                "The cache should hold at most `capacity` items. "
                "When capacity is exceeded, evict the least recently used item."
            ),
            "voice_intro_ru": "Открою задание на реализацию LRU кэша. Это классическая задача на интервью.",
            "voice_intro_en": "I'll open a coding task. Implement an LRU cache — a classic interview problem.",
            "language": "python",
            "starter_code": (
                "class LRUCache:\n"
                "    def __init__(self, capacity: int):\n"
                "        self.capacity = capacity\n"
                "        # your code here\n\n"
                "    def get(self, key: int) -> int:\n"
                "        # return value or -1 if not found\n"
                "        pass\n\n"
                "    def put(self, key: int, value: int) -> None:\n"
                "        # insert or update key-value pair\n"
                "        pass\n"
            ),
            "examples": [
                {"input": "capacity=2; put(1,1); put(2,2); get(1); put(3,3); get(2)", "output": "get(1)=1; get(2)=-1 (evicted)"},
            ],
            "evaluation_criteria": ["O(1) операции", "Корректное вытеснение", "Чистый код"],
            "time_limit_minutes": 12,
        },
    ],
}


def get_practical_task(role: str, language: str = "ru") -> dict | None:
    """
    Returns a randomly selected practical task for the given role and language,
    or None if the role has no tasks defined.
    """
    tasks = PRACTICAL_TASK_BANK.get(role)
    if not tasks:
        return None
    task = random.choice(tasks)
    return {
        "task_id": str(uuid.uuid4()),
        "task_type": task["task_type"],
        "title": task[f"title_{language}"] if f"title_{language}" in task else task.get("title_en", task.get("title_ru", "")),
        "instruction": task[f"instruction_{language}"] if f"instruction_{language}" in task else task.get("instruction_en", task.get("instruction_ru", "")),
        "voice_intro": task.get(f"voice_intro_{language}") or task.get("voice_intro_ru"),
        "language": task.get("language"),
        "starter_code": task.get("starter_code"),
        "examples": task.get("examples", []),
        "time_limit_minutes": task.get("time_limit_minutes", 10),
        "evaluation_criteria": task.get("evaluation_criteria", []),
    }


def should_trigger_practical_task(
    role: str,
    answered_count: int,
    already_triggered: bool,
    current_stage_key: str | None = None,
) -> bool:
    """
    Policy function: returns True when a practical task should be injected.

    Checks in order:
      1. Not already triggered this interview.
      2. Role supports practical tasks.
      3. Enough answers so the AI has context about the candidate.
      4. Not too late (don't disrupt closing/behavioral phase).
      5. Current stage is appropriate (technical/practical phases, or unknown).
    """
    if already_triggered:
        return False
    if role not in PRACTICAL_TASK_ROLES:
        return False
    if answered_count < MIN_ANSWERS_BEFORE_PRACTICAL:
        return False
    if answered_count > MAX_ANSWERS_BEFORE_PRACTICAL:
        return False
    # Stage check: if stage is tracked, only allow during appropriate phases
    stage = (current_stage_key or "").strip().lower()
    if stage and stage not in PRACTICAL_TASK_ALLOWED_STAGES:
        return False
    return True
